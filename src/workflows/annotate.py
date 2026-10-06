"""角色 work 并行标注，按成功保存的必需角色聚合章进度"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from types import SimpleNamespace

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.agents.annotation.agent import AnnotationAgent
from src.agents.annotation.work import WorkReceipt, annotation_work_id, completed_chapters, required_roles
from src.agents.audit.module import AuditModule
from src.case_pool import CasePool
from src.config import settings
from src.config.analysis_logger import AnalysisLogger
from src.event_bus import EventBus, Message
from src.event_trees.trees import EventTrees
from src.fact_graph.graph import FactGraph
from src.sse.consumer import SSEModule
from src.sse.events import StreamEvent
from src.storage.db import get_session_factory
from src.storage.models import AnalysisOutput, AnnotationWork, Chapter, Paragraph
from src.workflows.chapter_pool import ChapterWorkerPool


def _load_work(session_factory: Callable[[], Session], run_id: str) -> tuple[list[WorkReceipt], set[int]]:
    with session_factory() as session:
        chapters = (
            session.execute(
                select(Chapter).where(Chapter.run_id == run_id).order_by(Chapter.sequence, Chapter.chapter_id)
            )
            .scalars()
            .all()
        )
        records = session.execute(select(AnnotationWork).where(AnnotationWork.run_id == run_id)).scalars().all()
        outputs = {
            value.work_id: value
            for value in session.execute(
                select(AnalysisOutput).where(
                    AnalysisOutput.run_id == run_id, AnalysisOutput.kind == "chapter_annotation"
                )
            ).scalars()
        }
        valid = [
            record
            for record in records
            if record.work_id in outputs
            and outputs[record.work_id].invocation_id == record.invocation_id
            and outputs[record.work_id].role == record.role
            and outputs[record.work_id].actual_input
        ]
        complete = completed_chapters(valid)
        orders = [{"chapter_id": chapter.chapter_id, "sequence": chapter.sequence} for chapter in chapters]
        work: list[WorkReceipt] = []
        for chapter in chapters:
            if chapter.chapter_id in complete:
                continue
            if not chapter.text:
                raise ValueError(f"chapter_id={chapter.chapter_id} 缺少实际章输入")
            rows = (
                session.execute(
                    select(Paragraph)
                    .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter.chapter_id)
                    .order_by(Paragraph.paragraph_index)
                )
                .scalars()
                .all()
            )
            paragraphs = [
                SimpleNamespace(
                    **{
                        name: getattr(row, name)
                        for name in ("chapter_id", "paragraph_id", "local_start_char", "local_end_char", "text")
                    }
                )
                for row in rows
            ]
            if not paragraphs:
                raise ValueError(f"chapter_id={chapter.chapter_id} 缺少实际原文段落")
            for role in required_roles(chapter.text, settings.models.annotation.sub_chunk_max_chars):
                work.append(
                    WorkReceipt(
                        work_id=annotation_work_id(run_id, chapter.chapter_id, role),
                        run_id=run_id,
                        work_kind="annotation_agent",
                        payload={
                            "chapter_id": chapter.chapter_id,
                            "chapter_sequence": chapter.sequence,
                            "chapter_label": chapter.display_index_label or f"第{chapter.sequence}章",
                            "chapter_text": chapter.text,
                            "chapter_chars": len(chapter.text),
                            "role": role,
                            "paragraphs": paragraphs,
                            "chapter_orders": orders,
                        },
                    )
                )
        return work, complete


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
    """完成章节保留；未完成章节全部角色先丢弃，再按当前输入与阈值重建"""
    del analysis_logger, use_context_enhancement, novel_title
    started_at = time.perf_counter()
    session.commit()
    factory = get_session_factory()
    work, retained = await asyncio.to_thread(_load_work, factory, run_id)
    total = len(retained | {item.payload["chapter_id"] for item in work})
    if not total:
        return 0, 0, 0
    bus = EventBus()
    agent = AnnotationAgent(
        bus,
        run_id,
        factory,
        novel_id=novel_id,
        fact_graph=FactGraph(run_scope=run_id),
        event_trees=EventTrees(run_id),
        case_pool=CasePool(run_id),
    )
    audit = AuditModule(bus, run_id, factory)
    sse = SSEModule(bus, run_id, emitter)
    pool = ChapterWorkerPool(max_attempts=settings.models.annotation.total_attempts)
    try:
        recovery_session = factory()
        try:
            records = await asyncio.to_thread(
                lambda: (
                    recovery_session.execute(select(AnnotationWork).where(AnnotationWork.run_id == run_id))
                    .scalars()
                    .all()
                )
            )
            outputs = (
                recovery_session.execute(
                    select(AnalysisOutput).where(
                        AnalysisOutput.run_id == run_id, AnalysisOutput.kind == "chapter_annotation"
                    )
                )
                .scalars()
                .all()
            )
            discard = list({item.work_id for item in [*records, *outputs] if item.chapter_id not in retained})
            await bus.request(
                Message(
                    topic="agent.recover",
                    source=f"queue:{run_id}",
                    target=agent.address,
                    run_id=run_id,
                    payload={"session": recovery_session, "discard": discard},
                )
            )
            await asyncio.to_thread(
                recovery_session.execute, delete(AnnotationWork).where(AnnotationWork.work_id.in_(discard))
            )
            await asyncio.to_thread(recovery_session.commit)
            # 整章废弃已提交后再清除旧角色展示，阈值变化不会遗留旧 lane
            if work:
                await bus.request(
                    Message(
                        topic="agent.recover",
                        source=f"queue:{run_id}",
                        target=agent.address,
                        run_id=run_id,
                        payload={
                            "mode": "chapter_reset",
                            "chapter_ids": sorted({item.payload["chapter_id"] for item in work}),
                        },
                    )
                )
        except BaseException:
            recovery_session.rollback()
            raise
        finally:
            recovery_session.close()

        async def progress(receipt: WorkReceipt) -> None:
            with factory() as progress_session:
                records = await asyncio.to_thread(
                    lambda: (
                        progress_session.execute(select(AnnotationWork).where(AnnotationWork.run_id == run_id))
                        .scalars()
                        .all()
                    )
                )
                current = len(completed_chapters(records))
                invocation_id = next(item.invocation_id for item in records if item.work_id == receipt.work_id)
            await bus.request(
                Message(
                    topic="agent.saved_progress",
                    source=f"queue:{run_id}",
                    target=agent.address,
                    run_id=run_id,
                    work_id=receipt.work_id,
                    invocation_id=invocation_id,
                    payload={"current": current, "total": total},
                )
            )

        await pool.run(work, bus=bus, session_factory=factory, is_cancelled=is_cancelled, on_saved=progress)
        await bus.request(Message(topic="audit.barrier", source=agent.address, target=audit.address, run_id=run_id))
        with factory() as final_session:
            records = await asyncio.to_thread(
                lambda: (
                    final_session.execute(select(AnnotationWork).where(AnnotationWork.run_id == run_id)).scalars().all()
                )
            )
            actual = completed_chapters(records)
        if len(actual) != total:
            raise RuntimeError(f"必需角色未全部成功保存: completed={len(actual)} total={total}")
        logger.info(
            "annotation work completed run_id={} chapters={} elapsed={:.2f}s",
            run_id,
            total,
            time.perf_counter() - started_at,
        )
        return len(actual), 0, total
    finally:
        try:
            await audit.close()
        finally:
            sse.close()
            agent.close()
