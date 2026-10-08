"""SSE 独立保存实际展示消息，游标在消息入缓存前生成"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.storage.models import AnalysisRun, EventOutbox
from src.utils.identity import stable_digest


class OutboxRecords:
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
