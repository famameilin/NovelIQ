"""模型池容量位账本：并发位跟 agent 生命周期

2026-10-02 并发语义归位：并发数 = 同时存活的 agent 数。agent（单 agent 或子代理）
启动前领取所在模型的容量位，结束归还——"启动了但没干活"被构造性消灭：拿到位
才启动，启动即有模型容量服务其请求。容量位只在 agent 存活期间占用，任务排队、
等待容量都不占位。

容量位是进程内账本；跨进程硬顶由 Provider permit 层兜底（authoritative 配置 +
429 暂停 + 用量统计），单进程下 agent 领到位后其请求在 permit 层即得。
"""

from __future__ import annotations

import asyncio


class ModelSlots:
    """单个模型的容量位：容量 = 模型池条目的 max_in_flight"""

    def __init__(self, capacity: int) -> None:
        self.capacity = max(1, int(capacity))
        self.used = 0
        self._cond = asyncio.Condition()

    async def acquire(self) -> None:
        async with self._cond:
            await self._cond.wait_for(lambda: self.used < self.capacity)
            self.used += 1

    async def release(self) -> None:
        async with self._cond:
            self.used = max(0, self.used - 1)
            self._cond.notify_all()


class ModelCapacity:
    """按模型维护容量位；snapshot 供 claim 的容量感知选举读取"""

    def __init__(self) -> None:
        self._slots: dict[str, ModelSlots] = {}

    def slots(self, model_id: str, capacity: int) -> ModelSlots:
        """取（或建）模型的容量位；容量取最近一次传入值（热更新配置随后生效）"""
        state = self._slots.get(model_id)
        if state is None:
            state = self._slots[model_id] = ModelSlots(capacity)
        elif capacity > 0:
            state.capacity = max(1, int(capacity))
        return state

    def snapshot(self) -> dict[str, int]:
        return {model_id: slots.used for model_id, slots in self._slots.items()}


MODEL_CAPACITY = ModelCapacity()
