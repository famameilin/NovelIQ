"""SSE 独立保存实际展示消息，游标在消息入缓存前生成"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, func, not_, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.storage.models import AnalysisRun, EventOutbox
from src.utils.identity import stable_digest

_TASK_STATE_EVENTS = {
    "stage_start", "stage_progress", "stage_complete", "task_complete", "task_error", "task_cancelled", "task_reset",
}


def display_scope(data: dict[str, Any]) -> str:
    """工作身份优先；诊断等无 work 的展示使用实际阶段作用域"""
    scope = f"{data.get('stage') or ''}:{data.get('chapter_id') or 0}:{data.get('sub_stage') or ''}"
    return str(data.get("work_id") or scope)


@dataclass
class DisplayState:
    """只从实际 SSE 重置消息恢复展示，不读取业务或审计状态"""

    restart_sequence: int = 0
    executions: dict[str, str] = field(default_factory=dict)
    retired: set[tuple[str, str]] = field(default_factory=set)
    execution_chapters: dict[str, int] = field(default_factory=dict)
    chapter_resets: dict[int, int] = field(default_factory=dict)
    suspended: set[str] = field(default_factory=set)

    def accepts(self, event_type: str, data: dict[str, Any], sequence: int | None = None) -> bool:
        if sequence is not None and event_type in _TASK_STATE_EVENTS and sequence < self.restart_sequence:
            return False
        scope, invocation = display_scope(data), str(data.get("invocation_id") or "")
        if (scope, invocation) in self.retired:
            return False
        chapter = int(data.get("chapter_id") or 0)
        if sequence is not None and sequence < self.chapter_resets.get(chapter, 0):
            return False
        if event_type == "work_reset":
            return bool(invocation)
        if scope in self.suspended:
            return False
        current = self.executions.get(scope)
        if data.get("work_id") and current is None:
            return False
        return current is None or invocation == current

    def observe(self, event_type: str, data: dict[str, Any], sequence: int) -> None:
        if event_type == "task_reset":
            self.restart_sequence = max(self.restart_sequence, sequence)
        elif event_type == "chapter_reset":
            chapter = int(data["chapter_id"])
            self.chapter_resets[chapter] = sequence
            for scope, invocation in self.executions.items():
                if self.execution_chapters.get(scope) == chapter:
                    self.retired.add((scope, invocation))
                    self.suspended.add(scope)
        elif event_type == "work_reset":
            scope, invocation = display_scope(data), str(data["invocation_id"])
            previous = self.executions.get(scope)
            if previous and previous != invocation:
                self.retired.add((scope, previous))
            self.executions[scope] = invocation
            self.execution_chapters[scope] = int(data.get("chapter_id") or 0)
            self.suspended.discard(scope)


class EventOutboxRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _resolve_run(session: Session, task_id: str) -> AnalysisRun:
        row = session.execute(
            select(AnalysisRun).where(AnalysisRun.run_id.startswith(task_id, autoescape=True))
        ).scalar_one_or_none()
        if row is None:
            raise ValueError(f"SSE 任务不存在: {task_id}")
        return row

    def reserve_sequence(self, task_id: str, message_id: str) -> int:
        with self.session_factory() as session:
            run = self._resolve_run(session, task_id)
            existing = session.get(EventOutbox, stable_digest(run.run_id, message_id))
            if existing is not None:
                return existing.stream_id
            # 数据库序列只分配展示游标，消息保存次序不会重新编号
            return int(
                session.execute(
                    text("SELECT nextval(pg_get_serial_sequence('event_outbox', 'stream_id'))")
                ).scalar_one()
            )

    def emit(
        self, task_id: str, event_type: str, data: dict[str, Any], *, sequence: int | None = None
    ) -> dict[str, Any]:
        message_id = data.get("message_id") or uuid4().hex
        sequence = sequence if sequence is not None else self.reserve_sequence(task_id, message_id)
        with self.session_factory() as session, session.begin():
            run = self._resolve_run(session, task_id)
            identifier = stable_digest(run.run_id, message_id)
            session.execute(
                insert(EventOutbox)
                .values(
                    event_id=identifier,
                    run_id=run.run_id,
                    chapter_id=data.get("chapter_id") or None,
                    stream_id=sequence,
                    event_type="stream_message",
                    payload={"type": event_type, "data": data, "message_id": message_id},
                    published_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(index_elements=[EventOutbox.event_id])
            )
            row = session.get(EventOutbox, identifier)
            if row is None or row.payload["data"] != data or row.payload["type"] != event_type:
                raise ValueError(f"SSE message_id={message_id} 重复投递内容冲突")
            return {"type": event_type, "data": data, "seq": row.stream_id}

    def replay(self, task_id: str, after_seq: int, *, limit: int = 128) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            run = self._resolve_run(session, task_id)
            state = self._display_state(session, run.run_id)
            data = EventOutbox.payload["data"]
            kind = EventOutbox.payload["type"].astext
            scope = func.coalesce(
                func.nullif(data["work_id"].astext, ""),
                func.concat(
                    func.coalesce(data["stage"].astext, ""), ":",
                    func.coalesce(data["chapter_id"].astext, "0"), ":",
                    func.coalesce(data["sub_stage"].astext, ""),
                ),
            )
            filters: list[Any] = []
            filters.append(or_(
                data["work_id"].astext.is_(None), data["work_id"].astext == "",
                data["work_id"].astext.in_(set(state.executions) - state.suspended),
            ))
            if state.restart_sequence:
                filters.append(or_(kind.not_in(_TASK_STATE_EVENTS), EventOutbox.stream_id >= state.restart_sequence))
            for key, invocation in state.executions.items():
                filters.append(or_(scope != key, data["invocation_id"].astext == invocation))
            for chapter, sequence in state.chapter_resets.items():
                filters.append(or_(
                    func.coalesce(EventOutbox.chapter_id, 0) != chapter, EventOutbox.stream_id >= sequence,
                ))
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
            select(EventOutbox).where(
                EventOutbox.run_id == run_id,
                EventOutbox.event_type == "stream_message",
                EventOutbox.payload["type"].astext.in_({"task_reset", "work_reset", "chapter_reset"}),
            ).order_by(EventOutbox.stream_id)
        ).scalars()
        for row in rows:
            state.observe(row.payload["type"], row.payload["data"], row.stream_id)
        return state

    def display_state(self, task_id: str) -> DisplayState:
        with self.session_factory() as session:
            run = self._resolve_run(session, task_id)
            return self._display_state(session, run.run_id)
