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
    BoundEntity,
    BoundEntityDirectory,
    EntityType,
    PendingCase,
    ResolvedCase,
)
from src.agents.stream import AgentStream
from src.api.models.events import StreamEvent
from src.config.analysis_logger import AnalysisLogger
from src.storage.db import get_session_factory
from src.storage.repositories import (
    ChapterRepository,
    ChunkRepository,
    DatabaseAnnotationQueryService,
    ParagraphRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Row

    from src.agents.annotation.fact_graph import FactGraph


def _group_chunks_by_chapter(
    chunk_rows: list[tuple[int, int, str]],
) -> list[tuple[int, list[tuple[int, str]]]]:
    """2026-08-05 用于按真实非空 chapter_id 聚合完整 current 并保持原文顺序"""
    chapters: dict[int, list[tuple[int, str]]] = {}
    for chunk_id, chapter_id, chunk_text in chunk_rows:
        if chapter_id is None or chapter_id <= 0:
            raise ValueError(
                f"chunks.chapter_id 必须真实且非空，run 需要重新预处理: chunk_id={chunk_id}"
            )
        chapters.setdefault(chapter_id, []).append((chunk_id, chunk_text))
    return list(chapters.items())


def _split_chapter_sub_chunks(
    chapter_text: str,
    chapter_paragraphs: Sequence[Row],
    *,
    chapter_chunk_id: int,
    max_chars: int,
) -> list[tuple[int, str]]:
    """2026-08-14 M7（§20）用于在段落边界把超长章切成运行时子块

    子块是纯运行时派发单位：不落库、不进指标、不生成第二套段落边界——
    切分位置只取 paragraphs 行的 local_start_char（相对章文本）。子块 ID
    按顺序取 -1, -2, ...；章文本不超过 max_chars 或没有可用段落边界时
    原样返回 [(chapter_chunk_id, chapter_text)]。单个超长自然段无法在
    段落边界内再切，允许子块略超 max_chars（累计字符 ≥ max_chars 成块）。
    """
    if len(chapter_text) <= max_chars:
        return [(chapter_chunk_id, chapter_text)]
    usable_boundaries = sorted(
        {
            int(row.local_start_char)
            for row in chapter_paragraphs
            if 0 < int(row.local_start_char) < len(chapter_text)
        }
    )
    if not usable_boundaries:
        return [(chapter_chunk_id, chapter_text)]
    sub_chunks: list[tuple[int, str]] = []
    sub_index = 1
    block_start = 0
    for boundary in usable_boundaries + [len(chapter_text)]:
        if boundary <= block_start:
            continue
        if boundary - block_start >= max_chars:
            sub_chunks.append((-sub_index, chapter_text[block_start:boundary]))
            sub_index += 1
            block_start = boundary
    if block_start < len(chapter_text) or not sub_chunks:
        sub_chunks.append((-sub_index, chapter_text[block_start:]))
    return sub_chunks


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
) -> BoundChapterAnnotation:
    """2026-08-14 M7（§20）用于把同一章各子块标注合并为单 chunk 章节标注

    chapter_summary 按子块顺序换行拼接；chunks 收缩为单条
    BoundChunkAnnotation（chunk_id=章真实 chunk_id），metrics 取第一个子块，
    实体目录同名去重（保留先出现），其余领域按子块顺序拼接。
    """
    if not annotations:
        raise ValueError("子块标注列表不能为空")
    for annotation in annotations:
        if len(annotation.chunks) != 1:
            raise ValueError("子块标注必须恰好包含一个 chunk")
    first_chunk = annotations[0].chunks[0]
    return BoundChapterAnnotation(
        chapter_summary="\n".join(annotation.chapter_summary for annotation in annotations),
        chunks=[
            BoundChunkAnnotation(
                chunk_id=chapter_chunk_id,
                metrics=first_chunk.metrics,
                entities=BoundEntityDirectory(
                    entities=_merge_sub_chunk_entities(
                        [annotation.chunks[0].entities for annotation in annotations]
                    )
                ),
                character_observations=[
                    item
                    for annotation in annotations
                    for item in annotation.chunks[0].character_observations
                ],
                dialogues=[
                    item
                    for annotation in annotations
                    for item in annotation.chunks[0].dialogues
                ],
                events=[
                    item for annotation in annotations for item in annotation.chunks[0].events
                ],
                relations=[
                    item
                    for annotation in annotations
                    for item in annotation.chunks[0].relations
                ],
                foreshadowings=[
                    item
                    for annotation in annotations
                    for item in annotation.chunks[0].foreshadowings
                ],
            )
        ],
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
) -> AgentRunResult:
    """2026-08-14 M7（§20）用于把同一章各子块 Agent 结果合并为单次完成事务输入

    子块运行时负 chunk_id 一律映射回章真实 chunk_id（案例不落负 ID）；
    审计字段按并集/拼接合并，sub_chunk_index 归零（结果已合并为单章）。
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
            write_revisions=[
                revision for result in results for revision in result.audit.write_revisions
            ],
            rotation_case_ids=list(
                dict.fromkeys(
                    case_id
                    for result in results
                    for case_id in result.audit.rotation_case_ids
                )
            ),
            authorized_chapter_ids=sorted(
                {
                    case_id
                    for result in results
                    for case_id in result.audit.authorized_chapter_ids
                }
            ),
            authorized_text_paragraph_ids=sorted(
                {
                    paragraph_id
                    for result in results
                    for paragraph_id in result.audit.authorized_text_paragraph_ids
                }
            ),
            closed_case_ids=[
                case_id for result in results for case_id in result.audit.closed_case_ids
            ],
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
        latest = graph_repo.resolve_graph_version(run_id)
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
    chunk_rows = ChunkRepository(session).fetch_chunks_with_chapter(run_id)
    if not chunk_rows:
        logger.warning("no chunks found in db for run_id={}", run_id)
        return 0, 0, 0

    chapter_groups = _group_chunks_by_chapter(chunk_rows)
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
                        chunk_id=chapter_chunk_id,
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
                await agent_stream.thinking(
                    f"章节 {chapter_labels.get(chapter_id, chapter_id)} 标注 Agent 开始处理"
                )

            try:
                # 2026-08-14 二期段落化：查询服务边界从 chunk 改为段落事实源边界。
                # 章节边界取本 chapter 全部真实 chunk 的段落行 min/max
                # paragraph_id（章节边界，不是子块边界）。
                chapter_chunk_ids = {chunk_id for chunk_id, _ in current_chunks}
                chapter_paragraph_rows = [
                    row
                    for row in ParagraphRepository(session).fetch_paragraph_rows(run_id)
                    if int(row.chunk_id) in chapter_chunk_ids
                ]
                if not chapter_paragraph_rows:
                    raise ValueError(
                        f"章节无段落事实源: run_id={run_id} chapter_id={chapter_id}"
                    )
                chapter_first_paragraph_id = min(
                    int(row.paragraph_id) for row in chapter_paragraph_rows
                )
                chapter_last_paragraph_id = max(
                    int(row.paragraph_id) for row in chapter_paragraph_rows
                )
                # 2026-08-14 M7（§20）：章文本超过上限时在段落边界切成负 ID 子块，
                # 各子块严格串行运行章节 Agent，全部成功后合并为单章完成事务。
                chapter_text = "".join(
                    chunk_text for _chunk_id, chunk_text in current_chunks
                )
                sub_chunks = _split_chapter_sub_chunks(
                    chapter_text,
                    chapter_paragraph_rows,
                    chapter_chunk_id=chapter_chunk_id,
                    max_chars=settings.models.annotation.sub_chunk_max_chars,
                )
                sub_results: list[AgentRunResult] = []
                for sub_chunk_index, (sub_chunk_id, sub_chunk_text) in enumerate(sub_chunks):
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
                        )
                    )
                complete_annotation_run(
                    result=_merge_sub_chunk_results(
                        sub_results,
                        chapter_chunk_id=chapter_chunk_id,
                    ),
                    session_factory=sql_session_factory,
                )
                success_count += 1
            except Exception as exc:  # noqa: BLE001 单章失败即中断，run 收口 failed 后可 resume 补跑
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
                    chunk_id=chapter_chunk_id,
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
        # 2026-08-13 章节失败即中断（不再继续后续章节）：失败章未提交图版本，
        # 若后续章节先提交会造成修订号空洞，resume 补跑失败章时与后续章节
        # 修订号冲突（uq_*_run_revision）且重试必败。中断后 run 收口 failed，
        # resume 跳过已成功章节、仅重跑失败章及后续未完成章节，顺序补写无空洞。
        raise first_failure
    return success_count, 0, total_chapters
