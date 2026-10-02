"""章节任务独立执行；并发由模型池容量位控制，任务满位时留在队列"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from contextlib import suppress
from uuid import uuid4

from loguru import logger

from src.agents.annotation.errors import AnnotationRetryableError
from src.agents.model_capacity import ModelCapacity
from src.agents.stream import _is_transient_model_error
from src.storage.repositories.pipeline_work import (
    ImmutableWorkConflict,
    PipelineWorkRepository,
    StaleWorkLeaseError,
    WorkKind,
    WorkReceipt,
)


class PipelineWorkFailed(RuntimeError):
    """死信保留正式结果，但阻止本轮释放与后续聚合"""


class DurableWorkerPool:
    """章节任务由模型池分发：2026-10-02 并发语义归位——claim 前按各模型空位做容量
    感知选举（在途任务数 < max_in_flight），满位不领取、任务留在队列；容量位跟
    agent 生命周期（领取/归还在 executor 与子代理启动路径），permit 层跨进程兜底。
    capacity=None 时不做容量过滤（保持无容量约束行为）。
    """

    def __init__(
        self,
        queue: PipelineWorkRepository,
        *,
        lease_seconds: int = 120,
        max_attempts: int = 3,
        poll_seconds: float = 0.1,
        capacity: ModelCapacity | None = None,
    ) -> None:
        if min(lease_seconds, max_attempts) < 1:
            raise ValueError("租约与尝试预算必须大于零")
        self.queue = queue
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.poll_seconds = poll_seconds
        self.capacity = capacity
        self.owner = f"worker:{uuid4().hex}"

    async def run(
        self,
        *,
        run_id: str,
        work_kind: WorkKind | None,
        execute: Callable[[WorkReceipt], Awaitable[None]],
        is_cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, int]:
        tasks: set[asyncio.Task[None]] = set()
        try:
            while True:
                finished = {task for task in tasks if task.done()}
                for task in finished:
                    await task
                tasks.difference_update(finished)
                if is_cancelled is not None and is_cancelled():
                    await asyncio.to_thread(self.queue.cancel_run, run_id)
                    raise asyncio.CancelledError("分析已取消")
                receipt = await asyncio.to_thread(
                    self.queue.claim,
                    owner=self.owner,
                    lease_seconds=self.lease_seconds,
                    run_id=run_id,
                    work_kind=work_kind,
                    max_attempts=self.max_attempts,
                    in_flight=self.capacity.snapshot() if self.capacity is not None else None,
                )
                if receipt is not None:
                    tasks.add(asyncio.create_task(self._execute_owned(receipt, execute, is_cancelled)))
                    continue
                counts = await asyncio.to_thread(self.queue.state_counts, run_id, work_kind=work_kind)
                if counts.get("cancelled", 0):
                    raise asyncio.CancelledError("工作已取消")
                if not tasks and not (counts.get("queued", 0) or counts.get("running", 0)):
                    break
                await asyncio.sleep(self.poll_seconds)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        counts = await asyncio.to_thread(self.queue.state_counts, run_id, work_kind=work_kind)
        if counts.get("dead_letter", 0):
            raise PipelineWorkFailed(f"{work_kind} 有 {counts['dead_letter']} 个死信工作，需要修复后恢复")
        return counts

    async def _execute_owned(
        self,
        receipt: WorkReceipt,
        execute: Callable[[WorkReceipt], Awaitable[None]],
        is_cancelled: Callable[[], bool] | None,
    ) -> None:
        async def invoke() -> None:
            await execute(receipt)

        execution = asyncio.create_task(invoke())

        async def renew_lease() -> None:
            while True:
                await asyncio.sleep(min(self.lease_seconds / 3, 5))
                if is_cancelled is not None and is_cancelled():
                    await asyncio.to_thread(self.queue.cancel_run, receipt.run_id)
                    raise asyncio.CancelledError("分析已取消")
                await asyncio.to_thread(self.queue.heartbeat, receipt, lease_seconds=self.lease_seconds)

        heartbeat = asyncio.create_task(renew_lease())
        try:
            done, _ = await asyncio.wait({execution, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
            if execution in done:
                await execution
            else:
                await heartbeat
        except StaleWorkLeaseError:
            execution.cancel()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Agent 工作失败 work_id={} attempt_epoch={} error={!r}",
                         receipt.work_id, receipt.attempt_epoch, exc)
            transient = (
                receipt.work_kind == "formal_current" and not isinstance(exc, ImmutableWorkConflict)
            ) or isinstance(exc, AnnotationRetryableError) or _is_transient_model_error(exc)
            with suppress(StaleWorkLeaseError):
                await asyncio.to_thread(
                    self.queue.fail,
                    receipt,
                    reason=str(exc),
                    transient=transient,
                    max_attempts=self.max_attempts,
                    retry_delay_seconds=min(30, 2 ** receipt.attempt_epoch) + random.randint(0, 2),
                )
        finally:
            execution.cancel()
            heartbeat.cancel()
            await asyncio.gather(execution, heartbeat, return_exceptions=True)
