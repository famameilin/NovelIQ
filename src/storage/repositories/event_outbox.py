"""数据库单调游标、持久事件写入与跨进程 SSE 重放"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import AnalysisRun, EventOutbox
from src.storage.repositories.pipeline_work import append_outbox


class EventOutboxRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _resolve_run(session: Session, task_id: str) -> AnalysisRun:
        row = session.execute(select(AnalysisRun).where(
            AnalysisRun.run_id.startswith(task_id, autoescape=True)
        )).scalar_one_or_none()
        if row is None:
            raise ValueError(f"SSE 任务不存在: {task_id}")
        return row

    def emit(self, task_id: str, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as session, session.begin():
            run = self._resolve_run(session, task_id)
            event_id = append_outbox(session, run_id=run.run_id, event_type="stream_message", payload={
                "type": event_type, "data": data, "message_id": uuid4().hex,
            })
            row = session.get(EventOutbox, event_id)
            if row is None:
                raise RuntimeError("SSE 事件写入后无法回读")
            row.published_at = datetime.now(UTC)
            return {"type": event_type, "data": data, "seq": row.stream_id}

    def replay(self, task_id: str, after_seq: int, *, limit: int = 128) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            run = self._resolve_run(session, task_id)
            rows = session.execute(select(EventOutbox).where(
                EventOutbox.run_id == run.run_id, EventOutbox.stream_id > after_seq,
            ).order_by(EventOutbox.stream_id).limit(limit)).scalars()
            return [{
                "type": row.payload["type"] if row.event_type == "stream_message" else "pipeline_progress",
                "data": row.payload["data"] if row.event_type == "stream_message" else {
                    "event_type": row.event_type, "work_id": row.work_id, "attempt_epoch": row.attempt_epoch,
                    "cutoff_hash": row.cutoff_hash, "chapter_id": row.chapter_id, **row.payload,
                }, "seq": row.stream_id,
            } for row in rows]
