"""模型池容量位账本：并发位跟 agent 生命周期，选举即预留

2026-10-02 并发语义归位：并发数 = 同时存活的 agent 数。agent（单 agent 或子代理）
启动前领取所在模型的容量位，结束归还——"启动了但没干活"被构造性消灭：拿到位
才启动，启动即有模型容量服务其请求。容量位只在 agent 存活期间占用，任务排队、
等待容量都不占位。

2026-10-05 模型选择与容量位归模型池一处负责：队列经 dispatch 拿选举结果启动任务
（有空位的模型中加权选举并预留，reserve 时 used+1 记入预留账本），agent 启动时
兑现预留位，保证"已派发的任务必然立即干活"。

容量位是唯一的并发闸（2026-10-03 Provider permit 层已删：并发归模型池一处管，
429 退避归 stream 重试层，用量统计归 usage 回调）。
"""

from __future__ import annotations

import asyncio


class ModelSlots:
    """单个模型的容量位：容量 = 模型池条目的 max_in_flight"""

    def __init__(self, capacity: int, pool: ModelCapacity) -> None:
        self.capacity = max(1, int(capacity))
        self.used = 0
        self._cond = asyncio.Condition()
        self._pool = pool

    async def acquire(self) -> None:
        async with self._cond:
            await self._cond.wait_for(lambda: self.used < self.capacity)
            self.used += 1

    async def release(self) -> None:
        async with self._cond:
            self.used = max(0, self.used - 1)
            self._cond.notify_all()


class ModelCapacity:
    """按模型维护容量位；选举即预留，agent 启动兑现、结束归还"""

    def __init__(self) -> None:
        self._slots: dict[str, ModelSlots] = {}
        self._reservations: dict[str, str] = {}

    def slots(self, model_id: str, capacity: int) -> ModelSlots:
        """取（或建）模型的容量位；容量取最近一次传入值（热更新配置随后生效）"""
        state = self._slots.get(model_id)
        if state is None:
            state = self._slots[model_id] = ModelSlots(capacity, self)
        elif capacity > 0:
            state.capacity = max(1, int(capacity))
        return state

    def snapshot(self) -> dict[str, int]:
        return {model_id: slots.used for model_id, slots in self._slots.items()}

    def dispatch(self, work_id: str, attempt_epoch: int, previous_model_id: str | None) -> str | None:
        """派发选举：有空位的模型中加权选举并预留容量位，全部满位返回 None

        模型选择是模型池的职责，队列只拿结果启动任务；选举键按尝试次序派生，
        同一尝试的选举结果稳定。previous_model_id 传上一次失败的模型，有其他
        可用模型时不重复选它。
        """
        from src.agents.annotation.identity import stable_digest
        from src.config import settings
        from src.config.model_assignment import select_annotation_model

        model_id = select_annotation_model(
            stable_digest(work_id, attempt_epoch), settings.models.model_pool,
            previous_model_id=previous_model_id, in_flight=self.snapshot(),
        )
        if model_id is None:
            return None
        entry = next(item for item in settings.models.model_pool if item.model_id == model_id)
        self.reserve(work_id, model_id, entry.max_in_flight)
        return model_id

    def reserve(self, work_id: str, model_id: str, capacity: int) -> None:
        """派发选举成功即预留容量位（used+1）；重试覆盖同工作旧预留不重复计数"""
        previous = self._reservations.get(work_id)
        if previous == model_id:
            return
        if previous is not None:
            stale = self._slots.get(previous)
            if stale is not None:
                stale.used = max(0, stale.used - 1)
        self._reservations[work_id] = model_id
        self.slots(model_id, capacity).used += 1

    def consume(self, work_id: str, model_id: str) -> bool:
        """agent 启动兑现在途预留位；无预留（同章后续子代理）返回 False 走阻塞领取"""
        if self._reservations.get(work_id) == model_id:
            del self._reservations[work_id]
            return True
        return False

    def abandon(self, work_id: str) -> None:
        """领取事务失败时归还预留位"""
        model_id = self._reservations.pop(work_id, None)
        if model_id is not None:
            stale = self._slots.get(model_id)
            if stale is not None:
                stale.used = max(0, stale.used - 1)

    def reset(self) -> None:
        """清空全部容量位与预留账本（测试隔离用）"""
        self._slots.clear()
        self._reservations.clear()


MODEL_CAPACITY = ModelCapacity()
