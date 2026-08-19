"""
事件森林/DAG 过程层 ORM 模型

三层事实源中的过程层：事件节点（event_nodes）保存稳定事件身份、原文锚点与
树结构（tree_id/cause_role，契约 v3「树内图外」）；事件边（event_edges）
只保存因果关联边（causal，含树内主链/次因分支与树间/跨章边）。
foreshadowing 边的载体是 foreshadowing_threads 表（setup_event_id/payoff_event_id），
不在此表落库；contains 边不再落表，章节归属由 chapter_id 分组派生。

2026-08-18：P1 阶段影子表，API 读侧仍走 graph_facts；P2 提升为过程事实源后
才对 Agent/前端/导出暴露。2026-08-19：契约 v3 落地（contains 派生化 + 树字段）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
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
    """2026-08-18 用于生成事件森林表统一的 UTC 时间"""
    return datetime.now(UTC)


class EventNode(Base):
    """2026-08-18 用于保存事件过程层的稳定身份与原文锚点

    event_id 按 run_id + chapter_id + 事件序号确定性生成（uuid5），同一事件的
    修订只追加 event_revision，不覆盖历史。
    """

    __tablename__ = "event_nodes"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
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
    # 2026-08-19 契约 v3：事件树内部结构（Agent 显式声明）
    tree_id: Mapped[str] = mapped_column(String(255), nullable=False)
    cause_role: Mapped[str] = mapped_column(String(16), nullable=False)
    annotation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE"),
        nullable=False,
    )
    graph_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("graph_versions.graph_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    payload_path: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="event_nodes_chapter_run_fkey",
        ),
        CheckConstraint("event_revision > 0", name="ck_event_nodes_revision_positive"),
        CheckConstraint("char_end > char_start", name="ck_event_nodes_char_order"),
        CheckConstraint(
            "cause_role IN ('root', 'main', 'secondary')",
            name="ck_event_nodes_cause_role",
        ),
        UniqueConstraint("run_id", "event_id", "event_revision", name="uq_event_nodes_run_event_revision"),
        UniqueConstraint("graph_version_id", "payload_path", name="uq_event_nodes_graph_version_payload_path"),
        Index("idx_event_nodes_run_chapter", "run_id", "chapter_id"),
        Index("idx_event_nodes_run_chapter_order", "run_id", "chapter_order"),
        Index("idx_event_nodes_run_tree", "run_id", "tree_id"),
        Index("idx_event_nodes_graph_version", "graph_version_id"),
    )


class EventEdge(Base):
    """2026-08-19 用于保存事件森林/DAG 的因果关联边（契约 v3）

    事件间因果（多对多）统一落在 event_edges：树内主链/次因分支边与跨树跨章
    因果边都是 causal 类型，source/target 均为事件节点。contains 不再落表——
    章节归属由 event_nodes.chapter_id 分组派生；foreshadowing 边载体仍为
    foreshadowing_threads。
    """

    __tablename__ = "event_edges"

    edge_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    edge_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_event_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    target_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_event_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Integer, nullable=False
    )  # SQLite 兼容：Boolean 在 CheckConstraint 之外用 Integer
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    annotation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE"),
        nullable=False,
    )
    graph_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("graph_versions.graph_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    payload_path: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
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
        # causal 两端必须引用同一 run 的实际事件修订（contains 已不落表）
        ForeignKeyConstraint(
            ["run_id", "source_event_id", "source_event_revision"],
            ["event_nodes.run_id", "event_nodes.event_id", "event_nodes.event_revision"],
            ondelete="CASCADE",
            name="event_edges_source_event_fkey",
        ),
        ForeignKeyConstraint(
            ["run_id", "target_event_id", "target_event_revision"],
            ["event_nodes.run_id", "event_nodes.event_id", "event_nodes.event_revision"],
            ondelete="CASCADE",
            name="event_edges_target_event_fkey",
        ),
        CheckConstraint(
            "edge_type = 'causal'",
            name="ck_event_edges_type",
        ),
        CheckConstraint("is_active IN (0, 1)", name="ck_event_edges_is_active_bool"),
        UniqueConstraint("graph_version_id", "payload_path", name="uq_event_edges_graph_version_payload_path"),
        Index("idx_event_edges_run_source", "run_id", "source_event_id"),
        Index("idx_event_edges_run_target", "run_id", "target_event_id"),
        Index("idx_event_edges_run_type", "run_id", "edge_type"),
        Index("idx_event_edges_graph_version", "graph_version_id"),
    )
