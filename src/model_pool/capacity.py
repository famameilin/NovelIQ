"""模型池：容量位账本 + 加权选举循环

并发数 = 同时存活的 agent 数（2026-10-02 归位）：agent 启动前领取所在模型的容量位、
结束归还，容量位只在 agent 存活期间占用，任务排队与等待容量都不占位。容量位是唯一的
并发闸（2026-10-03 Provider permit 层已删：429 退避归 stream 重试层，用量归 usage 回调）。

账本以池子地址为归属（2026-10-06）：占用数就是账本里的预留条数，池子退出按归属一次性
归还，账本里不存在无主条目。规则：本轮无自有预留、全进程无占用（并发为空）、选举仍
不成功 ⇒ 报错停止，不静默空转。
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from dataclasses import replace
from uuid import uuid4

from loguru import logger

from src.event_bus import EventBus, Message
from src.work.annotation_work import WorkReceipt


class ModelCapacity:
    """容量位账本：归属 → 预留表，占用数即预留条数"""

    def __init__(self) -> None:
        self._reserved: dict[str, dict[str, str]] = {}

    def snapshot(self) -> dict[str, int]:
        """各模型当前占用，供选举的空位过滤与「并发为空」判定"""
        counts: dict[str, int] = {}
        for reservations in self._reserved.values():
            for model_id in reservations.values():
                counts[model_id] = counts.get(model_id, 0) + 1
        return counts

    def reserve(self, owner: str, reservation_id: str, model_id: str) -> None:
        """派发选举成功即预留容量位（占用 +1）"""
        self._reserved.setdefault(owner, {})[reservation_id] = model_id

    def release(self, owner: str, reservation_id: str | None = None) -> int:
        """归还该归属的一笔或全部预留（幂等），返回归还笔数"""
        reservations = self._reserved.get(owner)
        if not reservations:
            return 0
        if reservation_id is None:
            count = len(reservations)
            del self._reserved[owner]
            return count
        removed = reservations.pop(reservation_id, None)
        if not reservations:
            del self._reserved[owner]
        return 1 if removed is not None else 0

    def reset(self) -> None:
        """清空容量账本（测试隔离用）"""
        self._reserved.clear()


MODEL_CAPACITY = ModelCapacity()


class ModelElectionExhausted(RuntimeError):
    """没有预留或在飞占用且模型池无法继续选举"""


class ModelElectionPool:
    """本轮模型池只发布选举结果，预算、失败权重和退避仅保留在内存"""

    def __init__(self, bus: EventBus, run_id: str, *, max_attempts: int, poll_seconds: float = 0.1) -> None:
        self.bus = bus
        self.run_id = run_id
        # 池子地址同时是容量预留的归属：close() 按它归还
        self.address = f"model_pool:{run_id}"
        self.assignment_topic = f"assignment:{run_id}"
        self.max_attempts = max_attempts
        self.poll_seconds = poll_seconds
        self.pending: deque[WorkReceipt] = deque()
        self.attempts: dict[str, int] = {}
        self.failures: dict[str, dict[str, int]] = {}
        self.available_at: dict[str, float] = {}
        self.reservations: dict[str, tuple[str, str]] = {}
        self._wake = asyncio.Event()
        self.closed = False
        bus.handle("pool.enqueue", self.address, self.enqueue)
        bus.handle("pool.feedback", self.address, self.feedback)

    async def enqueue(self, message: Message) -> None:
        receipt = message.payload
        if any(item.work_id == receipt.work_id for item in self.pending):
            return
        if self.attempts.get(receipt.work_id, 0):
            self.pending.appendleft(receipt)
        else:
            self.pending.append(receipt)
        self._wake.set()

    async def feedback(self, message: Message) -> None:
        reservation_id = message.payload["reservation_id"]
        owned = self.reservations.get(message.work_id)
        if owned is None or owned[0] != reservation_id:
            return
        _, model_id = self.reservations.pop(message.work_id)
        MODEL_CAPACITY.release(self.address, reservation_id)
        if message.payload["outcome"] == "retry":
            failures = self.failures.setdefault(message.work_id, {})
            failures[model_id] = failures.get(model_id, 0) + 1
            self.available_at[message.work_id] = (
                time.monotonic() + min(30, 2 ** (self.attempts[message.work_id] - 1)) + random.uniform(0, 1)
            )
        self._wake.set()

    async def run(self) -> None:
        from src.config import settings
        from src.config.model_assignment import select_annotation_model
        from src.utils.identity import stable_digest

        selection_error: Exception | None = None
        while not self.closed:
            if self.pending:
                receipt = self.pending[0]
                attempts = self.attempts.get(receipt.work_id, 0)
                model_id = None
                if (
                    receipt.work_id not in self.reservations
                    and attempts < self.max_attempts
                    and time.monotonic() >= self.available_at.get(receipt.work_id, 0)
                    and selection_error is None
                ):
                    try:
                        # 空位过滤读配置的 max_in_flight：容量热更新无需另立登记
                        model_id = select_annotation_model(
                            stable_digest(receipt.work_id, attempts),
                            settings.models.model_pool,
                            in_flight=MODEL_CAPACITY.snapshot(),
                            failures=self.failures.get(receipt.work_id, {}),
                        )
                    except Exception as exc:
                        # 配置故障不处罚模型，也不能中断已有预留的执行和保存确认
                        selection_error = exc
                if model_id is not None:
                    reservation_id = uuid4().hex
                    MODEL_CAPACITY.reserve(self.address, reservation_id, model_id)
                    self.reservations[receipt.work_id] = (reservation_id, model_id)
                    self.attempts[receipt.work_id] = attempts + 1
                    self.pending.popleft()
                    self.bus.publish(
                        Message(
                            topic=self.assignment_topic, source=self.address, target=f"queue:{self.run_id}",
                            run_id=self.run_id, work_id=receipt.work_id,
                            payload=replace(receipt, payload={
                                **receipt.payload, "model_id": model_id,
                                "attempt_number": attempts + 1, "reservation_id": reservation_id,
                            }),
                        )
                    )
                    continue
                # 退避尚未到期不是选举失败；预留未被队列消费也仍然占用容量。
                # 并发为空（账本无任何占用）且选举仍不成功 ⇒ 报错停止，不空转
                cooling = time.monotonic() < self.available_at.get(receipt.work_id, 0)
                if (
                    not self.reservations
                    and not any(MODEL_CAPACITY.snapshot().values())
                    and (selection_error is not None or not cooling)
                ):
                    if selection_error is not None:
                        logger.error(
                            "模型池选举失败，并发为空，停止分析: run_id={} work_id={} error={}",
                            self.run_id,
                            receipt.work_id,
                            selection_error,
                        )
                        raise selection_error
                    raise ModelElectionExhausted(f"work_id={receipt.work_id} 无可选模型，尝试数={attempts}")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), self.poll_seconds)
            except TimeoutError:
                pass

    def stop_elections(self) -> None:
        """停止产生新预留，已有执行的反馈仍可归还容量"""
        self.closed = True
        self._wake.set()

    def close(self) -> None:
        """按归属归还本池子全部预留；有未兑现的预留必须留痕"""
        self.closed = True
        self._wake.set()
        released = MODEL_CAPACITY.release(self.address)
        self.reservations.clear()
        if released:
            logger.warning("模型池退出时归还 {} 笔未兑现预留: run_id={}", released, self.run_id)
        self.bus.unhandle("pool.enqueue", self.address)
        self.bus.unhandle("pool.feedback", self.address)
