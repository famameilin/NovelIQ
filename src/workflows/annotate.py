"""
核心标注工作流（LangGraph 标注 Agent）

阶段 1-4 合并为 agent 任务，消歧集成进 agent 循环（身份记忆工具），
不再存在独立的增量/最终消歧任务
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from loguru import logger
from sqlalchemy.orm import Session

from src.api.models.events import StreamEvent
from src.config import settings
from src.config.analysis_logger import AnalysisLogger
from src.storage.repositories import AnnotationRepository, ChunkRepository


async def run_annotate(
    run_id: str,
    session: Session,
    resume: bool = False,
    analysis_logger: AnalysisLogger | None = None,
    novel_id: str = "default",
    novel_title: str | None = None,
    use_context_enhancement: bool = True,
    use_rag: bool = True,
    is_cancelled: Callable[[], bool] | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> tuple[int, int, int]:
    """
    执行标注流程（每 chunk 一个标注 agent 任务）

    - 超长章节：同一章节切分出的多个子 chunk 各启动一个子代理会话，
      共享同一身份记忆，state 注入同章节其余内容保持叙事连贯
    - 身份消歧：由 agent 通过 register_identity/lookup_identity 工具在循环内完成，
      结果持久化到身份记忆 checkpoint（复用 disambig_checkpoint 表）

    Returns:
        Tuple[int, int, int]: (成功数量, 0, 总块数)
    """
    from src.agents.annotation import (
        AnnotationAgentRunError,
        IdentityMemory,
        load_identity_memory,
        run_annotation_agent,
        save_identity_memory,
    )
    from src.workflows.annotate_helpers import (
        _extract_and_save_global_context,
        _init_evidence_service,
        _store_annotation_results,
        project_graph_tables,
    )

    start_time = time.time()

    chunk_repo = ChunkRepository(session)
    chunk_rows = chunk_repo.fetch_chunks_with_chapter(run_id)
    all_chunks = [(chunk_id, chunk_text) for chunk_id, _chapter_id, chunk_text in chunk_rows]

    total_chunks = len(all_chunks)

    if total_chunks == 0:
        logger.warning("no chunks found in db")
        return 0, 0, 0

    annotated_ids: set[int] = set()
    if resume:
        ann_repo = AnnotationRepository(session)
        annotated_ids = ann_repo.fetch_annotated_chunk_ids(run_id)
        logger.info(f"resume mode: {len(annotated_ids)} chunks already annotated")

    evidence_service = _init_evidence_service(session, novel_id, use_rag, run_id=run_id, emitter=emitter)

    from src.agents.llm import build_chat_model

    llm = build_chat_model("annotation")
    fallback_llm = (
        build_chat_model("annotation_fallback")
        if settings.analysis.annotation_fallback_enabled
        else None
    )

    global_context_str = await _extract_and_save_global_context(
        session,
        all_chunks,
        novel_id,
        novel_title,
        use_context_enhancement,
        resume,
        llm,
        run_id=run_id,
    )

    memory: IdentityMemory = IdentityMemory()
    if resume:
        memory = load_identity_memory(session, run_id)

    success_count = 0
    newly_annotated = 0

    checkpoint_interval = max(1, settings.analysis.checkpoint_interval)
    projection_interval = max(1, settings.analysis.projection_interval)
    max_sub_agents = max(1, settings.analysis.agents.annotation.max_sub_agents)
    sub_chunk_max_chars = max(1, settings.analysis.agents.annotation.sub_chunk_max_chars)
    chapter_groups = _group_chunks_by_chapter(chunk_rows)

    if emitter and total_chunks > 0:
        await emitter(
            StreamEvent(
                action="progress",
                sub_stage="agent",
                current=len(annotated_ids),
                total=total_chunks,
                sub_percent=(len(annotated_ids) / total_chunks) * 100 if total_chunks > 0 else 0.0,
                message=(
                    f"共 {total_chunks} 个 chunk，{len(annotated_ids)} 个已标注，"
                    f"剩余 {total_chunks - len(annotated_ids)} 个待标注"
                ),
            )
        )

    cancelled = False
    for chapter_order, (chapter_id, chapter_chunks) in enumerate(chapter_groups, start=1):
        pending_chunks = [
            (chunk_id, chunk_text)
            for chunk_id, chunk_text in chapter_chunks
            if chunk_id not in annotated_ids
        ]
        if not pending_chunks:
            continue

        uses_sub_agents = len(chapter_chunks) > 1
        chapter_label = chapter_id if chapter_id is not None else chapter_order
        sub_agent_position = {
            chunk_id: index
            for index, (chunk_id, _chunk_text) in enumerate(chapter_chunks, start=1)
        }

        # 身份记忆和伏笔 ledger 都要求按原文顺序收口，因此 dispatcher 按配置分波次，
        # 每个波次最多委派 max_sub_agents 个独立会话，并按 chunk 顺序提交结果
        for wave in _iter_dispatch_waves(pending_chunks, max_sub_agents=max_sub_agents):
            for chunk_id, chunk_text in wave:
                if is_cancelled and is_cancelled():
                    logger.warning("Annotation cancelled at chunk {}/{}", chunk_id, total_chunks)
                    cancelled = True
                    break

                sub_position = sub_agent_position[chunk_id]
                sub_stage = "sub_agent" if uses_sub_agents else "agent"
                chapter_context = _build_chapter_context(
                    chapter_chunks,
                    current_chunk_id=chunk_id,
                    max_context_chunks=max_sub_agents,
                    max_chars_per_chunk=sub_chunk_max_chars,
                )
                prev_summary = _fetch_prev_chunk_summary(session, run_id, chunk_id, all_chunks)

                if emitter:
                    sub_percent = (
                        ((sub_position - 1) / len(chapter_chunks)) * 100
                        if uses_sub_agents
                        else ((len(annotated_ids) + success_count) / total_chunks) * 100
                    )
                    await emitter(
                        StreamEvent(
                            action="progress",
                            stage="annotate",
                            sub_stage=sub_stage,
                            chunk_id=chunk_id,
                            current=len(annotated_ids) + success_count,
                            total=total_chunks,
                            percent=10 + ((len(annotated_ids) + success_count) / total_chunks) * 70,
                            sub_percent=sub_percent,
                            message=(
                                f"第 {chapter_label} 章子代理 {sub_position}/{len(chapter_chunks)}"
                                if uses_sub_agents
                                else f"第 {chapter_label} 章标注 Agent"
                            ),
                        )
                    )

                try:
                    result, memory = await run_annotation_agent(
                        chunk_text=chunk_text,
                        chunk_id=chunk_id,
                        total_chunks=total_chunks,
                        novel_id=novel_id,
                        novel_title=novel_title,
                        chapter_id=chapter_label,
                        chapter_context=chapter_context,
                        global_context=global_context_str,
                        prev_summary=prev_summary,
                        memory=memory,
                        evidence_service=evidence_service,
                        llm=llm,
                        model_task_type="annotation",
                        run_id=run_id,
                        session=session,
                    )

                except AnnotationAgentRunError:
                    if fallback_llm is None:
                        raise
                    logger.warning("annotation primary model failed for chunk {}, switching to fallback", chunk_id)
                    result, memory = await run_annotation_agent(
                        chunk_text=chunk_text,
                        chunk_id=chunk_id,
                        total_chunks=total_chunks,
                        novel_id=novel_id,
                        novel_title=novel_title,
                        chapter_id=chapter_label,
                        chapter_context=chapter_context,
                        global_context=global_context_str,
                        prev_summary=prev_summary,
                        memory=memory,
                        evidence_service=evidence_service,
                        llm=fallback_llm,
                        model_task_type="annotation_fallback",
                        run_id=run_id,
                        session=session,
                    )

                _store_annotation_results(
                    session,
                    chunk_id,
                    result.annotation,
                    chunk_text,
                    use_context_enhancement,
                    run_id=run_id,
                    foreshadowing=result.foreshadowing,
                    dialogue_speakers=result.dialogue_speakers,
                    dialogues=result.dialogues,
                    dialogue_tones=result.dialogue_tones,
                    dialogue_identity_clues=result.dialogue_identity_clues,
                    relations=result.relations,
                )
                success_count += 1
                newly_annotated += 1
                progress_count = len(annotated_ids) + success_count
                if emitter:
                    await emitter(
                        StreamEvent(
                            action="progress",
                            stage="annotate",
                            sub_stage=sub_stage,
                            chunk_id=chunk_id,
                            current=progress_count,
                            total=total_chunks,
                            percent=10 + (progress_count / total_chunks) * 70,
                            sub_percent=(
                                (sub_position / len(chapter_chunks)) * 100
                                if uses_sub_agents
                                else (progress_count / total_chunks) * 100
                            ),
                            message=(
                                f"第 {chapter_label} 章子代理 {sub_position}/{len(chapter_chunks)} 完成"
                                if uses_sub_agents
                                else f"标注 chunk {progress_count}/{total_chunks}"
                            ),
                        )
                    )
                if run_id and newly_annotated % checkpoint_interval == 0:
                    save_identity_memory(session, run_id, memory)
                if run_id and newly_annotated % projection_interval == 0:
                    project_graph_tables(run_id, to_chunk=chunk_id, session=session)
                    if evidence_service:
                        evidence_service.invalidate_cache()
            if cancelled:
                break
        if cancelled:
            break

    if run_id and all_chunks:
        final_chunk_id = all_chunks[-1][0]
        save_identity_memory(session, run_id, memory)
        project_graph_tables(run_id, from_chunk=0, to_chunk=final_chunk_id, session=session, rebuild=True)
    if evidence_service:
        evidence_service.invalidate_cache()

    elapsed = time.time() - start_time
    logger.info(f"annotate completed success={success_count} time={elapsed:.2f}s")
    logger.info("\n=== Annotate Statistics ===")
    logger.info(f"Total chunks: {total_chunks}")
    logger.info(f"Annotated: {success_count}")
    logger.info(f"Processing time: {elapsed:.2f}s")
    return success_count, 0, total_chunks


def _group_chunks_by_chapter(
    chunk_rows: list[tuple[int, int | None, str]],
) -> list[tuple[int | None, list[tuple[int, str]]]]:
    """
    2026-08-02 用于按数据库章节序号构建保持原文顺序的 Agent dispatcher 输入
    """
    chapters: dict[int | None, list[tuple[int, str]]] = {}
    for chunk_id, chapter_id, chunk_text in chunk_rows:
        chapters.setdefault(chapter_id, []).append((chunk_id, chunk_text))
    return list(chapters.items())


def _build_chapter_context(
    chapter_chunks: list[tuple[int, str]],
    *,
    current_chunk_id: int,
    max_context_chunks: int,
    max_chars_per_chunk: int,
) -> str | None:
    """
    2026-08-02 用于为章节子代理选择相邻兄弟块并按原文顺序生成受限上下文
    """
    current_index = next(
        (index for index, (chunk_id, _text) in enumerate(chapter_chunks) if chunk_id == current_chunk_id),
        None,
    )
    if current_index is None:
        raise ValueError(f"current chunk is not in chapter dispatcher: {current_chunk_id}")

    # 同章节上下文只能读取当前子块之前的原文，避免把后续揭示写入前序标注记忆
    candidates = [
        (index, chunk_id, chunk_text)
        for index, (chunk_id, chunk_text) in enumerate(chapter_chunks[:current_index])
    ]
    if not candidates:
        return None

    selected = sorted(
        sorted(
            candidates,
            key=lambda item: (abs(item[0] - current_index), item[0]),
        )[: max(1, max_context_chunks)],
        key=lambda item: item[0],
    )
    total = len(chapter_chunks)
    return "\n\n".join(
        (
            f"[同章节子块 {index + 1}/{total} chunk {chunk_id}]\n"
            f"{chunk_text[:max(1, max_chars_per_chunk)]}"
        )
        for index, chunk_id, chunk_text in selected
    )


def _iter_dispatch_waves(
    chunks: list[tuple[int, str]],
    *,
    max_sub_agents: int,
) -> list[list[tuple[int, str]]]:
    """
    2026-08-02 用于把超长章节拆成不超过配置上限的子代理委派波次
    """
    wave_size = max(1, max_sub_agents)
    return [
        chunks[start : start + wave_size]
        for start in range(0, len(chunks), wave_size)
    ]


def _fetch_prev_chunk_summary(
    session: Session,
    run_id: str,
    chunk_id: int,
    all_chunks: list[tuple[int, str]],
) -> str | None:
    """查询前一个已标注 chunk 的摘要作为前文摘要"""
    from src.storage.repositories.stats.summaries import fetch_chunk_summaries_by_range

    chunk_ids = [cid for cid, _ in all_chunks if cid < chunk_id]
    if not chunk_ids:
        return None
    prev_id = chunk_ids[-1]
    try:
        summaries = fetch_chunk_summaries_by_range(session, run_id, prev_id, prev_id)
        if summaries:
            return summaries[0][1]
    except Exception as e:  # noqa: BLE001
        logger.debug("failed to fetch prev chunk summary: {}", e)
    return None
