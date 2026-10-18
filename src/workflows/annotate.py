"""角色 work 并行标注，按成功保存的必需角色聚合章进度"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from types import SimpleNamespace

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.annotation.agent import AnnotationAgent
from src.agents.annotation.chapter_consolidation import eligible_chapters
from src.audit.module import AuditModule
from src.config import settings
from src.config.analysis_logger import AnalysisLogger
from src.event_bus import EventBus, Message
from src.sse.consumer import SSEModule
from src.sse.events import StreamEvent
from src.storage.db import get_session_factory
from src.storage.models import Chapter, Paragraph
from src.work.annotation_work import WorkReceipt, annotation_work_id, required_roles
from src.work.chapter_pool import ChapterWorkerPool
from src.work.policy import completed_chapters
from src.work.queries import fetch_annotation_role_records
from src.workflows.progress import stage_progress_percent


def _load_work(session_factory: Callable[[], Session], run_id: str) -> tuple[list[WorkReceipt], set[int]]:
    with session_factory() as session:
        chapters = (
            session.execute(
                select(Chapter).where(Chapter.run_id == run_id).order_by(Chapter.sequence, Chapter.chapter_id)
            )
            .scalars()
            .all()
        )
        # 完成判定按产物行推导：chapter_annotations(run, 章, 角色) 产物集合覆盖必需角色
        complete = completed_chapters(fetch_annotation_role_records(session, run_id))
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
            # 段落终点是读取投影（local_start_char + 字符长度），与既有派发载荷字段名同口径
            paragraphs = [
                SimpleNamespace(
                    chapter_id=row.chapter_id,
                    paragraph_id=row.paragraph_id,
                    local_start_char=row.local_start_char,
                    local_end_char=row.local_start_char + len(row.text),
                    text=row.text,
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
    agent = AnnotationAgent(bus, run_id, factory, novel_id=novel_id)
    audit = AuditModule(bus, run_id, factory)
    sse = SSEModule(bus, run_id, emitter)
    pool = ChapterWorkerPool(max_attempts=settings.models.annotation.total_attempts)
    try:
        recovery_session = factory()
        try:
            # 未完成章节的全部角色先按章废弃：产物、域事实与真实尝试一并废弃。
            # 枚举取自派发集而非产物行，否则重派按 attempt=1 登记会撞
            # uq_executions_annotation_attempt
            discard = sorted({item.payload["chapter_id"] for item in work})
            await bus.request(
                Message(
                    topic="agent.recover",
                    source=f"queue:{run_id}",
                    target=agent.address,
                    run_id=run_id,
                    payload={"session": recovery_session, "chapter_ids": discard},
                )
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

        async def consolidate(chapter_id: int, *, recheck: bool = False) -> None:
            await bus.request(Message(topic="audit.barrier", source=agent.address, target=audit.address, run_id=run_id))
            await bus.request(
                Message(
                    topic="agent.consolidate_chapter",
                    source=f"queue:{run_id}",
                    target=agent.address,
                    run_id=run_id,
                    payload={"chapter_id": chapter_id, "recheck": recheck},
                )
            )

        # 恢复只补本版本已经保存但章末事务尚未完成的章，旧版本保留章不追溯入池
        with factory() as recovery_check:
            retry_chapters = eligible_chapters(recovery_check, run_id) & retained
        for chapter_id in sorted(retry_chapters):
            await consolidate(chapter_id)

        async def progress(receipt: WorkReceipt) -> None:
            with factory() as progress_session:
                states = await asyncio.to_thread(fetch_annotation_role_records, progress_session, run_id)
                completed = completed_chapters(states)
                current = len(completed)
                invocation_id = next(
                    # 收到回执的 work 必有正式产物行，执行号取该产物行的真实执行
                    state.invocation_id
                    for state in states
                    if state.chapter_id == receipt.payload["chapter_id"]
                    and state.role == receipt.payload["role"]
                )
            await bus.request(
                Message(
                    topic="agent.saved_progress",
                    source=f"queue:{run_id}",
                    target=agent.address,
                    run_id=run_id,
                    work_id=receipt.work_id,
                    invocation_id=invocation_id,
                    payload={
                        "current": current,
                        "total": total,
                        "percent": stage_progress_percent("annotate", current, total),
                        "sub_percent": current / total * 100,
                    },
                )
            )
            chapter_id = receipt.payload["chapter_id"]
            if chapter_id in completed and chapter_id not in retained:
                await consolidate(chapter_id)

        await pool.run(work, bus=bus, session_factory=factory, is_cancelled=is_cancelled, on_saved=progress)
        await bus.request(Message(topic="audit.barrier", source=agent.address, target=audit.address, run_id=run_id))
        with factory() as final_session:
            states = await asyncio.to_thread(fetch_annotation_role_records, final_session, run_id)
            actual = completed_chapters(states)
        if len(actual) != total:
            raise RuntimeError(f"必需角色未全部成功保存: completed={len(actual)} total={total}")
        # 池排空后按章序重算核对：多章并发时完成序可能反转，早跑的核对看不到更早章
        # 未保存的引用会误报孤立；与既有回执一致不动，不一致才替换（含恢复章与保留章）
        for chapter_id in sorted(actual):
            await consolidate(chapter_id, recheck=True)
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
