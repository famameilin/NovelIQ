"""
章节级 LangGraph 标注工作流
"""

from __future__ import annotations

import time
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from typing import TYPE_CHECKING, Any
from typing import cast as type_cast

from loguru import logger
from sqlalchemy.orm import Session

from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundEntity,
    BoundEntityDirectory,
    BoundEvent,
    ChunkParagraphInfo,
    EntityType,
    PendingCase,
    ResolvedCase,
    TextEvidence,
)
from src.agents.stream import AgentStream
from src.api.models.events import StreamEvent
from src.config.analysis_logger import AnalysisLogger
from src.storage.db import get_session_factory
from src.storage.repositories import (
    ChapterRepository,
    DatabaseAnnotationQueryService,
    ParagraphRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Row

    from src.agents.annotation.fact_graph import FactGraph


def _group_chunks_by_chapter(
    chapter_rows: list[tuple[int, str]],
) -> list[tuple[int, list[tuple[int, str]]]]:
    """2026-08-05 用于按真实非空 chapter_id 聚合完整 current 并保持原文顺序

    M9a-2：chunks 表合并进 chapters 后，存储层直接返回 (chapter_id, text)，
    运行时章 chunk 身份 = chapter_id（1 基）；超长章在 _split_chapter_sub_chunks
    处再切负 ID 子块。
    """
    chapters: list[tuple[int, list[tuple[int, str]]]] = []
    for chapter_id, chapter_text in chapter_rows:
        if chapter_id is None or chapter_id <= 0:
            raise ValueError(f"chapters.chapter_id 必须真实且非空，run 需要重新预处理: chapter_id={chapter_id}")
        chapters.append((chapter_id, [(chapter_id, chapter_text)]))
    return chapters


def _split_chapter_sub_chunks(
    chapter_text: str,
    chapter_paragraphs: Sequence[Row],
    *,
    chapter_chunk_id: int,
    max_chars: int,
) -> list[tuple[int, str, int]]:
    """2026-08-14 M7(§20)在段落边界切超长章为运行时子块(不落库/不进指标/不重建段落边界)，
    边界取 paragraphs.local_start_char，ID -1,-2…；≤max_chars或无边界原样返回，单段超长允许略超(≥max_chars成块)。
    2026-08-15 返回(子块ID, 文本, 章内偏移)供对话 start/end 重映射回章坐标。
    """
    if len(chapter_text) <= max_chars:
        return [(chapter_chunk_id, chapter_text, 0)]
    usable_boundaries = sorted(
        {int(row.local_start_char) for row in chapter_paragraphs if 0 < int(row.local_start_char) < len(chapter_text)}
    )
    if not usable_boundaries:
        return [(chapter_chunk_id, chapter_text, 0)]
    sub_chunks: list[tuple[int, str, int]] = []
    sub_index = 1
    block_start = 0
    for boundary in usable_boundaries + [len(chapter_text)]:
        if boundary <= block_start:
            continue
        if boundary - block_start >= max_chars:
            sub_chunks.append((-sub_index, chapter_text[block_start:boundary], block_start))
            sub_index += 1
            block_start = boundary
    if block_start < len(chapter_text) or not sub_chunks:
        sub_chunks.append((-sub_index, chapter_text[block_start:], block_start))
    return sub_chunks


def _build_sub_chunk_paragraph_info(
    chapter_paragraphs: Sequence[Row],
    *,
    sub_chunk_offset: int,
    sub_chunk_text: str,
) -> ChunkParagraphInfo:
    """为子块构建段落坐标映射"""
    paragraph_ids: list[int] = []
    char_spans: list[tuple[int, int]] = []
    texts: list[str] = []
    for row in chapter_paragraphs:
        local_start = int(row.local_start_char)
        local_end = int(row.local_end_char)
        if local_start >= sub_chunk_offset and local_end <= sub_chunk_offset + len(sub_chunk_text):
            paragraph_ids.append(int(row.paragraph_id))
            sub_start = local_start - sub_chunk_offset
            sub_end = local_end - sub_chunk_offset
            char_spans.append((sub_start, sub_end))
            texts.append(str(row.text))
    if not paragraph_ids:
        raise ValueError(f"子块无段落事实源: sub_chunk_offset={sub_chunk_offset}")
    return ChunkParagraphInfo(
        paragraph_ids=paragraph_ids,
        char_spans=char_spans,
        texts=texts,
    )


def _merge_sub_chunk_entities(directories: list[BoundEntityDirectory]) -> list[BoundEntity]:
    """2026-08-14 M7 用于按规范化名称合并去重实体目录（同名保留先出现）"""
    seen: set[str] = set()
    merged: list[BoundEntity] = []
    for directory in directories:
        for entity in directory.entities:
            key = unicodedata.normalize("NFC", entity.name).strip().casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(entity)
    return merged


def _merge_sub_chunk_annotations(
    annotations: list[BoundChapterAnnotation],
    *,
    chapter_chunk_id: int,
    sub_chunk_offsets: Sequence[int],
) -> BoundChapterAnnotation:
    """2026-08-14 M7（§20）用于把同一章各子块标注合并为单 chunk 章节标注

    chapter_summary 按子块顺序换行拼接；chunks 收缩为单条
    BoundChunkAnnotation（chunk_id=章真实 chunk_id），metrics 取第一个子块，
    实体目录同名去重（保留先出现），其余领域按子块顺序拼接。

    2026-08-15：第 2+ 子块的对话 start/end 是子块相对坐标，合并落库前按
    sub_chunk_offsets 加回子块在章文本内的起始偏移，与整章运行口径一致。

    2026-08-22事件 node_id/tree_id 与伏笔 setup_node_id 均为服务端
    一次性 uuid，合并只平移文本坐标，不再重排事件序号。
    """
    if not annotations:
        raise ValueError("子块标注列表不能为空")
    if len(sub_chunk_offsets) != len(annotations):
        raise ValueError("sub_chunk_offsets 长度必须与子块标注列表一致")
    for annotation in annotations:
        if len(annotation.chunks) != 1:
            raise ValueError("子块标注必须恰好包含一个 chunk")
    first_chunk = annotations[0].chunks[0]
    merged_events: list[BoundEvent] = []
    merged_foreshadowings = []
    for index, annotation in enumerate(annotations):
        sub_chunk = annotation.chunks[0]
        for event in sub_chunk.events:
            remapped = _remap_bound_event(event, sub_chunk_offsets[index])
            # 2026-08-22node_id/tree_id/setup_node_id 均为服务端一次性
            # uuid，合并无需重排；Evidence 中的全局段落 ID 是持久化锚点的权威值，
            # 合并后同步写入 anchor_paragraph_ids
            if remapped.evidence:
                global_ids = list(remapped.evidence[0].paragraph_ids)
            else:
                global_ids = list(remapped.anchor_paragraph_ids)
            remapped = remapped.model_copy(update={"anchor_paragraph_ids": global_ids})
            merged_events.append(remapped)
        for foreshadowing in sub_chunk.foreshadowings:
            merged_foreshadowings.append(foreshadowing.model_copy())
    return BoundChapterAnnotation(
        chapter_summary="\n".join(annotation.chapter_summary for annotation in annotations),
        chunks=[
            BoundChunkAnnotation(
                chunk_id=chapter_chunk_id,
                metrics=first_chunk.metrics,
                entities=BoundEntityDirectory(
                    entities=_merge_sub_chunk_entities([annotation.chunks[0].entities for annotation in annotations])
                ),
                character_observations=[
                    item for annotation in annotations for item in annotation.chunks[0].character_observations
                ],
                dialogues=[
                    _remap_bound_dialogue(item, sub_chunk_offsets[index])
                    for index, annotation in enumerate(annotations)
                    for item in annotation.chunks[0].dialogues
                ],
                events=merged_events,
                relations=[item for annotation in annotations for item in annotation.chunks[0].relations],
                foreshadowings=merged_foreshadowings,
            )
        ],
    )


def _remap_bound_dialogue(dialogue: BoundDialogue, sub_chunk_offset: int) -> BoundDialogue:
    """2026-08-15 用于把子块相对对话坐标平移回章文本坐标（首块偏移 0 不变）"""
    if sub_chunk_offset <= 0:
        return dialogue
    return dialogue.model_copy(
        update={
            "start": dialogue.start + sub_chunk_offset,
            "end": dialogue.end + sub_chunk_offset,
        }
    )


def _remap_bound_event(event: BoundEvent, sub_chunk_offset: int) -> BoundEvent:
    """2026-08-18 用于把子块相对事件锚点坐标平移回章文本坐标（首块偏移 0 不变）

    事件锚点的 char_start/char_end 和 evidence 内的 char_start/char_end 都需要
    按子块偏移量平移；anchor_paragraph_ids、causal_event_refs、description、
    participants、text_hash 不变（text_hash 基于段落文本，与章内偏移无关）。
    """
    if sub_chunk_offset <= 0:
        return event
    new_evidence = [
        TextEvidence(
            paragraph_ids=list(ev.paragraph_ids),
            char_start=ev.char_start + sub_chunk_offset,
            char_end=ev.char_end + sub_chunk_offset,
            text_hash=ev.text_hash,
        )
        for ev in event.evidence
    ]
    return event.model_copy(
        update={
            "char_start": event.char_start + sub_chunk_offset,
            "char_end": event.char_end + sub_chunk_offset,
            "evidence": new_evidence,
        }
    )


def _remap_case_anchor[CaseT: (PendingCase, ResolvedCase)](
    case: CaseT,
    sub_chunk_ids: set[int],
    chapter_chunk_id: int,
) -> CaseT:
    """2026-08-14 M7 用于把案例锚定 chunk 从子块负 ID 映射回章真实 chunk_id"""
    anchor = case.target_ref.get("chunk_id")
    if anchor in sub_chunk_ids:
        case.target_ref["chunk_id"] = chapter_chunk_id
    if isinstance(case, PendingCase) and case.chunk_id in sub_chunk_ids:
        case.chunk_id = chapter_chunk_id
    return case


def _merge_sub_chunk_results(
    results: list[AgentRunResult],
    *,
    chapter_chunk_id: int,
    sub_chunk_offsets: Sequence[int],
) -> AgentRunResult:
    """2026-08-14 M7（§20）用于把同一章各子块 Agent 结果合并为单次完成事务输入

    子块运行时负 chunk_id 一律映射回章真实 chunk_id（案例不落负 ID）；
    审计字段按并集/拼接合并，sub_chunk_index 归零（结果已合并为单章）。

    2026-08-15：sub_chunk_offsets 为各子块在章文本内的起始偏移（与 results
    顺序一致），用于把第 2+ 子块的对话坐标重映射回章坐标。
    """
    if not results:
        raise ValueError("子块 Agent 结果列表不能为空")
    sub_chunk_ids = {result.annotation.chunks[0].chunk_id for result in results}
    first = results[0]
    return AgentRunResult(
        run_id=first.run_id,
        chapter_id=first.chapter_id,
        annotation=_merge_sub_chunk_annotations(
            [result.annotation for result in results],
            chapter_chunk_id=chapter_chunk_id,
            sub_chunk_offsets=sub_chunk_offsets,
        ),
        resolved_cases=[
            _remap_case_anchor(
                case,
                sub_chunk_ids,
                chapter_chunk_id,
            )
            for result in results
            for case in result.resolved_cases
        ],
        pushed_cases=[
            _remap_case_anchor(
                case,
                sub_chunk_ids,
                chapter_chunk_id,
            )
            for result in results
            for case in result.pushed_cases
        ],
        audit=AgentRunAudit(
            allow_future_context=first.audit.allow_future_context,
            write_records=[record for result in results for record in result.audit.write_records],
            rotation_case_ids=list(
                dict.fromkeys(case_id for result in results for case_id in result.audit.rotation_case_ids)
            ),
            authorized_chapter_ids=sorted(
                {case_id for result in results for case_id in result.audit.authorized_chapter_ids}
            ),
            authorized_text_paragraph_ids=sorted(
                {paragraph_id for result in results for paragraph_id in result.audit.authorized_text_paragraph_ids}
            ),
            authorized_event_ids=sorted(
                {event_id for result in results for event_id in result.audit.authorized_event_ids}
            ),
            closed_case_ids=[case_id for result in results for case_id in result.audit.closed_case_ids],
        ),
    )


def _load_chapter_labels(session: Session, run_id: str) -> dict[int, str]:
    """2026-08-12 用于加载 chapter_id → 展示标签映射，避免卷标题占用编号导致展示错位

    卷标题（如"少年篇"）会占用 chapter_id 导致真实章节编号整体偏移，
    进度消息必须以 chapters.display_index_label（如"第1章"）展示而非原始 chapter_id。
    """
    labels: dict[int, str] = {}
    for chapter in ChapterRepository(session).fetch_chapters(run_id):
        if chapter.display_index_label:
            labels[chapter.chapter_id] = chapter.display_index_label
        else:
            labels[chapter.chapter_id] = f"第{chapter.sequence}章"
    return labels


def _load_existing_completion(
    *,
    session_factory: Callable[[], Session],
    run_id: str,
    chapter_id: int,
):
    """2026-08-05 用于在启动章节 Agent 前回读已提交的 CompletionResult"""
    from src.workflows.annotate_helpers.storage import load_completion_result

    read_session = session_factory()
    try:
        return load_completion_result(
            read_session,
            run_id=run_id,
            chapter_id=chapter_id,
        )
    finally:
        read_session.rollback()
        read_session.close()


def _build_fact_graph(
    *,
    session_factory: Callable[[], Session],
    run_id: str,
) -> FactGraph:
    """2026-08-09 用于在首个章节 Agent 启动时从库加载常驻事实图"""
    from src.agents.annotation.fact_graph import FactGraph, _stable_relation_key
    from src.storage.repositories.graph import GraphRepository

    read_session = session_factory()
    try:
        graph_repo = GraphRepository(read_session)
        latest = graph_repo.resolve_chapter_boundary(run_id)
        history_entity_types: dict[str, EntityType] = {}
        history_entity_names: dict[str, str] = {}
        history_entity_tags: dict[str, list[str]] = {}
        history_entity_attributes: dict[str, dict[str, Any]] = {}
        history_entity_state: dict[str, dict[str, Any]] = {}
        history_relations: set[tuple[str, str, str]] = set()
        history_relation_attributes: dict[tuple[str, str, str], dict[str, Any]] = {}
        if latest is not None:
            for entity_row in graph_repo.fetch_entity_snapshots(latest):
                key = entity_row.name.strip().casefold()
                history_entity_types[key] = type_cast(EntityType, entity_row.entity_type)
                history_entity_names[key] = entity_row.name
                history_entity_tags[key] = list(entity_row.tags or [])
                history_entity_attributes[key] = dict(entity_row.attributes or {})
                history_entity_state[key] = dict(entity_row.state or {})
            for relation_row in graph_repo.fetch_relation_snapshots(latest, active_only=True):
                relation_key = _stable_relation_key(
                    relation_row.from_name,
                    relation_row.to_name,
                    relation_row.relation_type,
                )
                history_relations.add(relation_key)
                history_relation_attributes[relation_key] = dict(relation_row.attributes or {})
        return FactGraph(
            history_entity_types=history_entity_types,
            history_entity_names=history_entity_names,
            history_entity_tags=history_entity_tags,
            history_entity_attributes=history_entity_attributes,
            history_entity_state=history_entity_state,
            history_relations=history_relations,
            history_relation_attributes=history_relation_attributes,
        )
    finally:
        read_session.rollback()
        read_session.close()


async def run_annotate(
    run_id: str,
    session: Session,
    analysis_logger: AnalysisLogger | None = None,
    novel_id: str = "default",
    novel_title: str | None = None,
    use_context_enhancement: bool = True,
    is_cancelled: Callable[[], bool] | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> tuple[int, int, int]:
    """2026-08-05 用于严格串行执行每章一次 Agent 并在成功后完成唯一事务"""
    del analysis_logger, use_context_enhancement

    from src.agents.annotation import run_annotation_agent
    from src.agents.llm import build_chat_model
    from src.agents.usage import build_token_usage_callback
    from src.config import settings
    from src.models.local.embedding import EmbeddingClient
    from src.workflows.annotate_helpers.storage import complete_annotation_run

    started_at = time.perf_counter()
    chapter_rows = ChapterRepository(session).fetch_chapters_with_text(run_id)
    if not chapter_rows:
        logger.warning("no chapters found in db for run_id={}", run_id)
        return 0, 0, 0

    chapter_groups = _group_chunks_by_chapter(chapter_rows)
    total_chapters = len(chapter_groups)
    chapter_labels = _load_chapter_labels(session, run_id)
    sql_session_factory = get_session_factory()
    llm = build_chat_model("annotation")
    embedding_client = EmbeddingClient(
        novel_id=novel_id,
        token_usage_callback=build_token_usage_callback(session=session, run_id=run_id),
    )
    graph_state = _build_fact_graph(
        session_factory=sql_session_factory,
        run_id=run_id,
    )
    success_count = 0
    failed_count = 0
    first_failure: Exception | None = None

    if emitter:
        await emitter(
            StreamEvent(
                action="progress",
                stage="annotate",
                sub_stage="chapter_agent",
                current=0,
                total=total_chapters,
                percent=10,
                sub_percent=0,
                message=f"共 {total_chapters} 个章节待核对",
            )
        )

    for chapter_index, (chapter_id, current_chunks) in enumerate(chapter_groups):
        if is_cancelled and is_cancelled():
            logger.warning(
                "annotation cancelled before chapter run_id={} chapter_id={}",
                run_id,
                chapter_id,
            )
            break

        # 2026-08-14 M7（§20）：子块为负 ID（纯运行时派发），SSE/stream 事件
        # 一律使用章真实 chunk_id，因此在循环外先取 chapter_chunk_id
        chapter_chunk_id = current_chunks[0][0]
        existing = _load_existing_completion(
            session_factory=sql_session_factory,
            run_id=run_id,
            chapter_id=chapter_id,
        )
        if existing is not None:
            success_count += 1
            logger.info(
                "annotation chapter already committed run_id={} chapter_id={} annotation_id={}",
                run_id,
                chapter_id,
                existing.annotation_id,
            )
        else:
            if emitter:
                await emitter(
                    StreamEvent(
                        action="progress",
                        stage="annotate",
                        sub_stage="chapter_agent",
                        chapter_id=chapter_chunk_id,
                        current=chapter_index,
                        total=total_chapters,
                        percent=10 + (chapter_index / total_chapters) * 70,
                        sub_percent=(chapter_index / total_chapters) * 100,
                        message=f"章节 {chapter_labels.get(chapter_id, chapter_id)} 标注 Agent 运行中",
                    )
                )

            agent_stream = (
                AgentStream(
                    emitter,
                    chunk_id=chapter_chunk_id,
                    sub_stage="chapter_agent",
                )
                if emitter is not None
                else None
            )
            if agent_stream is not None:
                await agent_stream.thinking(f"章节 {chapter_labels.get(chapter_id, chapter_id)} 标注 Agent 开始处理")

            try:
                # 2026-08-14 二期段落化：查询服务边界从 chunk 改为段落事实源边界。
                # 章节边界取本 chapter 全部真实 chunk 的段落行 min/max
                # paragraph_id（章节边界，不是子块边界）。
                chapter_chunk_ids = {chunk_id for chunk_id, _ in current_chunks}
                chapter_paragraph_rows = [
                    row
                    for row in ParagraphRepository(session).fetch_paragraph_rows(run_id)
                    if int(row.chapter_id) in chapter_chunk_ids
                ]
                if not chapter_paragraph_rows:
                    raise ValueError(f"章节无段落事实源: run_id={run_id} chapter_id={chapter_id}")
                chapter_first_paragraph_id = min(int(row.paragraph_id) for row in chapter_paragraph_rows)
                chapter_last_paragraph_id = max(int(row.paragraph_id) for row in chapter_paragraph_rows)
                # 2026-08-14 M7（§20）：章文本超过上限时在段落边界切成负 ID 子块，
                # 各子块严格串行运行章节 Agent，全部成功后合并为单章完成事务。
                chapter_text = "".join(chunk_text for _chunk_id, chunk_text in current_chunks)
                sub_chunks = _split_chapter_sub_chunks(
                    chapter_text,
                    chapter_paragraph_rows,
                    chapter_chunk_id=chapter_chunk_id,
                    max_chars=settings.models.annotation.sub_chunk_max_chars,
                )
                sub_results: list[AgentRunResult] = []
                sub_chunk_offsets: list[int] = []
                for sub_chunk_index, (sub_chunk_id, sub_chunk_text, sub_chunk_offset) in enumerate(sub_chunks):
                    sub_chunk_offsets.append(sub_chunk_offset)
                    sub_paragraph_info = _build_sub_chunk_paragraph_info(
                        chapter_paragraph_rows,
                        sub_chunk_offset=sub_chunk_offset,
                        sub_chunk_text=sub_chunk_text,
                    )
                    sub_results.append(
                        await run_annotation_agent(
                            run_id=run_id,
                            chapter_id=chapter_id,
                            current_chunks=[(sub_chunk_id, sub_chunk_text)],
                            sub_chunk_index=sub_chunk_index,
                            novel_title=novel_title,
                            novel_id=novel_id,
                            llm=llm,
                            session_factory=sql_session_factory,
                            query_service_factory=partial(
                                DatabaseAnnotationQueryService,
                                run_id=run_id,
                                current_chapter_id=chapter_id,
                                current_first_paragraph_id=chapter_first_paragraph_id,
                                current_last_paragraph_id=chapter_last_paragraph_id,
                                embedding_client=embedding_client,
                            ),
                            stream=agent_stream,
                            graph_state=graph_state,
                            chapter_label=chapter_labels.get(chapter_id),
                            paragraph_info=sub_paragraph_info,
                        )
                    )
                complete_annotation_run(
                    result=_merge_sub_chunk_results(
                        sub_results,
                        chapter_chunk_id=chapter_chunk_id,
                        sub_chunk_offsets=sub_chunk_offsets,
                    ),
                    session_factory=sql_session_factory,
                )
                success_count += 1
            except Exception as exc:
                if first_failure is None:
                    first_failure = exc
                failed_count += 1
                logger.error(
                    "annotation chapter failed run_id={} chapter_id={} label={} error={!r}",
                    run_id,
                    chapter_id,
                    chapter_labels.get(chapter_id, chapter_id),
                    exc,
                )
                # 失败章未提交 annotation，不产生图版本；审计 invocation 收口由
                # runner 内 finish_invocation(status="error") 完成。中断后续章节，
                # 避免先提交的后续章节与 resume 补跑的失败章产生修订号冲突。
                break

        if emitter:
            await emitter(
                StreamEvent(
                    action="progress",
                    stage="annotate",
                    sub_stage="chapter_agent",
                    chapter_id=chapter_chunk_id,
                    current=success_count,
                    total=total_chapters,
                    percent=10 + (success_count / total_chapters) * 70,
                    sub_percent=(success_count / total_chapters) * 100,
                    message=f"章节 {chapter_labels.get(chapter_id, chapter_id)} 已完成",
                )
            )

    elapsed = time.perf_counter() - started_at
    logger.info(
        "annotate completed run_id={} chapters={}/{} failed={} elapsed={:.2f}s",
        run_id,
        success_count,
        total_chapters,
        failed_count,
        elapsed,
    )
    if first_failure is not None:
        # 2026-08-19 章节失败即中断，失败章未提交；恢复任务时从失败章节继续
        raise first_failure
    return success_count, 0, total_chapters
