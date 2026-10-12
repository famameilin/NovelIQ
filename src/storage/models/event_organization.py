"""诊断阶段确认的全书叙事组织，不改变原子事件的局部结构"""

from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class NarrativeArc(Base):
    """全书叙事线，允许并列主线和没有父级的独立支线"""

    __tablename__ = "event_narrative_arcs"
    __table_args__ = (
        UniqueConstraint("run_id", "arc_id", name="uq_event_narrative_arcs_run_arc"),
        ForeignKeyConstraint(
            ["run_id", "parent_arc_id"],
            ["event_narrative_arcs.run_id", "event_narrative_arcs.arc_id"],
            name="event_narrative_arcs_parent_fkey",
        ),
        CheckConstraint("kind IN ('main', 'subplot')", name="ck_event_narrative_arcs_kind"),
        CheckConstraint("parent_arc_id IS NULL OR parent_arc_id <> arc_id", name="ck_event_narrative_arcs_self"),
        Index("idx_event_narrative_arcs_run", "run_id"),
    )
    arc_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"))
    parent_arc_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String)
    objective: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    annotation_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_outputs.output_id", ondelete="CASCADE"))


class EventMembership(Base):
    """每个原子事件唯一的主要归属，空归属必须说明尚缺的判断依据"""

    __tablename__ = "event_memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "arc_id"],
            ["event_narrative_arcs.run_id", "event_narrative_arcs.arc_id"],
            name="event_memberships_arc_fkey",
        ),
        Index("idx_event_memberships_run_arc", "run_id", "arc_id"),
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("event_nodes.event_id", ondelete="CASCADE"), primary_key=True
    )
    arc_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    role: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    annotation_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_outputs.output_id", ondelete="CASCADE"))


class EventReference(Base):
    """跨线引用同一原子事件，不复制事件和主要归属"""

    __tablename__ = "event_references"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "arc_id"],
            ["event_narrative_arcs.run_id", "event_narrative_arcs.arc_id"],
            name="event_references_arc_fkey",
        ),
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    arc_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("event_nodes.event_id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    annotation_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_outputs.output_id", ondelete="CASCADE"))
