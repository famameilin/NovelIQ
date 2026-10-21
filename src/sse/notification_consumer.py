"""按任务有界接管通知并持续重试，持久故障不返回业务执行链"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from loguru import logger

from src.event_bus import EVENT_BUS, EventBus, Message
from src.sse.manager import EventManager


class NotificationConsumer:
    @classmethod
    def for_application(cls, manager: EventManager) -> NotificationConsumer:
        """将应用通知出口注册到进程消息总线"""
        return cls(EVENT_BUS, manager)

    def __init__(self, bus: EventBus, manager: EventManager):
        self.bus, self.manager = bus, manager
        self.queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.workers: dict[str, asyncio.Task[None]] = {}
        self.routes: dict[str, str] = {}
        self.capacity: dict[str, Any] = {"models": [], "seats": []}
        self.errors: dict[str, str] = {}
        self.counts: dict[str, int] = {}
        self.observers: dict[str, int] = {}
        self.terminal: set[str] = set()
        bus.handle("analysis.notification", "notifications", self.accept)
        bus.handle("analysis.capacity", "notifications", self.capacity_changed)

    def _queue(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        if task_id not in self.queues:
            self.queues[task_id] = asyncio.Queue(maxsize=512)
            self.workers[task_id] = asyncio.create_task(self._consume(task_id))
        return self.queues[task_id]

    async def enqueue(self, task_id: str, event_type: str, data: dict[str, Any]) -> None:
        self.counts[task_id] = self.counts.get(task_id, 0) + 1
        try:
            async with self.locks.setdefault(task_id, asyncio.Lock()):
                await self._queue(task_id).put(
                    {"type": event_type, "data": {
                        **data, "task_id": task_id, "message_id": data.get("message_id") or uuid4().hex,
                    }}
                )
        except BaseException:
            self.counts[task_id] -= 1
            raise

    def pending(self, task_id: str) -> int:
        return self.counts.get(task_id, 0)

    async def watch(self, run_id: str, task_id: str, *, terminal: bool = False) -> None:
        """订阅时把当前容量事实按同一队列持久化，不拼接快照外状态"""
        self.observers[task_id] = self.observers.get(task_id, 0) + 1
        self.routes[run_id] = task_id
        if terminal:
            self.terminal.add(task_id)
        await self._capacity_for(run_id, task_id)

    def unwatch(self, task_id: str) -> None:
        remaining = self.observers.get(task_id, 0) - 1
        if remaining > 0:
            self.observers[task_id] = remaining
        else:
            self.observers.pop(task_id, None)
            self._retire(task_id)

    def _retire(self, task_id: str) -> None:
        if task_id in self.terminal and task_id not in self.observers:
            self.routes = {run: task for run, task in self.routes.items() if task != task_id}

    async def accept(self, message: Message) -> None:
        task_id = message.payload["task_id"]
        new_route = message.run_id not in self.routes
        self.routes[message.run_id] = task_id
        if new_route and self.capacity["models"]:
            await self._capacity_for(message.run_id, task_id)
        await self.enqueue(
            task_id,
            message.payload["type"],
            {
                **message.payload["data"],
                "run_id": message.run_id,
                "message_id": message.message_id,
            },
        )

    async def _capacity_for(self, run_id: str, task_id: str, capacity: dict[str, Any] | None = None) -> None:
        capacity = capacity if capacity is not None else self.capacity
        seats = [
            {
                **seat,
                **(
                    {}
                    if seat["run_id"] == run_id
                    else {
                        "run_id": "",
                        "work_id": "",
                        "invocation_id": "",
                        "foreign": True,
                    }
                ),
            }
            for seat in capacity["seats"]
        ]
        await self.enqueue(task_id, "capacity", {"run_id": run_id, "models": capacity["models"], "seats": seats})

    async def capacity_changed(self, message: Message) -> None:
        self.capacity = message.payload
        await asyncio.gather(*(self._capacity_for(run_id, task_id, message.payload)
            for run_id, task_id in list(self.routes.items())))

    async def _consume(self, task_id: str) -> None:
        queue = self.queues[task_id]
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), 60)
            except TimeoutError:
                self.queues.pop(task_id, None)
                self.workers.pop(task_id, None)
                self.counts.pop(task_id, None)
                self.locks.pop(task_id, None)
                if task_id not in self.observers:
                    self.terminal.discard(task_id)
                return
            try:
                while True:
                    try:
                        await self.manager.send(task_id, message["type"], message["data"])
                        self.errors.pop(task_id, None)
                        if message["type"] in {"task_complete", "task_error", "task_cancelled"}:
                            self.terminal.add(task_id)
                            self._retire(task_id)
                        elif message["type"] in {"task_reset", "task_state"}:
                            self.terminal.discard(task_id)
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self.errors[task_id] = str(exc)
                        logger.warning(
                            "通知保存失败，保留原消息重试: task_id={} message_id={} error={}",
                            task_id,
                            message["data"]["message_id"],
                            exc,
                        )
                        await asyncio.sleep(2)
            finally:
                self.counts[task_id] -= 1
                queue.task_done()

    async def drain(self, task_id: str) -> None:
        if task_id in self.queues:
            await self.queues[task_id].join()

    async def close(self) -> None:
        try:
            await asyncio.wait_for(asyncio.gather(*(self.drain(task_id) for task_id in list(self.queues))), 5)
        except TimeoutError:
            logger.warning("通知关闭等待超时，仍有未持久通知: {}",
                {key: count for key, count in self.counts.items() if count})
        for worker in self.workers.values():
            worker.cancel()
        await asyncio.gather(*self.workers.values(), return_exceptions=True)
        self.bus.unhandle("analysis.notification", "notifications")
        self.bus.unhandle("analysis.capacity", "notifications")
