"""章节事件森林 ORM 模型"""

from __future__ import annotations

from datetime import datetime
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

from .base import Base, naive_utcnow


class EventNode(Base):
    """2026-08-19 用于保存章节事件的稳定身份与原文锚点"""

    __tablename__ = "event_nodes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="event_nodes_chapter_run_fkey",
        ),
        CheckConstraint("char_end > char_start", name="ck_event_nodes_char_order"),
        CheckConstraint("cause_role IN ('root', 'main', 'secondary')", name="ck_event_nodes_cause_role"),
        CheckConstraint(
            "(is_foreshadowing_root = FALSE) OR (foreshadowing_status IN ('open', 'reinforced', 'likely_paid_off'))",
            name="ck_event_nodes_foreshadow_status",
        ),
        UniqueConstraint("run_id", "chapter_id", "payload_path", name="uq_event_nodes_chapter_payload_path"),
        Index("idx_event_nodes_run_chapter", "run_id", "chapter_id"),
        Index("idx_event_nodes_run_chapter_order", "run_id", "chapter_order"),
        Index("idx_event_nodes_run_tree", "run_id", "tree_id"),
        Index("idx_event_nodes_run_foreshadow_root", "run_id", "is_foreshadowing_root"),
        {"comment": "事件节点表：章节事件森林的节点身份、原文锚点与伏笔树根属性（伏笔即事件树根）"},
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="事件主键（uuid）")
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, comment="所属分析运行"
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="登记章节编号")
    chapter_order: Mapped[int] = mapped_column(Integer, nullable=False, comment="章节全书顺序号")
    description: Mapped[str] = mapped_column(String, nullable=False, comment="事件描述")
    participants: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list,
        comment="参与者列表",
    )
    anchor_paragraph_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, comment="锚点段落 id 列表")
    char_start: Mapped[int] = mapped_column(Integer, nullable=False, comment="全文起始字符偏移")
    char_end: Mapped[int] = mapped_column(Integer, nullable=False, comment="全文结束字符偏移")
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, comment="原文证据列表")
    causal_event_refs: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list,
        comment="因果引用事件 id 列表",
    )
    tree_id: Mapped[str] = mapped_column(String(255), nullable=False, comment="所属事件树 id")
    cause_role: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="树内因果角色（root/main/secondary）"
    )
    # 2026-09-13 伏笔入森林：伏笔树根事件标记与生命周期属性（仅根事件非空）
    # 2026-09-14 expected_payoff_family 列退役（写入面收敛为 isforeshadowing+confidence，
    # confidence 落 payoff_likelihood 列，值域 high/medium/low）
    is_foreshadowing_root: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否伏笔树根事件"
    )
    foreshadowing_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="伏笔状态（open/reinforced/likely_paid_off，仅根非空）"
    )
    payoff_likelihood: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="兑现可能性（high/medium/low，仅根非空）"
    )
    strength: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="伏笔强度标记（仅根非空）")
    annotation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_outputs.output_id", ondelete="CASCADE"),
        nullable=False,
        comment="来源标注 id",
    )
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False, comment="来源种类")
    payload_path: Mapped[str] = mapped_column(String(255), nullable=False, comment="章内 payload 路径（章内唯一）")
    author_work_id: Mapped[str | None] = mapped_column(String(64), comment="产生该行的 agent 执行 work 标识")
    producer_invocation_id: Mapped[str | None] = mapped_column(String(64), comment="产生该行的 agent 调用 id")
    parent_node_id: Mapped[str | None] = mapped_column(String(36), comment="树内父节点 id")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )


class EventEdge(Base):
    """2026-08-19 用于保存章节事件之间的因果边"""

    __tablename__ = "event_edges"
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
        CheckConstraint("edge_type IN ('causal', 'foreshadowing')", name="ck_event_edges_type"),
        UniqueConstraint(
            "run_id", "source_event_id", "target_event_id", "edge_type", "author_work_id", name="uq_event_edges_author"
        ),
        UniqueConstraint("run_id", "source_chapter_id", "payload_path", name="uq_event_edges_chapter_payload_path"),
        Index("idx_event_edges_run_source", "run_id", "source_event_id"),
        Index("idx_event_edges_run_target", "run_id", "target_event_id"),
        Index("idx_event_edges_run_type", "run_id", "edge_type"),
        {"comment": "事件边表：章节事件之间的因果（causal）与伏笔（foreshadowing）边"},
    )

    edge_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="边主键（uuid）")
    author_work_id: Mapped[str | None] = mapped_column(String(64), comment="产生该行的 agent 执行 work 标识")
    cause_role: Mapped[str | None] = mapped_column(String(16), comment="因果角色")
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, comment="所属分析运行"
    )
    edge_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="边类型（causal/foreshadowing）")
    source_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("event_nodes.event_id", ondelete="CASCADE"), nullable=False, comment="起因事件"
    )
    target_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("event_nodes.event_id", ondelete="CASCADE"), nullable=False, comment="结果事件"
    )
    source_chapter_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="起因事件所在章")
    target_chapter_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="结果事件所在章")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="是否活跃")
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, comment="原文证据列表")
    annotation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_outputs.output_id", ondelete="CASCADE"),
        nullable=False,
        comment="来源标注 id",
    )
    payload_path: Mapped[str] = mapped_column(String(255), nullable=False, comment="章内 payload 路径（章内唯一）")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )
    expired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="失效时间")
