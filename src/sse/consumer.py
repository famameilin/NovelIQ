"""展示消息消费者，独立于 work 的业务保存"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace

from src.event_bus import EventBus, Message
from src.sse.events import StreamEvent


class SSEModule:
    """消息按产生次序发送，展示出口自行管理实际保存与重放"""

    def __init__(self, bus: EventBus, run_id: str, emitter: Callable[[StreamEvent], Awaitable[None]] | None) -> None:
        self.bus, self.address, self.emitter = bus, f"sse:{run_id}", emitter
        self.seen: set[str] = set()
        self.lock = asyncio.Lock()
        self.executions: dict[str, str] = {}
        self.retired: set[tuple[str, str]] = set()
        self.execution_chapters: dict[str, int] = {}
        self.suspended: set[str] = set()
        bus.handle("sse.show", self.address, self.show)

    async def show(self, message: Message) -> None:
        async with self.lock:
            if message.message_id in self.seen:
                return
            scope = message.work_id or f"{message.payload.sub_stage}:{message.payload.chapter_id or 0}"
            invocation = message.invocation_id
            if (scope, invocation) in self.retired:
                return
            if message.payload.action == "chapter_reset":
                for key, current in self.executions.items():
                    if self.execution_chapters.get(key) == message.payload.chapter_id:
                        self.retired.add((key, current))
                        self.suspended.add(key)
            elif message.payload.action == "work_reset":
                if not invocation:
                    raise ValueError("work_reset 必须携带实际 invocation_id")
                if (scope, invocation) in self.retired:
                    return
                previous = self.executions.get(scope)
                if previous and previous != invocation:
                    self.retired.add((scope, previous))
                self.executions[scope] = invocation
                self.execution_chapters[scope] = message.payload.chapter_id or 0
                self.suspended.discard(scope)
            elif (
                scope in self.suspended
                or message.work_id and scope not in self.executions
                or scope in self.executions and self.executions[scope] != invocation
            ):
                return
            if self.emitter is not None:
                await self.emitter(
                    replace(
                        message.payload,
                        work_id=message.work_id or None,
                        invocation_id=message.invocation_id or None,
                        message_id=message.message_id,
                    )
                )
            self.seen.add(message.message_id)

    def close(self) -> None:
        self.bus.unhandle("sse.show", self.address)
