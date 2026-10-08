"""持久 SSE 消息的可见性查询，游标分配与原始消息写入委托 storage"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.orm import Session

from src.sse.state import _TASK_STATE_EVENTS, DisplayState
from src.storage.models import EventOutbox
from src.storage.repositories.event_outbox import OutboxRecords


class SseMessageRepository(OutboxRecords):
    """只管理 SSE 重放与展示状态，不读取 work 业务事务或审计记录"""

    def replay(self, task_id: str, after_seq: int, *, limit: int = 128) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            run = self._resolve_run(session, task_id)
            state = self._display_state(session, run.run_id)
            data = EventOutbox.payload["data"]
            kind = EventOutbox.payload["type"].astext
            scope = func.coalesce(
                func.nullif(data["work_id"].astext, ""),
                func.concat(
                    func.coalesce(data["stage"].astext, ""),
                    ":",
                    func.coalesce(data["chapter_id"].astext, "0"),
                    ":",
                    func.coalesce(data["sub_stage"].astext, ""),
                ),
            )
            filters: list[Any] = []
            filters.append(
                or_(
                    data["work_id"].astext.is_(None),
                    data["work_id"].astext == "",
                    data["work_id"].astext.in_(set(state.executions) - state.suspended),
                )
            )
            if state.restart_sequence:
                filters.append(or_(kind.not_in(_TASK_STATE_EVENTS), EventOutbox.stream_id >= state.restart_sequence))
            for key, invocation in state.executions.items():
                filters.append(or_(scope != key, data["invocation_id"].astext == invocation))
            for chapter, sequence in state.chapter_resets.items():
                filters.append(
                    or_(
                        func.coalesce(EventOutbox.chapter_id, 0) != chapter,
                        EventOutbox.stream_id >= sequence,
                    )
                )
            if state.suspended:
                filters.append(scope.not_in(state.suspended))
            # 整章恢复和同 work 重跑均不接受已退役执行的展示
            for key, invocation in state.retired:
                filters.append(not_(and_(scope == key, data["invocation_id"].astext == invocation)))
            rows = session.execute(
                select(EventOutbox)
                .where(
                    EventOutbox.run_id == run.run_id,
                    EventOutbox.stream_id > after_seq,
                    EventOutbox.event_type == "stream_message",
                    *filters,
                )
                .order_by(EventOutbox.stream_id)
                .limit(limit)
            ).scalars()
            return [{"type": row.payload["type"], "data": row.payload["data"], "seq": row.stream_id} for row in rows]

    @staticmethod
    def _display_state(session: Session, run_id: str) -> DisplayState:
        state = DisplayState()
        rows = session.execute(
            select(EventOutbox)
            .where(
                EventOutbox.run_id == run_id,
                EventOutbox.event_type == "stream_message",
                EventOutbox.payload["type"].astext.in_({"task_reset", "work_reset", "chapter_reset"}),
            )
            .order_by(EventOutbox.stream_id)
        ).scalars()
        for row in rows:
            state.observe(row.payload["type"], row.payload["data"], row.stream_id)
        return state

    def display_state(self, task_id: str) -> DisplayState:
        with self.session_factory() as session:
            run = self._resolve_run(session, task_id)
            return self._display_state(session, run.run_id)
