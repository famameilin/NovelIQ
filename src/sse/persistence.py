"""持久 SSE 消息的可见性查询，游标分配与原始消息写入委托 storage

消息按 agent_outbox 宽表列读取（run/章节/事件类型与实际发出的字节），重放不按当前业务状态重建。
"""

from __future__ import annotations

import json
from typing import Any

from src.sse.state import _TASK_STATE_EVENTS, DisplayState, display_scope
from src.storage import Storage

_REPLAY_BATCH = 128
_RESET_EVENT_TYPES = frozenset({"task_reset", "work_reset", "chapter_reset"})


class SseMessageRepository:
    """只管理 SSE 重放与展示状态，不读取 work 业务事务或审计记录"""

    def __init__(self, storage_factory):
        self.storage_factory = storage_factory

    def reserve_sequence(self, task_id: str, message_id: str) -> int:
        return self.storage_factory().sse.reserve_sequence(task_id, message_id)

    def emit(self, task_id: str, event_type: str, data: dict, *, sequence: int | None = None) -> dict:
        return self.storage_factory().sse.emit(task_id, event_type, data, sequence=sequence)

    def replay(self, task_id: str, after_seq: int, *, limit: int = 128) -> list[dict[str, Any]]:
        storage = self.storage_factory()
        run = storage.runs.get_run_by_task_id(task_id)
        if run is None:
            raise ValueError(f"SSE 任务不存在: {task_id}")
        state = self._display_state(storage, run["run_id"])
        messages: list[dict[str, Any]] = []
        cursor = after_seq
        while len(messages) < limit:
            rows = storage.sse.replay_candidates(
                run["run_id"], cursor, state.restart_sequence, state.chapter_resets, _TASK_STATE_EVENTS
            )
            if not rows:
                break
            for row in rows:
                cursor = int(row.stream_id)
                payload = json.loads(bytes(row.emitted_bytes))
                data = payload.get("data") or {}
                if self._visible_to_display(state, data):
                    messages.append({"type": payload.get("type"), "data": data, "seq": cursor})
                    if len(messages) >= limit:
                        break
        return messages

    @staticmethod
    def _visible_to_display(state: DisplayState, data: dict[str, Any]) -> bool:
        """旧 SQL 展示过滤的等价重写：执行一致性与退役执行（作用域取实际阶段上下文）"""
        scope = display_scope(data)
        invocation = str(data.get("invocation_id") or "")
        if scope in state.suspended:
            return False
        for key, current in state.executions.items():
            if key == scope and invocation != current:
                return False
        for key, current in state.retired:
            if key == scope and invocation == current:
                return False
        return True

    @staticmethod
    def _display_state(session: Storage, run_id: str) -> DisplayState:
        state = DisplayState()
        rows = session.reads.sse_persistence_display_state_1(_RESET_EVENT_TYPES, run_id)
        for row in rows:
            payload = json.loads(bytes(row.emitted_bytes))
            state.observe(payload["type"], payload["data"], int(row.stream_id))
        return state

    def display_state(self, task_id: str) -> DisplayState:
        storage = self.storage_factory()
        run = storage.runs.get_run_by_task_id(task_id)
        if run is None:
            raise ValueError(f"SSE 任务不存在: {task_id}")
        return self._display_state(storage, run["run_id"])
