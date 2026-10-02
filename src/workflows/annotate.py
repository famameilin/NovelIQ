"""持久化章节队列与固定 cutoff 的并行标注主流程"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from loguru import logger
from sqlalchemy.orm import Session

from src.api.models.events import StreamEvent
from src.config.analysis_logger import AnalysisLogger
from src.storage.db import get_session_factory
from src.storage.models import AnalysisRun
from src.storage.repositories.pipeline_projection import CutoffNotReady, PipelineProjectionRepository
from src.storage.repositories.pipeline_source import prepare_formal_work
from src.storage.repositories.pipeline_work import PipelineWorkRepository, WorkReceipt
from src.workflows.durable_worker import DurableWorkerPool
from src.workflows.pipeline_agent import PipelineAgentExecutor
from src.workflows.pipeline_materialization import materialize_cutoff


async def project_and_release(repository: PipelineProjectionRepository, cutoff_hash: str) -> None:
    """投影无模型请求；只有全部 ACK 后才切换现有 API 的读模型"""
    await asyncio.to_thread(repository.resume_projection, cutoff_hash)

    deadline = time.monotonic() + 300
    while True:
        if await asyncio.to_thread(repository.project_next, cutoff_hash):
            continue
        state, counts = await asyncio.to_thread(repository.projection_progress, cutoff_hash)
        if state == "released":
            return
        if state == "failed" or time.monotonic() >= deadline:
            raise CutoffNotReady("投影分区失败或等待其他进程 ACK 超时")
        if not counts.get("queued", 0):
            break
        await asyncio.sleep(0.05)
    await asyncio.to_thread(repository.release, cutoff_hash, materialize=materialize_cutoff)


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
    """章节独立执行；数据库工作、正式提交和 cutoff 是恢复与可见性的真相源"""
    del analysis_logger, use_context_enhancement
    from src.config import settings

    started_at = time.perf_counter()
    session.commit()
    factory = get_session_factory()
    work = await asyncio.to_thread(prepare_formal_work, factory, run_id)
    total = len(work)
    if not total:
        return 0, 0, 0
    options = settings.models.annotation
    queue = PipelineWorkRepository(factory)
    await asyncio.to_thread(queue.resume_failed_work, run_id)
    projections = PipelineProjectionRepository(factory)
    pool = DurableWorkerPool(queue, max_attempts=options.total_attempts)
    executor = PipelineAgentExecutor(factory, owner=pool.owner, novel_id=novel_id, novel_title=novel_title,
                                     is_cancelled=is_cancelled, emitter=emitter)

    async def emit_progress(chapter_id: int | None = None, label: str = "") -> None:
        if emitter is None:
            return
        counts = await asyncio.to_thread(queue.state_counts, run_id, work_kind="formal_current")
        submitted = counts.get("submitted", 0)
        await emitter(StreamEvent(
            action="progress", stage="annotate", sub_stage="chapter_agent", chapter_id=chapter_id,
            current=submitted, total=total, percent=10 + submitted / total * 70,
            sub_percent=submitted / total * 100,
            message=f"章节 {label} 已提交" if label else f"共 {total} 个章节，按模型请求并发处理",
        ))

    async def execute_formal(receipt: WorkReceipt) -> None:
        await executor.execute(receipt)
        await emit_progress(int(receipt.payload["chapter_id"]), receipt.payload["chapter_label"])

    await emit_progress()
    counts = await pool.run(run_id=run_id, work_kind="formal_current", execute=execute_formal,
                            is_cancelled=is_cancelled)
    boundary = await asyncio.to_thread(projections.latest_released, run_id)
    if boundary is None:
        cutoff_hash = await asyncio.to_thread(projections.seal, run_id, round_kind="formal", round_number=0)
        await project_and_release(projections, cutoff_hash)
    boundary = await asyncio.to_thread(projections.latest_released, run_id)
    if boundary is None:
        raise RuntimeError("标注完成但没有可见 cutoff")
    with factory() as completion_session, completion_session.begin():
        run = completion_session.get(AnalysisRun, run_id, with_for_update=True)
        if run is None or run.cancel_requested:
            raise asyncio.CancelledError("完成标注前分析已取消")
        run.annotation_cutoff_hash = boundary["cutoff_hash"]
    logger.info("parallel annotate completed run_id={} chapters={} elapsed={:.2f}s",
                run_id, total, time.perf_counter() - started_at)
    return counts.get("submitted", 0), 0, total
