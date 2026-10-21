"""将实际执行通知补全身份后交付运行通知出口"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace

from src.event_bus import EventBus, Message
from src.event_bus.notifications import StreamEvent


class ActivityRelay:
    def __init__(self, bus: EventBus, run_id: str, emitter: Callable[[StreamEvent], Awaitable[None]] | None):
        self.bus, self.address, self.emitter = bus, f"activity:{run_id}", emitter
        bus.handle("analysis.activity", self.address, self.show)

    async def show(self, message: Message) -> None:
        if self.emitter is not None:
            await self.emitter(
                replace(
                    message.payload,
                    run_id=message.run_id,
                    work_id=message.work_id,
                    invocation_id=message.invocation_id or None,
                    message_id=message.message_id,
                )
            )

    def close(self) -> None:
        self.bus.unhandle("analysis.activity", self.address)
