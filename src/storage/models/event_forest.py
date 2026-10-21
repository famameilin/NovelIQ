"标注与诊断共用的事件及参与者模型"

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base, naive_utcnow

#: 事件生命周期状态封闭取值
EVENT_STATUSES = ("ongoing", "resolved")
#: 伏笔兑现可能性封闭取值
PAYOFF_LIKELIHOODS = ("high", "medium", "low")


class EventParticipant(Base):
    "事件参与者：实体引用与事件中角色（名字/类型读实体，不复制）"

    __tablename__ = "event_participants"
    __table_args__ = (
        UniqueConstraint("event_id", "participant_ordinal", name="uq_event_participants_ordinal"),
        UniqueConstraint("event_id", "entity_id", name="uq_event_participants_entity"),
        {"comment": "事件参与者表：参与实体与叙事角色/动作/情绪（动态观测只关联本行）"},
    )

    participant_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="参与者主键（uuid）", default=new_id, autoincrement=False
    )
    event_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_records.event_id", ondelete="CASCADE", name="event_participants_annotation_event_fkey"),
        nullable=False,
        comment="所属事件",
    )
    participant_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, comment="参与者序号（0 起）")
    entity_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("graph_entities.entity_id", ondelete="RESTRICT", name="event_participants_entity_fkey"),
        nullable=False,
        comment="参与实体",
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, comment="事件角色")
    narrative_role: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="叙事功能")
    action: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="动作")
    emotion: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="情绪（-2..2 整数分值）")

    def __repr__(self) -> str:
        return f"<EventParticipant(participant_id={self.participant_id}, role={self.role})>"


class CompleteEvent(Base):
    "标注和诊断创建的不可变事件"

    __tablename__ = "event_records"
    __table_args__ = (
        UniqueConstraint("producer_agent_id", "local_key", name="uq_complete_events_producer_local_key"),
        Index("idx_complete_events_producer", "producer_agent_id"),
        Index("idx_events_annotation", "annotation_record_id"),
        CheckConstraint("status IN ('ongoing', 'resolved')", name="ck_events_status"),
        CheckConstraint(
            "(is_foreshadowing_root AND payoff_likelihood IS NOT NULL AND payoff_likelihood IN ('high','medium','low'))"
            " OR (NOT is_foreshadowing_root AND payoff_likelihood IS NULL)",
            name="ck_events_payoff",
        ),
        {"comment": "完整事件表：真实生产者、局部稳定键、正文与章节范围"},
    )

    event_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="事件主键（uuid）", default=new_id, autoincrement=False
    )
    producer_agent_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("agent.id", ondelete="RESTRICT", name="complete_events_producer_fkey"),
        nullable=False,
        comment="真实成功生产尝试（整轮 session 从 producer→work→session 推导）",
    )
    local_key: Mapped[str] = mapped_column(String(255), nullable=False, comment="同 work 重试沿用的局部稳定键")
    annotation_record_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("agent_annotations.record_id", ondelete="RESTRICT"), nullable=True
    )
    from_chapter_id: Mapped[int] = mapped_column("from", Integer, nullable=False)
    to_chapter_id: Mapped[int] = mapped_column("to", Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True, comment="事件创建理由")
    is_foreshadowing_root: Mapped[bool] = mapped_column(nullable=False, default=False)
    payoff_likelihood: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow)
    title: Mapped[str] = mapped_column(String, nullable=False, comment="全书事件标题")
    problem: Mapped[str] = mapped_column(String, nullable=False, comment="全书事件问题")
    summary: Mapped[str] = mapped_column(String, nullable=False, comment="全书事件概要")
    event_type: Mapped[str] = mapped_column(String, nullable=False, comment="全书事件类型")
    status: Mapped[str] = mapped_column(String(16), nullable=False, comment="全书事件状态")
    progress: Mapped[str | None] = mapped_column(String, nullable=True, comment="全书事件进展")

    def __repr__(self) -> str:
        return f"<CompleteEvent(event_id={self.event_id}, local_key={self.local_key})>"
