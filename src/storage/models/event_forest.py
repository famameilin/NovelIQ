"""章节事件森林 ORM 模型"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    """2026-08-19 用于生成事件森林表统一的 UTC 时间"""
    return datetime.now(UTC)


class EventNode(Base):
    """2026-08-19 用于保存章节事件的稳定身份与原文锚点"""

    __tablename__ = "event_nodes"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_order: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    participants: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    anchor_paragraph_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    causal_event_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    tree_id: Mapped[str] = mapped_column(String(255), nullable=False)
    cause_role: Mapped[str] = mapped_column(String(16), nullable=False)
    annotation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    payload_path: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="event_nodes_chapter_run_fkey",
        ),
        CheckConstraint("char_end > char_start", name="ck_event_nodes_char_order"),
        CheckConstraint("cause_role IN ('root', 'main', 'secondary')", name="ck_event_nodes_cause_role"),
        UniqueConstraint("run_id", "chapter_id", "payload_path", name="uq_event_nodes_chapter_payload_path"),
        Index("idx_event_nodes_run_chapter", "run_id", "chapter_id"),
        Index("idx_event_nodes_run_chapter_order", "run_id", "chapter_order"),
        Index("idx_event_nodes_run_tree", "run_id", "tree_id"),
    )


class EventEdge(Base):
    """2026-08-19 用于保存章节事件之间的因果边"""

    __tablename__ = "event_edges"

    edge_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    edge_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("event_nodes.event_id", ondelete="CASCADE"), nullable=False
    )
    target_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("event_nodes.event_id", ondelete="CASCADE"), nullable=False
    )
    source_chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    annotation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE"), nullable=False
    )
    payload_path: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="event_edges_source_chapter_run_fkey",
        ),
        ForeignKeyConstraint(
            ["target_chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="event_edges_target_chapter_run_fkey",
        ),
        CheckConstraint("edge_type = 'causal'", name="ck_event_edges_type"),
        UniqueConstraint("run_id", "source_event_id", "target_event_id", name="uq_event_edges_endpoints"),
        UniqueConstraint("run_id", "source_chapter_id", "payload_path", name="uq_event_edges_chapter_payload_path"),
        Index("idx_event_edges_run_source", "run_id", "source_event_id"),
        Index("idx_event_edges_run_target", "run_id", "target_event_id"),
        Index("idx_event_edges_run_type", "run_id", "edge_type"),
    )
