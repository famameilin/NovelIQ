"SSE 独立保存实际展示消息，游标在消息入缓存前生成"

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.storage.ids import new_id
from src.storage.models import EventOutbox, Run
from src.storage.models.base import naive_utcnow

_DOCUMENT_SEPARATORS = (",", ":")


def encode_document(value: Any) -> bytes:
    "把实际发出的消息稳定编码为文档字节"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=_DOCUMENT_SEPARATORS, default=str).encode(
        "utf-8"
    )


def decode_document(blob: bytes) -> Any:
    "把发出消息的文档字节解码回原 JSON 语义"
    return json.loads(blob.decode("utf-8"))


class OutboxRecords:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _resolve_run(session: Session, task_id: str) -> Run:
        row = session.execute(select(Run).where(Run.taskid == task_id)).scalar_one_or_none()
        if row is None:
            raise ValueError(f"SSE 任务不存在: {task_id}")
        return row

    def reserve_sequence(self, task_id: str, message_id: str) -> int:
        session = self._session
        run = self._resolve_run(session, task_id)
        existing = session.scalar(
            select(EventOutbox).where(EventOutbox.run_id == run.id, EventOutbox.message_key == message_id)
        )
        if existing is not None:
            return int(existing.stream_id)
        return int(
            session.execute(text("SELECT nextval(pg_get_serial_sequence('agent_outbox', 'stream_id'))")).scalar_one()
        )

    def emit(
        self, task_id: str, event_type: str, data: dict[str, Any], *, sequence: int | None = None
    ) -> dict[str, Any]:
        message_id = data.get("message_id") or new_id()
        sequence = sequence if sequence is not None else self.reserve_sequence(task_id, message_id)
        chapter_id = data.get("chapter_id") or None
        emitted = {"type": event_type, "data": data, "message_id": message_id}
        session = self._session
        run = self._resolve_run(session, task_id)
        identifier = new_id()
        now = naive_utcnow()
        session.execute(
            insert(EventOutbox)
            .values(
                event_id=identifier,
                message_key=message_id,
                stream_id=sequence,
                run_id=run.id,
                chapter_id=chapter_id,
                event_type=event_type,
                emitted_bytes=encode_document(emitted),
                created_at=now,
                published_at=now,
            )
            .on_conflict_do_nothing(index_elements=[EventOutbox.run_id, EventOutbox.message_key])
        )
        row = session.scalar(
            select(EventOutbox).where(EventOutbox.run_id == run.id, EventOutbox.message_key == message_id)
        )
        if row is None:
            raise ValueError(f"SSE message_id={message_id} 消息身份丢失")
        if (
            row.run_id != run.id
            or row.event_type != event_type
            or row.chapter_id != chapter_id
            or (decode_document(bytes(row.emitted_bytes)) != emitted)
        ):
            raise ValueError(f"SSE message_id={message_id} 重复投递内容冲突")
        return {"type": event_type, "data": data, "seq": int(row.stream_id)}


def replay_candidates(session, run_id, after_seq, restart_sequence, chapter_resets, task_state_events, limit):
    from sqlalchemy import func, or_

    filters = [EventOutbox.run_id == run_id, EventOutbox.stream_id > after_seq]
    if restart_sequence:
        filters.append(or_(EventOutbox.event_type.not_in(task_state_events), EventOutbox.stream_id >= restart_sequence))
    for chapter, sequence in chapter_resets.items():
        filters.append(or_(func.coalesce(EventOutbox.chapter_id, 0) != int(chapter), EventOutbox.stream_id >= sequence))
    return session.execute(
        select(EventOutbox.stream_id, EventOutbox.emitted_bytes)
        .where(*filters)
        .order_by(EventOutbox.stream_id)
        .limit(limit)
    ).all()
