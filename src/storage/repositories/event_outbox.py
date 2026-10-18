"""SSE 独立保存实际展示消息，游标在消息入缓存前生成

消息身份、全局游标、真实路由、当时实际发出的消息字节与实际投递时刻
都在 event_outbox 表（stream_id 为 Identity 自增游标；未投递 published_at
为空，不补创建时间）。
发出消息字节的稳定编码属于该表的存储合同：同一消息得到同一字节（键序固定、
中文不转义、UTF-8），解码回原 JSON 语义供重放。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.storage.models import AnalysisRun, EventOutbox
from src.storage.models.base import naive_utcnow
from src.utils.identity import stable_digest

_DOCUMENT_SEPARATORS = (",", ":")


def encode_document(value: Any) -> bytes:
    """把实际发出的消息稳定编码为文档字节"""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=_DOCUMENT_SEPARATORS,
        default=str,
    ).encode("utf-8")


def decode_document(blob: bytes) -> Any:
    """把发出消息的文档字节解码回原 JSON 语义"""
    return json.loads(blob.decode("utf-8"))


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
                return int(existing.stream_id)
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
        chapter_id = data.get("chapter_id") or None
        emitted = {"type": event_type, "data": data, "message_id": message_id}
        with self.session_factory() as session, session.begin():
            run = self._resolve_run(session, task_id)
            identifier = stable_digest(run.run_id, message_id)
            now = naive_utcnow()
            session.execute(
                insert(EventOutbox)
                .values(
                    event_id=identifier,
                    stream_id=sequence,
                    run_id=run.run_id,
                    chapter_id=chapter_id,
                    event_type=event_type,
                    emitted_bytes=encode_document(emitted),
                    created_at=now,
                    # 消息已在本轮展示路径投递后才写发件箱；未投递的消息不会有这一行
                    published_at=now,
                )
                .on_conflict_do_nothing(index_elements=[EventOutbox.event_id])
            )
            row = session.get(EventOutbox, identifier)
            if row is None:
                raise ValueError(f"SSE message_id={message_id} 消息身份丢失")
            if (
                row.run_id != run.run_id
                or row.event_type != event_type
                or row.chapter_id != chapter_id
                or decode_document(bytes(row.emitted_bytes)) != emitted
            ):
                raise ValueError(f"SSE message_id={message_id} 重复投递内容冲突")
            return {"type": event_type, "data": data, "seq": int(row.stream_id)}
