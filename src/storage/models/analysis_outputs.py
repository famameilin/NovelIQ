"""分析产物 ORM 模型（章节标注与整体诊断统一落点）

2026-10-06 表合并：章节标注与诊断两表收敛为 analysis_outputs
一张产物表——kind 区分产物种类，业务内容统一进 payload JSONB：
- chapter_annotation：每 run×章×角色 一行（部分唯一索引守卫），payload 为标注产出，
  actual_input 为实际输入快照，invocation_id/work_id 溯源产生它的 agent；
- agent_analysis：诊断 agent 的整体产出，每执行追加一行、读侧取最新。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from .base import Base, naive_utcnow


class AnalysisOutput(Base):
    """LLM agent 的正式分析产物"""

    __tablename__ = "analysis_outputs"
    __table_args__ = (
        CheckConstraint("kind IN ('chapter_annotation', 'agent_analysis')", name="ck_analysis_outputs_kind"),
        # 章节标注行每 run×章×角色 唯一（部分唯一索引；诊断行不在此约束内）
        Index(
            "uq_analysis_outputs_chapter_role",
            "run_id",
            "chapter_id",
            "role",
            unique=True,
            postgresql_where=text("kind = 'chapter_annotation'"),
        ),
        Index("idx_analysis_outputs_run", "run_id"),
        Index("idx_analysis_outputs_run_chapter", "run_id", "chapter_id"),
        {"comment": "分析产物表：章节标注（每 run×章×角色一行）与整体诊断（每执行追加）统一落点"},
    )

    output_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="产物主键（uuid）")
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        comment="所属分析运行",
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, comment="产物种类")
    chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="章节编号（章节标注行）")
    role: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="产出角色（solo/structure/event/evidence，章节标注行）"
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="产物内容（JSON）")
    actual_input: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}", comment="实际输入快照（章节标注行）"
    )
    invocation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="产生产物的 agent 调用 id")
    work_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, comment="铸造回执溯源标识")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )


__all__ = ["AnalysisOutput"]
