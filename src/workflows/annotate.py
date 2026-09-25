"""
章节级 LangGraph 标注工作流
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from functools import partial
from typing import TYPE_CHECKING, Any
from typing import cast as type_cast

from loguru import logger
from sqlalchemy.orm import Session

from src.agents.annotation.schema import (
    EntityType,
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
    from src.agents.annotation.fact_graph import FactGraph


def _validated_chapter_rows(
    chapter_rows: list[tuple[int, str]],
) -> list[tuple[int, str]]:
    """2026-08-05 用于校验章身份并保持原文顺序

    M9a-2：chapters 表合并进 chapters 后，存储层直接返回 (chapter_id, text)，
    运行时块身份 = chapter_id（1 基）。2026-09-19 双路径定案：一章就是一份正文，
    不再有章内 chunk 聚合；超过 sub_chunk_max_chars 的章走 subagent 路径
    （门槛只作派发，正文永远整章注入）。
    """
    chapters: list[tuple[int, str]] = []
    for chapter_id, chapter_text in chapter_rows:
        if chapter_id is None or chapter_id <= 0:
            raise ValueError(f"chapters.chapter_id 必须真实且非空，run 需要重新预处理: chapter_id={chapter_id}")
        chapters.append((chapter_id, chapter_text))
    return chapters


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
    """2026-08-09 创建；2026-08-23 用于启动时从库直接加载已提交事实图（不依赖 annotation record）"""
    from src.agents.annotation.fact_graph import FactGraph, _stable_relation_key
    from src.storage.repositories.graph import GraphRepository

    read_session = session_factory()
    try:
        graph_repo = GraphRepository(read_session)
        latest = graph_repo.resolve_persisted_boundary(run_id)
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
            run_scope=run_id,
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
    from src.workflows.annotate_helpers.block_codeact import (
        build_chapter_paragraph_info,
        run_chapter_subagents,
    )
    from src.workflows.annotate_helpers.storage import complete_annotation_run

    started_at = time.perf_counter()
    chapter_rows = ChapterRepository(session).fetch_chapters_with_text(run_id)
    if not chapter_rows:
        logger.warning("no chapters found in db for run_id={}", run_id)
        return 0, 0, 0

    chapter_rows = _validated_chapter_rows(chapter_rows)
    total_chapters = len(chapter_rows)
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

    for chapter_index, (chapter_id, chapter_text) in enumerate(chapter_rows):
        if is_cancelled and is_cancelled():
            logger.warning(
                "annotation cancelled before chapter run_id={} chapter_id={}",
                run_id,
                chapter_id,
            )
            break

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
                        chapter_id=chapter_id,
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
                    chapter_id=chapter_id,
                    sub_stage="chapter_agent",
                )
                if emitter is not None
                else None
            )
            if agent_stream is not None:
                await agent_stream.thinking(f"章节 {chapter_labels.get(chapter_id, chapter_id)} 标注 Agent 开始处理")

            try:
                # 2026-08-14 二期段落化：查询服务边界从 chunk 改为段落事实源边界。
                # 章节边界取本章全部段落行的 paragraph_id min/max。
                chapter_paragraph_rows = [
                    row
                    for row in ParagraphRepository(session).fetch_paragraph_rows(run_id)
                    if int(row.chapter_id) == chapter_id
                ]
                if not chapter_paragraph_rows:
                    raise ValueError(f"章节无段落事实源: run_id={run_id} chapter_id={chapter_id}")
                chapter_first_paragraph_id = min(int(row.paragraph_id) for row in chapter_paragraph_rows)
                chapter_last_paragraph_id = max(int(row.paragraph_id) for row in chapter_paragraph_rows)
                # 2026-09-19 双路径定案：门槛只作派发（章正文超过 sub_chunk_max_chars
                # =长章走三条职责 subagent 各持整章并发），两条路径的正文都整章注入，
                # 子块不再是运行单元、也不再真的切分（模拟切分的旧门控已删）。
                if len(chapter_text) > settings.models.annotation.sub_chunk_max_chars:
                    # 多块章=subagent 路径：三条职责 subagent 各持整章并发
                    # （structure/event/evidence，职责只写在文案里，见 subagent_ir §3）
                    chapter_result = await run_chapter_subagents(
                        run_id=run_id,
                        chapter_id=chapter_id,
                        chapter_text=chapter_text,
                        chapter_paragraph_rows=chapter_paragraph_rows,
                        llm=llm,
                        sql_session_factory=sql_session_factory,
                        query_service_factory=partial(
                            DatabaseAnnotationQueryService,
                            run_id=run_id,
                            current_chapter_id=chapter_id,
                            current_first_paragraph_id=chapter_first_paragraph_id,
                            current_last_paragraph_id=chapter_last_paragraph_id,
                            embedding_client=embedding_client,
                        ),
                        graph_state=graph_state,
                        stream=agent_stream,
                        novel_id=novel_id,
                    )
                else:
                    # 单块章=agent 路径：整章一个 agent（程序面，task_type="annotation"）
                    chapter_result = await run_annotation_agent(
                        run_id=run_id,
                        chapter_id=chapter_id,
                        chapter_text=chapter_text,
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
                        paragraph_info=build_chapter_paragraph_info(
                            chapter_paragraph_rows,
                            chapter_text=chapter_text,
                        ),
                    )
                complete_annotation_run(
                    result=chapter_result,
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
                    chapter_id=chapter_id,
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
