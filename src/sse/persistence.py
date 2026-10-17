"""持久 SSE 消息的可见性查询，游标分配与原始消息写入委托 storage

2026-10-16 全库 3NF 改造：路由（run/章节/事件类型）与当时实际发出的消息字节
都在 event_outbox 宽表上按列读取，重放不按当前业务状态重建。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.sse.state import _TASK_STATE_EVENTS, DisplayState, display_scope
from src.storage.models import EventOutbox
from src.storage.repositories.event_outbox import OutboxRecords, decode_document

_REPLAY_BATCH = 128
_RESET_EVENT_TYPES = frozenset({"task_reset", "work_reset", "chapter_reset"})


class SseMessageRepository(OutboxRecords):
    """只管理 SSE 重放与展示状态，不读取 work 业务事务或审计记录"""

    def replay(self, task_id: str, after_seq: int, *, limit: int = 128) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            run = self._resolve_run(session, task_id)
            state = self._display_state(session, run.run_id)
            statement = self._replay_statement(run.run_id, after_seq, state)
            messages: list[dict[str, Any]] = []
            result = session.execute(statement).yield_per(_REPLAY_BATCH)
            try:
                for stream_id, emitted_bytes in result:
                    payload = decode_document(bytes(emitted_bytes))
                    data = payload.get("data") or {}
                    if not self._visible_to_display(state, data):
                        continue
                    messages.append({"type": payload.get("type"), "data": data, "seq": int(stream_id)})
                    # 与旧查询同口径：只返回过滤后的一整页，短页表示其后没有更多可见消息
                    if len(messages) >= limit:
                        break
            finally:
                result.close()
            return messages

    @staticmethod
    def _replay_statement(run_id: str, after_seq: int, state: DisplayState) -> Any:
        """按路由与游标做数据库侧收窄；数据侧可见性由展示状态逐条判断"""
        filters: list[Any] = [
            EventOutbox.run_id == run_id,
            EventOutbox.stream_id > after_seq,
        ]
        if state.restart_sequence:
            filters.append(
                or_(
                    EventOutbox.event_type.not_in(_TASK_STATE_EVENTS),
                    EventOutbox.stream_id >= state.restart_sequence,
                )
            )
        for chapter, sequence in state.chapter_resets.items():
            filters.append(
                or_(
                    func.coalesce(EventOutbox.chapter_id, 0) != chapter,
                    EventOutbox.stream_id >= sequence,
                )
            )
        return (
            select(EventOutbox.stream_id, EventOutbox.emitted_bytes)
            .where(*filters)
            .order_by(EventOutbox.stream_id)
        )

    @staticmethod
    def _visible_to_display(state: DisplayState, data: dict[str, Any]) -> bool:
        """旧 SQL 展示过滤的等价重写：工作可见性、执行一致性与退役执行"""
        scope = display_scope(data)
        invocation = str(data.get("invocation_id") or "")
        work_id = data.get("work_id")
        # 带工作身份的展示只接受当前在编执行；无工作身份的展示按阶段作用域判断
        if work_id and work_id not in state.executions:
            return False
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
    def _display_state(session: Session, run_id: str) -> DisplayState:
        state = DisplayState()
        rows = session.execute(
            select(EventOutbox.event_type, EventOutbox.emitted_bytes, EventOutbox.stream_id)
            .where(
                EventOutbox.run_id == run_id,
                EventOutbox.event_type.in_(_RESET_EVENT_TYPES),
            )
            .order_by(EventOutbox.stream_id)
        )
        for _event_type, emitted_bytes, stream_id in rows:
            payload = decode_document(bytes(emitted_bytes))
            state.observe(payload["type"], payload["data"], int(stream_id))
        return state

    def display_state(self, task_id: str) -> DisplayState:
        with self.session_factory() as session:
            run = self._resolve_run(session, task_id)
            return self._display_state(session, run.run_id)
