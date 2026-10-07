"""统计审计独立接收实际运行事实并保存，不参与 work 业务事务

2026-10-06 表合并：invocation 上下文保存在本模块内存中并随 start_turn 注入回合行；
跨重启重放的幂等去重由行上的 message_key 唯一列承担（每条审计消息自带唯一 id）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.event_bus import EventBus, Message

from .recorder import AgentAuditRecorder


class AuditPersistenceError(RuntimeError):
    """审计基础设施错误不能扣成模型失败重试"""


class AuditModule:
    def __init__(self, bus: EventBus, run_id: str, session_factory: Callable[[], Session]) -> None:
        self.bus, self.run_id = bus, run_id
        self.address = f"audit:{run_id}"
        self.queue = bus.subscribe(self.address)
        self.session_factory = session_factory
        self.identifiers: dict[tuple[str, str, int], int] = {}
        self.seen: set[str] = set()
        self.error: Exception | None = None
        self.task = asyncio.create_task(self.consume())
        bus.handle("audit.barrier", self.address, self.barrier)

    @staticmethod
    def close_interrupted(session_factory: Callable[[], Any], run_id: str) -> int:
        return AgentAuditRecorder(session_factory).close_orphaned_turns(run_id)

    @staticmethod
    def save_global_stats(session: Session, run_id: str) -> list[tuple[str, float | None]]:
        """统计模块计算并保存自己负责的全书充分统计量"""
        from src.metrics.curve_metrics import compute_global_stats
        from src.storage.repositories import StatsRepository

        values = compute_global_stats(session, run_id)
        StatsRepository(session).insert_global_stats(run_id, values)
        return values

    async def consume(self) -> None:
        while True:
            message = await self.queue.get()
            try:
                if message.message_id not in self.seen:
                    await asyncio.to_thread(self._save, message)
                    self.seen.add(message.message_id)
            except Exception as exc:
                self.error = exc
            finally:
                self.queue.task_done()

    def _save(self, message: Message) -> None:
        with self.session_factory() as session, session.begin():
            if self._skip_replayed(session, message):
                return
            recorder = AgentAuditRecorder(lambda: session, owns_transaction=False)
            if message.payload["method"] == "nonagent_usage":
                from src.storage.repositories import StatsRepository

                StatsRepository(session).insert_model_turn(
                    **message.payload["kwargs"], message_key=message.message_id
                )
            else:
                self._save_fact(message, recorder)

    def _skip_replayed(self, session: Session, message: Message) -> bool:
        """按 message_key 幂等去重；start_turn 重放需先补回本地回合 id 映射"""
        from src.storage.models import AgentToolCall, ModelTurn

        turn_id = session.execute(
            select(ModelTurn.id).where(ModelTurn.message_key == message.message_id)
        ).scalar_one_or_none()
        if turn_id is not None:
            if message.payload["method"] == "start_turn":
                self.identifiers[(message.invocation_id, "turn", message.payload["local_id"])] = int(turn_id)
            return True
        tool_id = session.execute(
            select(AgentToolCall.id).where(AgentToolCall.message_key == message.message_id)
        ).scalar_one_or_none()
        return tool_id is not None

    def _save_fact(self, message: Message, recorder: AgentAuditRecorder) -> int | None:
        payload = message.payload
        method = payload["method"]
        args = list(payload["args"])
        kwargs = dict(payload["kwargs"])
        local_id = payload["local_id"]
        execution_id = message.invocation_id
        if method == "start_invocation":
            # invocation 不落行：上下文由发起方随每条审计调用流动
            self.identifiers[(execution_id, "invocation", local_id)] = local_id
            return local_id
        if method == "start_turn":
            kwargs.pop("invocation_id")
            turn_id = recorder.start_turn(**kwargs, message_key=message.message_id)
            self.identifiers[(execution_id, "turn", local_id)] = turn_id
            return turn_id
        if method == "record_tool_call":
            recorder.record_tool_call(
                turn_id=self.identifiers[(execution_id, "turn", kwargs.pop("turn_id"))],
                **kwargs,
                message_key=message.message_id,
            )
            return None
        if method == "finish_turn":
            recorder.finish_turn(
                self.identifiers[(execution_id, "turn", args[0])],
                **kwargs,
            )
            return None
        if method == "update_turn_timings":
            recorder.update_turn_timings(
                self.identifiers[(execution_id, "turn", args[0])],
                **kwargs,
            )
            return None
        if method == "finish_invocation":
            recorder.finish_invocation(**kwargs, message_key=message.message_id)
            return None
        raise AttributeError(f"未知审计方法: {method}")

    async def barrier(self, message: Message) -> None:
        await self.queue.join()
        if self.error is not None:
            raise AuditPersistenceError(f"统计审计保存失败: {self.error}") from self.error

    async def close(self) -> None:
        await self.queue.join()
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        self.bus.unsubscribe(self.address, self.queue)
        self.bus.unhandle("audit.barrier", self.address)
        if self.error is not None:
            raise AuditPersistenceError(f"统计审计保存失败: {self.error}") from self.error


class AuditMessages:
    """同步 observer 的消息适配，只生成调用事实，不接触数据库或 Session"""

    def __init__(self, bus: EventBus, run_id: str, work_id: str, invocation_id: str, role: str) -> None:
        self.bus, self.run_id, self.work_id, self.invocation_id, self.role = bus, run_id, work_id, invocation_id, role
        self.sequence = 0

    def __getattr__(self, method: str) -> Any:
        if method not in {
            "start_invocation",
            "finish_invocation",
            "start_turn",
            "finish_turn",
            "update_turn_timings",
            "record_tool_call",
        }:
            raise AttributeError(method)

        def emit(*args: Any, **kwargs: Any) -> int:
            self.sequence += 1
            self.bus.publish(
                Message(
                    topic=f"audit:{self.run_id}",
                    source="agent",
                    target=f"audit:{self.run_id}",
                    run_id=self.run_id,
                    work_id=self.work_id,
                    invocation_id=self.invocation_id,
                    message_id=f"{self.invocation_id}:audit:{self.sequence}",
                    payload={
                        "method": method,
                        "args": args,
                        "kwargs": kwargs,
                        "local_id": self.sequence,
                        "role": self.role,
                    },
                )
            )
            return self.sequence

        return emit
