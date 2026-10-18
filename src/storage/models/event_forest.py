"""
事件声明、完整事件与阶段版本身份 ORM 模型

声明正文/原生产者/参与者/证据从声明读；origin 生产者从完整事件读；
不复制源事实，不按时间/章号猜顺序。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base, naive_utcnow

#: 事件生命周期状态封闭取值
EVENT_STATUSES = ("ongoing", "resolved")
#: 伏笔兑现可能性封闭取值
PAYOFF_LIKELIHOODS = ("high", "medium", "low")


class EventDeclaration(Base):
    "章级事件声明表（不可变）"

    __tablename__ = "event_declarations"
    __table_args__ = (
        UniqueConstraint("record_id", "local_key", name="uq_event_declarations_record_local_key"),
        CheckConstraint(
            "payoff_likelihood IS NULL OR payoff_likelihood IN ('high', 'medium', 'low')",
            name="ck_event_declarations_payoff_likelihood",
        ),
        Index("idx_event_declarations_record", "record_id"),
        {"comment": "事件声明表：不可变章级声明及伏笔属性（来源归属从标注记录取得）"},
    )

    declaration_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="声明主键（uuid）", default=new_id, autoincrement=False
    )
    record_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("chapter_annotations.record_id", ondelete="RESTRICT", name="event_declarations_record_fkey"),
        nullable=False,
        comment="来源标注记录",
    )
    local_key: Mapped[str] = mapped_column(String(255), nullable=False, comment="真实 EL 本地地址")
    title: Mapped[str] = mapped_column(String, nullable=False, comment="事件标题")
    problem: Mapped[str] = mapped_column(String, nullable=False, comment="事件问题")
    summary: Mapped[str] = mapped_column(String, nullable=False, comment="事件概要（description 读投影）")
    event_type: Mapped[str] = mapped_column(String, nullable=False, comment="事件类型")
    status: Mapped[str] = mapped_column(String(16), nullable=False, comment="声明状态（ongoing/resolved）")
    progress: Mapped[str | None] = mapped_column(String, nullable=True, comment="进展")
    is_foreshadowing_root: Mapped[bool] = mapped_column(
        nullable=False, default=False, comment="是否伏笔根（区分非伏笔与未给 likelihood 的伏笔）"
    )
    payoff_likelihood: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="兑现可能性（high/medium/low，仅伏笔声明非空）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow, comment="创建时间")

    def __repr__(self) -> str:
        return f"<EventDeclaration(declaration_id={self.declaration_id}, title={self.title})>"


class DeclarationParticipant(Base):
    "声明参与者：实体引用与事件中角色（名字/类型读实体，不复制）"

    __tablename__ = "declaration_participants"
    __table_args__ = (
        UniqueConstraint("declaration_id", "participant_ordinal", name="uq_declaration_participants_ordinal"),
        UniqueConstraint("declaration_id", "entity_id", name="uq_declaration_participants_entity"),
        {"comment": "声明参与者表：参与实体与叙事角色/动作/情绪（动态观测只关联本行）"},
    )

    participant_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="参与者主键（uuid）", default=new_id, autoincrement=False
    )
    declaration_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey(
            "event_declarations.declaration_id", ondelete="CASCADE", name="declaration_participants_declaration_fkey"
        ),
        nullable=False,
        comment="所属声明",
    )
    participant_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, comment="参与者序号（0 起）")
    entity_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("graph_entities.entity_id", ondelete="RESTRICT", name="declaration_participants_entity_fkey"),
        nullable=False,
        comment="参与实体",
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, comment="事件角色")
    narrative_role: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="叙事功能")
    action: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="动作")
    emotion: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="情绪（-2..2 整数分值）")

    def __repr__(self) -> str:
        return f"<DeclarationParticipant(participant_id={self.participant_id}, role={self.role})>"


class CompleteEvent(Base):
    "完整事件表：身份、真实生产者与同一性理由（source_work 从 producer 推导）"

    __tablename__ = "complete_events"
    __table_args__ = (
        UniqueConstraint("producer_execution_id", "local_key", name="uq_complete_events_producer_local_key"),
        Index("idx_complete_events_producer", "producer_execution_id"),
        {"comment": "完整事件表：正式身份（真实成功生产尝试 + 本地稳定键）与同一性理由"},
    )

    event_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="事件主键（uuid）", default=new_id, autoincrement=False
    )
    producer_execution_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("executions.execution_id", ondelete="RESTRICT", name="complete_events_producer_fkey"),
        nullable=False,
        comment="真实成功生产尝试（整轮 session 从 producer→work→session 推导）",
    )
    local_key: Mapped[str] = mapped_column(String(255), nullable=False, comment="同 work 重试沿用的局部稳定键")
    identity_reason: Mapped[str] = mapped_column(String, nullable=False, comment="同一身份判断理由（非诊断正文副本）")

    def __repr__(self) -> str:
        return f"<CompleteEvent(event_id={self.event_id}, local_key={self.local_key})>"


class EventRevision(Base):
    "事件阶段版本表"

    __tablename__ = "event_revisions"
    __table_args__ = (
        UniqueConstraint("event_id", "stage_index", name="uq_event_revisions_event_stage"),
        CheckConstraint(
            "origin_status IS NULL OR origin_status IN ('ongoing', 'resolved')",
            name="ck_event_revisions_origin_status",
        ),
        CheckConstraint(
            "(declaration_id IS NOT NULL AND origin_title IS NULL AND origin_problem IS NULL"
            " AND origin_summary IS NULL AND origin_event_type IS NULL AND origin_status IS NULL"
            " AND origin_progress IS NULL)"
            " OR (declaration_id IS NULL AND origin_title IS NOT NULL AND origin_problem IS NOT NULL"
            " AND origin_summary IS NOT NULL AND origin_event_type IS NOT NULL AND origin_status IS NOT NULL)",
            name="ck_event_revisions_source_shape",
        ),
        Index(
            "uq_event_revisions_declaration",
            "declaration_id",
            unique=True,
            postgresql_where=sql_text("declaration_id IS NOT NULL"),
        ),
        Index("idx_event_revisions_event", "event_id"),
        {"comment": "事件版本表：显式连续阶段链（声明绑定与独立 origin 正文互斥）"},
    )

    revision_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="版本主键（uuid）", default=new_id, autoincrement=False
    )
    event_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("complete_events.event_id", ondelete="CASCADE", name="event_revisions_event_fkey"),
        nullable=False,
        comment="所属完整事件",
    )
    stage_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="阶段序号（模型显式顺序，连续）")
    declaration_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_declarations.declaration_id", ondelete="RESTRICT", name="event_revisions_declaration_fkey"),
        nullable=True,
        comment="绑定声明（声明分支，唯一）",
    )
    origin_title: Mapped[str | None] = mapped_column(String, nullable=True, comment="origin 标题（独立新增分支）")
    origin_problem: Mapped[str | None] = mapped_column(String, nullable=True, comment="origin 问题")
    origin_summary: Mapped[str | None] = mapped_column(String, nullable=True, comment="origin 概要")
    origin_event_type: Mapped[str | None] = mapped_column(String, nullable=True, comment="origin 事件类型")
    origin_status: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="origin 生命周期状态")
    origin_progress: Mapped[str | None] = mapped_column(String, nullable=True, comment="origin 进展")

    def __repr__(self) -> str:
        return f"<EventRevision(revision_id={self.revision_id}, event_id={self.event_id}, stage={self.stage_index})>"
