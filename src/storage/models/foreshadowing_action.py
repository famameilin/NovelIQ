"""明确伏笔动作与正文披露位置"""

from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ForeshadowingAction(Base):
    """动作事实独立于静态照应边，来源操作身份保证重试幂等"""

    __tablename__ = "event_foreshadowing_actions"
    __table_args__ = (
        ForeignKeyConstraint(["chapter_id", "run_id"], ["chapters.chapter_id", "chapters.run_id"], ondelete="CASCADE"),
        CheckConstraint("action_type IN ('setup', 'reinforce', 'payoff')", name="ck_foreshadow_action_type"),
        CheckConstraint("evidence_scope IN ('chapter', 'paragraph')", name="ck_foreshadow_action_scope"),
        CheckConstraint("jsonb_array_length(evidence) > 0", name="ck_foreshadow_action_evidence"),
        UniqueConstraint("run_id", "source_work_id", "source_operation_id", name="uq_foreshadow_action_source"),
        Index("idx_foreshadow_actions_run_root", "run_id", "root_event_id", "chapter_order"),
    )

    action_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"))
    root_event_id: Mapped[str] = mapped_column(String(36), ForeignKey("event_nodes.event_id", ondelete="CASCADE"))
    target_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("event_nodes.event_id", ondelete="CASCADE"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(16))
    chapter_id: Mapped[int] = mapped_column(Integer)
    chapter_order: Mapped[int] = mapped_column(Integer)
    source_work_id: Mapped[str] = mapped_column(String(64))
    source_operation_id: Mapped[str] = mapped_column(String(128))
    operation_order: Mapped[int] = mapped_column(Integer)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    evidence_scope: Mapped[str] = mapped_column(String(16))
    annotation_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_outputs.output_id", ondelete="CASCADE"))
