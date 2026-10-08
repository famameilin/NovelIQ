"""对话记录独立表 ORM 模型"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, naive_utcnow


class DialogueRecord(Base):
    """2026-08-11 用于保存系统绑定对话原文位置与语义结果，案例解决直接更新本表"""

    __tablename__ = "dialogue_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="dialogue_records_chapter_run_fkey",
        ),
        Index("idx_dialogue_records_run_chapter", "run_id", "chapter_id"),
        # 2026-08-12 唯一约束兜底 (run_id, candidate_key)：案例解决按该键 scalar_one_or_none 定位，
        # 唯一性此前仅靠应用层保证，防止重复候选键导致定位歧义
        UniqueConstraint(
            "run_id",
            "candidate_key",
            name="uq_dialogue_records_run_candidate",
        ),
        {"comment": "对话记录表：对话原文位置与语义结果，说话人存图实体 id，案例解决直接更新本表"},
    )

    dialogue_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="对话主键（uuid）")
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        comment="所属分析运行",
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="章节编号")
    author_work_id: Mapped[str | None] = mapped_column(String(64), comment="产生该行的 agent 执行 work 标识")
    candidate_key: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="候选键（run 内唯一，案例解决定位键）",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="对话原文")
    start: Mapped[int] = mapped_column(Integer, nullable=False, comment="起始字符偏移")
    end: Mapped[int] = mapped_column(Integer, nullable=False, comment="结束字符偏移")
    # 2026-09-17 说话人存图实体 id（原为登记名字符串）：名字不是稳定键，读取侧按 id 取实体、
    # 不再按名字形态猜有效性。实体行不存在时置空（ondelete=SET NULL），归因缺失与
    # "没判出说话人"同义——两种情形读取侧都当无说话人处理。
    # 2026-09-19 图实体主键改 uuid（String(36)），跟随。
    speaker: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("graph_entities.entity_id", ondelete="SET NULL"),
        nullable=True,
        comment="说话人图实体 id（实体删除置空，NULL=无说话人）",
    )
    tone: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="语气")
    is_inner_monologue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否内心独白")
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, comment="判定置信度")
    # 2026-08-18 事件森林/DAG P3：对话弱关联事件（可空——无匹配或多匹配时为 NULL）
    event_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
        comment="弱关联事件 id（无匹配或多匹配为 NULL）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=naive_utcnow,
        onupdate=naive_utcnow,
        comment="更新时间",
    )

    def __repr__(self) -> str:
        return f"<DialogueRecord(dialogue_id={self.dialogue_id}, run_id={self.run_id}, chapter_id={self.chapter_id})>"
