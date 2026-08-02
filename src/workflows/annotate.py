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
    all_chunks = chunk_repo.fetch_chunk_texts(run_id)

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

    # 构建章节上下文：同一 chapter 的兄弟子块文本
    chapter_ctx_by_chunk: dict[int, str] = {}
    chapters: dict[int | None, list[int]] = {}
    chapter_ids: list[int | None] = []
    chunk_text_by_id: dict[int, str] = dict(all_chunks)
    for chunk_id, _text in all_chunks:
        chapter_id = _fetch_chunk_chapter_id(session, run_id, chunk_id)
        if chapter_id not in chapters:
            chapters[chapter_id] = []
            chapter_ids.append(chapter_id)
        chapters[chapter_id].append(chunk_id)
    for chunk_id, _text in all_chunks:
        chapter_id = _find_chapter_for_chunk(chunk_id, chapters)
        siblings = [cid for cid in chapters.get(chapter_id, []) if cid != chunk_id]
        if len(siblings) <= 1:
            continue
        ctx_parts = []
        for cid in sorted(siblings)[:3]:
            ctx_parts.append(chunk_text_by_id.get(cid, "")[:1200])
        chapter_ctx_by_chunk[chunk_id] = "\n\n".join(ctx_parts)

    chapter_index_by_chunk: dict[int, int] = {}
    for index, chapter_id in enumerate(chapter_ids, start=1):
        for chunk_id in chapters[chapter_id]:
            chapter_index_by_chunk[chunk_id] = index

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

    for idx, (chunk_id, chunk_text) in enumerate(all_chunks):
        if chunk_id in annotated_ids:
            logger.debug(f"skipping already annotated chunk_id={chunk_id}")
            continue

        if is_cancelled and is_cancelled():
            logger.warning(f"Annotation cancelled at chunk {idx + 1}/{total_chunks}")
            break

        prev_summary = _fetch_prev_chunk_summary(session, run_id, chunk_id, all_chunks)

        try:
            result, memory = await run_annotation_agent(
                chunk_text=chunk_text,
                chunk_id=chunk_id,
                total_chunks=total_chunks,
                novel_id=novel_id,
                novel_title=novel_title,
                chapter_id=chapter_index_by_chunk.get(chunk_id),
                chapter_context=chapter_ctx_by_chunk.get(chunk_id),
                global_context=global_context_str,
                prev_summary=prev_summary,
                memory=memory,
                evidence_service=evidence_service,
                llm=llm,
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
                        sub_stage="agent",
                        current=progress_count,
                        total=total_chunks,
                        percent=10 + (progress_count / total_chunks) * 70,
                        sub_percent=(progress_count / total_chunks) * 100,
                        message=f"标注 chunk {progress_count}/{total_chunks}",
                    )
                )
            if run_id and newly_annotated % checkpoint_interval == 0:
                save_identity_memory(session, run_id, memory)
            if run_id and newly_annotated % projection_interval == 0:
                project_graph_tables(run_id, to_chunk=chunk_id, session=session)
                if evidence_service:
                    evidence_service.invalidate_cache()
        except Exception as e:
            logger.error(f"chunk annotation failed for chunk_id={chunk_id}: {str(e)}")
            raise

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


def _fetch_chunk_chapter_id(session: Session, run_id: str, chunk_id: int) -> int | None:
    """查询 chunk 的章节 ID"""
    from sqlalchemy import select

    from src.storage.models import Chunk as ChunkModel

    result = session.execute(
        select(ChunkModel.chapter_id).where(ChunkModel.run_id == run_id, ChunkModel.chunk_id == chunk_id)
    ).scalar_one_or_none()
    return int(result) if result is not None else None


def _find_chapter_for_chunk(chunk_id: int, chapters: dict[int | None, list[int]]) -> int | None:
    for chapter_id, chunk_ids in chapters.items():
        if chunk_id in chunk_ids:
            return chapter_id
    return None


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
