"""按章节序的进程内工作队列：只维护队列、启动任务、收下 agent 回传的状态

2026-10-05 删除数据库租约队列（work_items/claim/lease/epoch）后把职责边界收到
三处：队列只做三件事——按章节序维护待办、经 agent 暴露的启动接口拉起任务、
agent 结束后按回传状态处理重试与终局。模型选择与容量位归模型池
（MODEL_CAPACITY.dispatch），失败分类归 agent 执行器（execute 返回 AgentStatus），
队列不 import 任何模型或异常语义。不向数据库写任何队列状态：单进程执行器下
重启恢复等于重查无标注章节，天然幂等，不需要租约接管与取消纪元栅栏。
取消 = 停止派发 + 等待在飞章节收尾，已开始的提交照常落库。
"""

from __future__ import annotations

import asyncio
import random
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Literal
from uuid import uuid4

from src.agents.model_capacity import MODEL_CAPACITY
from src.storage.repositories.pipeline_work import WorkReceipt

AgentStatus = Literal["submitted", "retry", "failed"]


class PipelineWorkFailed(RuntimeError):
    """存在超出尝试预算的失败章节，阻止本轮释放与后续聚合"""


def retry_delay(attempt_epoch: int) -> float:
    """瞬态失败的重试退避：指数增长封顶 30 秒，加随机抖动防同步重试"""
    return min(30, 2 ** max(0, attempt_epoch - 1)) + random.uniform(0, 2)


class ChapterWorkerPool:
    """按序维护队列并启动任务；重试预算与退避是队列自己的调度职责"""

    def __init__(self, *, max_attempts: int = 3, poll_seconds: float = 0.1) -> None:
        if max_attempts < 1:
            raise ValueError("尝试预算必须大于零")
        self.max_attempts = max_attempts
        self.poll_seconds = poll_seconds
        self.owner = f"worker:{uuid4().hex}"

    async def run(
        self,
        work: list[WorkReceipt],
        *,
        execute: Callable[[WorkReceipt], Awaitable[AgentStatus]],
        is_cancelled: Callable[[], bool] | None = None,
    ) -> int:
        """按传入顺序启动（work 已按章节序构造），返回成功提交数；终局失败抛 PipelineWorkFailed"""
        pending: deque[WorkReceipt] = deque(work)
        in_flight: set[asyncio.Task[tuple[str, WorkReceipt | None]]] = set()
        succeeded = 0
        failures: list[str] = []

        def start_head() -> bool:
            """启动队头：向模型池要一个容量位（选举+预留），全部满位返回 False 等完成"""
            head = pending[0]
            model_id = MODEL_CAPACITY.dispatch(
                head.work_id, head.attempt_epoch, head.payload.get("model_id"),
            )
            if model_id is None:
                return False
            pending.popleft()
            receipt = replace(head, attempt_epoch=head.attempt_epoch + 1,
                              payload={**head.payload, "model_id": model_id})
            in_flight.add(asyncio.create_task(self._attempt(receipt, execute)))
            return True

        while pending or in_flight:
            if is_cancelled is not None and is_cancelled():
                raise asyncio.CancelledError("分析已取消")
            while pending:
                if not start_head():
                    break
            if not in_flight:
                # 选举落空且无在飞：容量账本暂无空位（并发收尾会修正），短暂退避重试
                await asyncio.sleep(self.poll_seconds)
                continue
            done, _ = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
            in_flight.difference_update(done)
            for task in done:
                outcome, retry = await task
                if outcome == "submitted":
                    succeeded += 1
                elif outcome == "retry" and retry is not None:
                    pending.append(retry)
                elif outcome == "failed":
                    failures.append(retry.work_id if retry else "?")
        if failures:
            raise PipelineWorkFailed(f"{len(failures)} 个章节超出尝试预算仍失败，需修复后恢复: {failures}")
        return succeeded

    async def _attempt(
        self, receipt: WorkReceipt, execute: Callable[[WorkReceipt], Awaitable[AgentStatus]],
    ) -> tuple[str, WorkReceipt | None]:
        """启动一次尝试并收下 agent 回传的状态；瞬态失败按预算退避重试，其余终局上报"""
        outcome = await execute(receipt)
        if outcome == "submitted":
            return "submitted", None
        if outcome == "retry" and receipt.attempt_epoch < self.max_attempts:
            await asyncio.sleep(retry_delay(receipt.attempt_epoch))
            return "retry", receipt
        return "failed", receipt
