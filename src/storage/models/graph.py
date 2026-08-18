"""
章节级事实图版本 ORM 模型
"""

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
    """2026-08-07 用于生成事实图版本统一的 UTC 时间"""
    return datetime.now(UTC)


class GraphVersion(Base):
    """2026-08-07 用于保存每个章节成功提交后的唯一逻辑图边界"""

    __tablename__ = "graph_versions"

    graph_version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_order: Mapped[int] = mapped_column(Integer, nullable=False)
    first_chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    last_chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    annotation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["first_chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="graph_versions_first_chapter_run_fkey",
        ),
        ForeignKeyConstraint(
            ["last_chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="graph_versions_last_chapter_run_fkey",
        ),
        UniqueConstraint("run_id", "chapter_id", name="uq_graph_versions_run_chapter"),
        UniqueConstraint("run_id", "chapter_order", name="uq_graph_versions_run_order"),
        UniqueConstraint("annotation_id", name="uq_graph_versions_annotation"),
        Index("idx_graph_versions_run_order", "run_id", "chapter_order"),
    )


class GraphEntity(Base):
    """2026-08-07 用于保存单次分析运行内稳定的实体身份"""

    __tablename__ = "graph_entities"

    entity_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    first_seen_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    last_seen_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('character', 'location', 'item', 'organization')",
            name="ck_graph_entities_type",
        ),
        UniqueConstraint("run_id", "canonical_name", name="uq_graph_entities_run_canonical"),
        Index("idx_graph_entities_run_type", "run_id", "entity_type"),
        Index("idx_graph_entities_run_last_seen", "run_id", "last_seen_chapter"),
    )


class GraphFact(Base):
    """2026-08-07 用于保存不可变事实版本及其来源与根 Evidence

    2026-08-18：增加 event_id/event_revision（事件/伏笔事实引用事件节点）、
    evidence 列（非空 JSONB 列表，保存 TextEvidence/GraphEvidence）。
    """

    __tablename__ = "graph_facts"

    graph_fact_version_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    graph_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("graph_versions.graph_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    fact_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    fact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_entity_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("graph_entities.entity_id", ondelete="RESTRICT"),
        nullable=True,
    )
    predicate: Mapped[str] = mapped_column(String(255), nullable=False)
    object: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    participants: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    story_time: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    assertion: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    effective_chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    annotation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE"),
        nullable=False,
    )
    payload_path: Mapped[str] = mapped_column(String(255), nullable=False)
    # 2026-08-18 事件森林/DAG：事件/伏笔事实引用事件节点（非事件事实为 NULL）
    event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 2026-08-18 统一 Evidence：非空 JSONB 列表，保存 TextEvidence/GraphEvidence
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["effective_chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="graph_facts_effective_chapter_run_fkey",
        ),
        ForeignKeyConstraint(
            ["run_id", "event_id", "event_revision"],
            ["event_nodes.run_id", "event_nodes.event_id", "event_nodes.event_revision"],
            ondelete="RESTRICT",
            name="graph_facts_event_fkey",
        ),
        CheckConstraint("fact_revision > 0", name="ck_graph_facts_revision_positive"),
        # 2026-08-18 所有事实都必须携带至少一条 Evidence
        CheckConstraint(
            "jsonb_array_length(evidence) > 0",
            name="ck_graph_facts_evidence_non_empty",
        ),
        # 2026-08-18 event_id 和 event_revision 必须同时有或同时无
        CheckConstraint(
            "(event_id IS NULL AND event_revision IS NULL) OR "
            "(event_id IS NOT NULL AND event_revision IS NOT NULL)",
            name="ck_graph_facts_event_id_revision_coupled",
        ),
        UniqueConstraint("run_id", "fact_id", "fact_revision", name="uq_graph_facts_run_fact_revision"),
        UniqueConstraint("graph_version_id", "payload_path", name="uq_graph_facts_version_payload_path"),
        Index("idx_graph_facts_run_chapter", "run_id", "effective_chapter_id"),
        Index("idx_graph_facts_run_subject_predicate", "run_id", "subject_entity_id", "predicate"),
        Index("idx_graph_facts_graph_version", "graph_version_id"),
        # 2026-08-18 事件事实按 event_id 快速检索
        Index("idx_graph_facts_run_event", "run_id", "event_id"),
    )


class EntityStateVersion(Base):
    """2026-08-07 用于保存实体在章节结束时的完整状态与逐次变化"""

    __tablename__ = "entity_state_versions"

    state_version_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    graph_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("graph_versions.graph_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("graph_entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    )
    state_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint("state_revision > 0", name="ck_entity_state_versions_revision_positive"),
        CheckConstraint("jsonb_array_length(changes) > 0", name="ck_entity_state_versions_changes_non_empty"),
        UniqueConstraint("graph_version_id", "entity_id", name="uq_entity_state_versions_graph_entity"),
        UniqueConstraint("run_id", "entity_id", "state_revision", name="uq_entity_state_versions_run_revision"),
        Index("idx_entity_state_versions_run_entity", "run_id", "entity_id", "state_revision"),
        Index("idx_entity_state_versions_graph_version", "graph_version_id"),
    )


class GraphRelation(Base):
    """2026-08-07 用于保存稳定关系身份端点方向和关系语义"""

    __tablename__ = "graph_relations"

    relation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    from_entity_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("graph_entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    )
    to_entity_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("graph_entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    )
    directionality: Mapped[str] = mapped_column(String(20), nullable=False)
    relation_semantics: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "directionality IN ('directed', 'bidirectional')",
            name="ck_graph_relations_directionality",
        ),
        CheckConstraint(
            "relation_semantics IN ('ordinary', 'same_character')",
            name="ck_graph_relations_semantics",
        ),
        CheckConstraint("from_entity_id <> to_entity_id", name="ck_graph_relations_distinct_endpoints"),
        Index("idx_graph_relations_run_from", "run_id", "from_entity_id"),
        Index("idx_graph_relations_run_to", "run_id", "to_entity_id"),
    )


class GraphRelationVersion(Base):
    """2026-08-07 用于保存关系在章节结束时的完整版本与逐次变化"""

    __tablename__ = "graph_relation_versions"

    relation_version_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    graph_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("graph_versions.graph_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    relation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("graph_relations.relation_id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    relation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint("relation_revision > 0", name="ck_graph_relation_versions_revision_positive"),
        CheckConstraint(
            "jsonb_array_length(changes) > 0",
            name="ck_graph_relation_versions_changes_non_empty",
        ),
        UniqueConstraint("graph_version_id", "relation_id", name="uq_graph_relation_versions_graph_relation"),
        UniqueConstraint(
            "run_id",
            "relation_id",
            "relation_revision",
            name="uq_graph_relation_versions_run_revision",
        ),
        Index("idx_graph_relation_versions_run_relation", "run_id", "relation_id", "relation_revision"),
        Index("idx_graph_relation_versions_graph_version", "graph_version_id"),
        Index("idx_graph_relation_versions_run_active", "run_id", "is_active"),
    )
