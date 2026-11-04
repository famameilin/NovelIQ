"""按任务有界接管通知并持续重试，持久故障不返回业务执行链"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from loguru import logger

from src.event_bus import EVENT_BUS, EventBus, Message
from src.sse.manager import EventManager

_THINKING_FLUSH_SECONDS = 0.25
_MAX_OVERFLOW_EVENTS = 4096
"""思考块合并写间隔与队列满时的溢出上限"""


class NotificationConsumer:
    @classmethod
    def for_application(cls, manager: EventManager) -> NotificationConsumer:
        """将应用通知出口注册到进程消息总线"""
        return cls(EVENT_BUS, manager)

    def __init__(self, bus: EventBus, manager: EventManager):
        self.bus, self.manager = bus, manager
        self.queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self.workers: dict[str, asyncio.Task[None]] = {}
        self.routes: dict[str, str] = {}
        self.capacity: dict[str, Any] = {"models": [], "seats": []}
        self.errors: dict[str, str] = {}
        self.counts: dict[str, int] = {}
        self.observers: dict[str, int] = {}
        self.terminal: set[str] = set()
        self.overflow: dict[str, list[dict[str, Any]]] = {}
        self.thinking_parts: dict[tuple[str, str], list[str]] = {}
        self.thinking_meta: dict[tuple[str, str], dict[str, Any]] = {}
        self.thinking_timers: dict[tuple[str, str], asyncio.TimerHandle] = {}
        bus.handle("analysis.notification", "notifications", self.accept)
        bus.handle("analysis.capacity", "notifications", self.capacity_changed)

    def _queue(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        if task_id not in self.queues:
            self.queues[task_id] = asyncio.Queue(maxsize=512)
            self.workers[task_id] = asyncio.create_task(self._consume(task_id))
        return self.queues[task_id]

    def _put(self, task_id: str, event_type: str, data: dict[str, Any]) -> None:
        """入队永不等数据库或队列容量，满时进有界溢出缓冲"""
        message = {
            "type": event_type,
            "data": {**data, "task_id": task_id, "message_id": data.get("message_id") or uuid4().hex},
        }
        queue = self._queue(task_id)
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            overflow = self.overflow.setdefault(task_id, [])
            if len(overflow) >= _MAX_OVERFLOW_EVENTS:
                logger.warning("通知溢出缓冲已满，丢弃事件: task_id={} type={}", task_id, event_type)
                return
            overflow.append(message)
        self.counts[task_id] = self.counts.get(task_id, 0) + 1

    async def enqueue(self, task_id: str, event_type: str, data: dict[str, Any]) -> None:
        self._flush_task_thinking(task_id)
        self._put(task_id, event_type, data)

    def _buffer_thinking(self, task_id: str, data: dict[str, Any]) -> None:
        """思考块只进内存并定时合并，调用方不等待持久化"""
        text = str(data.get("content") or "")
        if not text:
            return
        key = (task_id, str(data.get("stream_id") or ""))
        self.thinking_parts.setdefault(key, []).append(text)
        self.thinking_meta[key] = data
        if key not in self.thinking_timers:
            loop = asyncio.get_running_loop()
            self.thinking_timers[key] = loop.call_later(
                _THINKING_FLUSH_SECONDS, self._flush_thinking_key, key
            )

    def _flush_thinking_key(self, key: tuple[str, str]) -> None:
        handle = self.thinking_timers.pop(key, None)
        if handle is not None:
            handle.cancel()
        parts = self.thinking_parts.pop(key, None)
        meta = self.thinking_meta.pop(key, None)
        if not parts or meta is None:
            return
        self._put(key[0], "llm_thinking", {**meta, "content": "".join(parts)})

    def _flush_task_thinking(self, task_id: str) -> None:
        for key in [item for item in self.thinking_parts if item[0] == task_id]:
            self._flush_thinking_key(key)

    def _flush_all_thinking(self) -> None:
        for key in list(self.thinking_parts):
            self._flush_thinking_key(key)
        for handle in self.thinking_timers.values():
            handle.cancel()
        self.thinking_timers.clear()

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
        event_type = message.payload["type"]
        data = {
            **message.payload["data"],
            "run_id": message.run_id,
            "message_id": message.message_id,
        }
        if event_type == "llm_thinking":
            self._buffer_thinking(task_id, data)
            return
        await self.enqueue(task_id, event_type, data)

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
            overflow = self.overflow.get(task_id)
            from_queue = not overflow
            if overflow:
                message = overflow.pop(0)
            else:
                try:
                    message = await asyncio.wait_for(queue.get(), 60)
                except TimeoutError:
                    self.queues.pop(task_id, None)
                    self.workers.pop(task_id, None)
                    self.counts.pop(task_id, None)
                    self.overflow.pop(task_id, None)
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
                self.counts[task_id] = max(0, self.counts.get(task_id, 1) - 1)
                if from_queue:
                    queue.task_done()

    async def drain(self, task_id: str) -> None:
        if task_id in self.queues:
            await self.queues[task_id].join()

    async def close(self) -> None:
        self._flush_all_thinking()
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
