"""角色 work 并行标注，按成功保存的必需角色聚合章进度"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from types import SimpleNamespace

from loguru import logger

from src.agents.annotation.agent import AnnotationAgent
from src.audit.module import AuditModule
from src.config import settings
from src.config.analysis_logger import AnalysisLogger
from src.event_bus import EventBus, Message
from src.event_bus.activity import ActivityRelay
from src.event_bus.notifications import StreamEvent
from src.storage import Storage, get_storage_factory
from src.work.annotation_work import WorkReceipt, annotation_work_id, required_roles
from src.work.chapter_pool import ChapterWorkerPool
from src.work.policy import LANES, completed_chapters
from src.work.queries import fetch_annotation_role_records


def _load_work(
    session_factory: Callable[[], Storage], run_id: str
) -> tuple[list[WorkReceipt], set[int], dict[int, set[str]]]:
    session = session_factory()
    all_chapters = session.reads.text.list_ordered_run_chapters(run_id)
    chapters = [chapter for chapter in all_chapters if str(chapter.text or "").strip()]
    annotatable = {int(chapter.chapter_id) for chapter in chapters}
    states = fetch_annotation_role_records(session, run_id)
    complete = completed_chapters(states) & annotatable
    saved: dict[int, set[str]] = {}
    for record in states:
        if record.state == "saved" and int(record.chapter_id) in annotatable:
            saved.setdefault(int(record.chapter_id), set()).add(str(record.role))
    orders = [{"chapter_id": chapter.chapter_id, "sequence": chapter.sequence} for chapter in all_chapters]
    work: list[WorkReceipt] = []
    for chapter in chapters:
        if chapter.chapter_id in complete:
            continue
        rows = session.reads.text.list_work_paragraphs(chapter, run_id)
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
        roles = required_roles(chapter.text, settings.models.annotation.sub_chunk_max_chars)
        if saved.get(chapter.chapter_id, set()) & set(LANES):
            roles = LANES
        for role in roles:
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
    return (work, complete, saved)


def _plan_work(work: list[WorkReceipt], saved: dict[int, set[str]]) -> tuple[list[WorkReceipt], list[int]]:
    """未完成章按已保存角色保留产物：只重派缺失角色；角色集合不兼容的章整章重建"""
    receipts_by_chapter: dict[int, list[WorkReceipt]] = {}
    for receipt in work:
        receipts_by_chapter.setdefault(int(receipt.payload["chapter_id"]), []).append(receipt)
    planned: list[WorkReceipt] = []
    rebuild: list[int] = []
    for chapter_id, receipts in sorted(receipts_by_chapter.items()):
        required = {str(receipt.payload["role"]) for receipt in receipts}
        kept = saved.get(chapter_id, set())
        if kept and kept <= required:
            planned.extend(receipt for receipt in receipts if str(receipt.payload["role"]) not in kept)
        else:
            rebuild.append(chapter_id)
            planned.extend(receipts)
    return (planned, rebuild)


async def run_annotate(
    run_id: str,
    session: Storage,
    analysis_logger: AnalysisLogger | None = None,
    novel_id: str = "default",
    novel_title: str | None = None,
    use_context_enhancement: bool = True,
    is_cancelled: Callable[[], bool] | None = None,
    bus: EventBus | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> tuple[int, int, int]:
    """完成章节保留；未完成章节保留已保存角色，只重派缺失角色，角色集合不兼容时整章重建"""
    del analysis_logger, use_context_enhancement, novel_title
    started_at = time.perf_counter()
    pass
    factory = get_storage_factory()
    load_started = time.perf_counter()
    work, retained, saved = await asyncio.to_thread(_load_work, factory, run_id)
    logger.info(
        "annotate timing: load_work={:.3f}s work={} retained={}",
        time.perf_counter() - load_started,
        len(work),
        len(retained),
    )
    expected_ids = retained | {int(item.payload["chapter_id"]) for item in work}
    total = len(expected_ids)
    if not total:
        return (0, 0, 0)
    work, rebuild = _plan_work(work, saved)
    bus = bus or EventBus()
    agent = AnnotationAgent(bus, run_id, factory, novel_id=novel_id)
    audit = AuditModule(bus, run_id, factory)
    activity = ActivityRelay(bus, run_id, emitter)
    pool = ChapterWorkerPool()
    try:
        recovery_session = factory()
        recover_started = time.perf_counter()
        await bus.request(
            Message(
                topic="agent.recover",
                source=f"queue:{run_id}",
                target=agent.address,
                run_id=run_id,
                payload={"session": recovery_session, "chapter_ids": rebuild},
            )
        )
        logger.info("annotate timing: recover={:.3f}s rebuild={}", time.perf_counter() - recover_started, len(rebuild))
        if rebuild:
            await bus.request(
                Message(
                    topic="agent.recover",
                    source=f"queue:{run_id}",
                    target=agent.address,
                    run_id=run_id,
                    payload={"mode": "chapter_reset", "chapter_ids": rebuild},
                )
            )

        async def progress(receipt: WorkReceipt) -> None:
            del receipt
            progress_session = factory()
            states = await asyncio.to_thread(fetch_annotation_role_records, progress_session, run_id)
            completed = completed_chapters(states) & expected_ids
            if emitter:
                await emitter(StreamEvent(action="progress", stage="annotate", sub_stage="confirmed_chapters",
                    current=len(completed), total=total, unit="章", message="必需角色正式保存确认"))

        pool_started = time.perf_counter()
        await pool.run(work, bus=bus, session_factory=factory, is_cancelled=is_cancelled, on_saved=progress)
        logger.info("annotate timing: pool={:.3f}s works={}", time.perf_counter() - pool_started, len(work))
        await bus.request(Message(topic="audit.barrier", source=agent.address, target=audit.address, run_id=run_id))
        final_session = factory()
        states = await asyncio.to_thread(fetch_annotation_role_records, final_session, run_id)
        actual = completed_chapters(states) & expected_ids
        if len(actual) != total:
            raise RuntimeError(f"必需角色未全部成功保存: completed={len(actual)} total={total}")
        logger.info(
            "annotation work completed run_id={} chapters={} elapsed={:.2f}s",
            run_id,
            total,
            time.perf_counter() - started_at,
        )
        return (len(actual), 0, total)
    finally:
        try:
            await audit.close()
        finally:
            activity.close()
            agent.close()
