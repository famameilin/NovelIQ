"""SSE 实际展示消息及其稳定游标"""
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, naive_utcnow


def _utcnow() -> datetime:
    return datetime.now(UTC)

class EventOutbox(Base):
    """独立保存实际展示消息，游标在消息产生时分配"""

    __tablename__ = "event_outbox"
    __table_args__ = (
        Index("idx_event_outbox_stream", "run_id", "stream_id"),
        Index("idx_event_outbox_pending", "published_at", "created_at"),
        {"comment": "SSE 事件发件箱表：实际展示消息持久化，stream_id 为稳定重放游标"},
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="事件主键")
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), comment="所属分析运行"
    )
    chapter_id: Mapped[int | None] = mapped_column(Integer, comment="章节编号（可空）")
    stream_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), nullable=False, unique=True,
        comment="全局单调游标（产生时分配）",
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, comment="事件类型")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="事件载荷")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="产生时间"
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime, comment="发布时间")
