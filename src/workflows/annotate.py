"""
章节级 LangGraph 标注工作流
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from loguru import logger
from sqlalchemy.orm import Session

from src.api.models.events import StreamEvent
from src.config.analysis_logger import AnalysisLogger
from src.storage.db import get_session_factory
from src.storage.repositories import ChunkRepository, DatabaseAnnotationQueryService


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
    """2026-08-05 用于严格串行执行每章一次 Agent 并在成功后完成唯一事务"""
    del resume, analysis_logger, use_context_enhancement, use_rag

    from src.agents.annotation import run_annotation_agent
    from src.agents.llm import build_chat_model
    from src.workflows.annotate_helpers.storage import complete_annotation_run

    started_at = time.perf_counter()
    chunk_rows = ChunkRepository(session).fetch_chunks_with_chapter(run_id)
    if not chunk_rows:
        logger.warning("no chunks found in db for run_id={}", run_id)
        return 0, 0, 0

    chapter_groups = _group_chunks_by_chapter(chunk_rows)
    chapter_ids = [chapter_id for chapter_id, _chunks in chapter_groups]
    total_chapters = len(chapter_groups)
    sql_session_factory = get_session_factory()
    llm = build_chat_model("annotation")
    success_count = 0

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
            after_chapter_ids = chapter_ids[chapter_index + 1 :]
            if emitter:
                await emitter(
                    StreamEvent(
                        action="progress",
                        stage="annotate",
                        sub_stage="chapter_agent",
                        chunk_id=current_chunks[0][0],
                        current=chapter_index,
                        total=total_chapters,
                        percent=10 + (chapter_index / total_chapters) * 70,
                        sub_percent=(chapter_index / total_chapters) * 100,
                        message=f"章节 {chapter_id} 标注 Agent 运行中",
                    )
                )

            agent_result = await run_annotation_agent(
                run_id=run_id,
                chapter_id=chapter_id,
                current_chunks=current_chunks,
                after_chapter_ids=after_chapter_ids,
                novel_title=novel_title,
                llm=llm,
                session_factory=sql_session_factory,
                query_service_factory=lambda read_session: DatabaseAnnotationQueryService(
                    read_session,
                    run_id,
                ),
            )
            complete_annotation_run(
                result=agent_result,
                novel_id=novel_id,
                session_factory=sql_session_factory,
            )
            success_count += 1

        if emitter:
            await emitter(
                StreamEvent(
                    action="progress",
                    stage="annotate",
                    sub_stage="chapter_agent",
                    chunk_id=current_chunks[0][0],
                    current=success_count,
                    total=total_chapters,
                    percent=10 + (success_count / total_chapters) * 70,
                    sub_percent=(success_count / total_chapters) * 100,
                    message=f"章节 {chapter_id} 已完成",
                )
            )

    elapsed = time.perf_counter() - started_at
    logger.info(
        "annotate completed run_id={} chapters={}/{} elapsed={:.2f}s",
        run_id,
        success_count,
        total_chapters,
        elapsed,
    )
    return success_count, 0, total_chapters
