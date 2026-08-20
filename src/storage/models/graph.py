"""章节图谱当前状态 ORM 模型"""

from __future__ import annotations

from dataclasses import dataclass
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
    """2026-08-19 用于生成章节图谱记录的 UTC 时间"""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ChapterBoundary:
    """2026-08-19 用于表示由章节身份派生的图谱边界"""

    run_id: str
    chapter_id: int
    chapter_order: int
    first_chapter_id: int
    last_chapter_id: int
    annotation_id: str


class GraphEntity(Base):
    """2026-08-19 用于保存单次分析运行内稳定的实体身份"""

    __tablename__ = "graph_entities"

    entity_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    first_seen_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    last_seen_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
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
    """2026-08-19 用于保存章节事实及其来源证据"""

    __tablename__ = "graph_facts"

    graph_fact_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    fact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_entity_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("graph_entities.entity_id", ondelete="RESTRICT"), nullable=True
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
        String(36), ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE"), nullable=False
    )
    payload_path: Mapped[str] = mapped_column(String(255), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("event_nodes.event_id", ondelete="RESTRICT"), nullable=True
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="graph_facts_chapter_run_fkey",
        ),
        ForeignKeyConstraint(
            ["effective_chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="graph_facts_effective_chapter_run_fkey",
        ),
        CheckConstraint("jsonb_array_length(evidence) > 0", name="ck_graph_facts_evidence_non_empty"),
        UniqueConstraint("run_id", "chapter_id", "fact_id", name="uq_graph_facts_run_chapter_fact"),
        UniqueConstraint("run_id", "chapter_id", "payload_path", name="uq_graph_facts_chapter_payload_path"),
        Index("idx_graph_facts_run_chapter", "run_id", "chapter_id"),
        Index("idx_graph_facts_run_subject_predicate", "run_id", "subject_entity_id", "predicate"),
        Index("idx_graph_facts_run_event", "run_id", "event_id"),
    )


class EntityState(Base):
    """2026-08-19 用于保存实体在章节边界的状态和变化"""

    __tablename__ = "entity_states"

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    chapter_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="entity_states_chapter_run_fkey",
        ),
        CheckConstraint("jsonb_array_length(changes) > 0", name="ck_entity_states_changes_non_empty"),
        Index("idx_entity_states_run_entity", "run_id", "entity_id", "chapter_id"),
    )


class GraphRelation(Base):
    """2026-08-19 用于保存稳定关系身份及其实体端点"""

    __tablename__ = "graph_relations"

    relation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    from_entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    to_entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    directionality: Mapped[str] = mapped_column(String(20), nullable=False)
    relation_semantics: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint("directionality IN ('directed', 'bidirectional')", name="ck_graph_relations_directionality"),
        CheckConstraint("relation_semantics IN ('ordinary', 'same_character')", name="ck_graph_relations_semantics"),
        CheckConstraint("from_entity_id <> to_entity_id", name="ck_graph_relations_distinct_endpoints"),
        Index("idx_graph_relations_run_from", "run_id", "from_entity_id"),
        Index("idx_graph_relations_run_to", "run_id", "to_entity_id"),
    )


class RelationState(Base):
    """2026-08-19 用于保存关系在章节边界的状态和变化"""

    __tablename__ = "relation_states"

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    chapter_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    relation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("graph_relations.relation_id", ondelete="CASCADE"), primary_key=True
    )
    relation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="relation_states_chapter_run_fkey",
        ),
        CheckConstraint("jsonb_array_length(changes) > 0", name="ck_relation_states_changes_non_empty"),
        Index("idx_relation_states_run_relation", "run_id", "relation_id", "chapter_id"),
        Index("idx_relation_states_run_active", "run_id", "is_active"),
    )
