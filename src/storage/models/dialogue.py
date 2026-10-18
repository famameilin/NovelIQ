"对话记录 ORM 模型（2026-10-16 全库 3NF 改造；2026-10-17 六 agent 归属）"

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base, naive_utcnow


class DialogueRecord(Base):
    "对话记录表：定位事实 + 当前实际归因（候选键身份算法不变）"

    __tablename__ = "dialogue_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "chapter_id"],
            ["chapters.run_id", "chapters.chapter_id"],
            ondelete="CASCADE",
            name="dialogue_records_chapter_fkey",
        ),
        CheckConstraint("start_char < end_char", name="ck_dialogue_records_char_order"),
        CheckConstraint(
            "related_declaration_id IS NULL OR related_complete_event_id IS NULL",
            name="ck_dialogue_records_event_refs_exclusive",
        ),
        {"comment": "对话记录表：定位事实与当前归因（原文读取投影，candidate_key 身份算法不改）"},
    )

    dialogue_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="对话主键（uuid）", default=new_id, autoincrement=False
    )
    run_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, comment="创建时所属运行")
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="创建时所属章节编号")
    creation_execution_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("executions.execution_id", ondelete="RESTRICT", name="dialogue_records_creation_fkey"),
        nullable=False,
        comment="原标注来源执行（creation execution）",
    )
    candidate_key: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="候选键（run 内唯一，案例解决定位键）"
    )
    start_char: Mapped[int] = mapped_column(Integer, nullable=False, comment="章内起始字符偏移")
    end_char: Mapped[int] = mapped_column(Integer, nullable=False, comment="章内结束字符偏移")
    current_attribution_execution_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("executions.execution_id", ondelete="RESTRICT", name="dialogue_records_attribution_fkey"),
        nullable=True,
        comment="当前归因生产者执行（诊断改归因记诊断执行）",
    )
    speaker_entity_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("graph_entities.entity_id", ondelete="SET NULL", name="dialogue_records_speaker_fkey"),
        nullable=True,
        comment="说话人实体 id（NULL=无说话人）",
    )
    tone: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="语气")
    is_inner_monologue: Mapped[bool] = mapped_column(nullable=False, default=False, comment="是否内心独白")
    related_declaration_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_declarations.declaration_id", ondelete="RESTRICT", name="dialogue_records_declaration_fkey"),
        nullable=True,
        comment="关联章级声明（与完整事件引用互斥）",
    )
    related_complete_event_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("complete_events.event_id", ondelete="RESTRICT", name="dialogue_records_event_fkey"),
        nullable=True,
        comment="关联完整事件（与声明引用互斥）",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=naive_utcnow,
        onupdate=naive_utcnow,
        comment="更新时间",
    )

    def __repr__(self) -> str:
        return f"<DialogueRecord(dialogue_id={self.dialogue_id}, candidate_key={self.candidate_key})>"
