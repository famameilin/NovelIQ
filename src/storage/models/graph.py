"""
图谱权威层 ORM 模型定义
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GraphEntity(Base):
    __tablename__ = "graph_entities"

    entity_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, default="character")
    first_seen_chunk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_chunk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primary_role_function: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_emotion_score: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    source_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint("run_id", "canonical_name", name="uq_graph_entities_run_canonical"),
        Index("idx_graph_entities_run_last_seen", "run_id", "last_seen_chunk"),
    )


class GraphEntityAlias(Base):
    __tablename__ = "graph_entity_aliases"

    alias_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), index=True)
    entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    source_chunk_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("run_id", "entity_id", "alias", name="uq_graph_entity_aliases_entity_alias"),
        Index("idx_graph_entity_aliases_run_alias", "run_id", "alias"),
    )


class GraphRelationEvent(Base):
    __tablename__ = "graph_relation_events"

    relation_event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), index=True)
    from_entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), index=True
    )
    to_entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_relation_row_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    directionality: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=lambda: datetime.now(UTC))

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
            name="graph_relation_events_chunk_id_run_id_fkey",
        ),
        CheckConstraint(
            "change_type IN ('新建', '强化', '弱化', '断裂')",
            name="ck_graph_relation_events_change_type_v2",
        ),
        UniqueConstraint(
            "run_id",
            "source_relation_row_id",
            name="uq_graph_relation_events_source_row",
        ),
        Index("idx_graph_relation_events_pair", "run_id", "from_entity_id", "to_entity_id"),
    )


class GraphRelationCurrent(Base):
    __tablename__ = "graph_relations_current"

    relation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), index=True)
    from_entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), index=True
    )
    to_entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), index=True
    )
    current_type: Mapped[str] = mapped_column(String(50), nullable=False)
    first_seen_chunk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_chunk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    support_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_event_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("graph_relation_events.relation_event_id", ondelete="SET NULL"), nullable=True
    )
    tension_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint("run_id", "from_entity_id", "to_entity_id", name="uq_graph_relations_current_pair"),
        Index("idx_graph_relations_current_active", "run_id", "is_active"),
    )


class GraphEntityParticipant(Base):
    __tablename__ = "graph_entity_participants"

    participant_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), index=True)
    entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), index=True
    )
    relation_event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_degree: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    historical_degree: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_relation_chunk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_relation_chunk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_relation_event_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("graph_relation_events.relation_event_id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint("run_id", "entity_id", name="uq_graph_entity_participants_run_entity"),
        Index("idx_graph_entity_participants_run_entity", "run_id", "entity_id"),
    )


class GraphFact(Base):
    """2026-08-05 用于保存章节标注与 continuity fact 的通用数据库图投影"""

    __tablename__ = "graph_facts"

    graph_fact_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    stable_fact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    fact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False)
    predicate: Mapped[str] = mapped_column(String(255), nullable=False)
    object: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    participants: Mapped[list] = mapped_column(JSONB, nullable=False)
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    story_time: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    assertion: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint("run_id", "stable_fact_id", name="uq_graph_facts_run_stable"),
        Index("idx_graph_facts_run_subject_predicate", "run_id", "subject_name", "predicate"),
        Index("idx_graph_facts_run_active", "run_id", "active"),
    )


class GraphFactSource(Base):
    """2026-08-05 用于关联稳定来源事实与实际图投影行"""

    __tablename__ = "graph_fact_sources"

    source_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    graph_fact_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("graph_facts.graph_fact_id", ondelete="CASCADE"),
        nullable=False,
    )
    stable_fact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    annotation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE"),
        nullable=True,
    )
    continuity_fact_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("continuity_facts.fact_id", ondelete="CASCADE"),
        nullable=True,
    )
    payload_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint("run_id", "stable_fact_id", name="uq_graph_fact_sources_run_stable"),
        Index("idx_graph_fact_sources_annotation", "run_id", "annotation_id"),
        Index("idx_graph_fact_sources_continuity", "run_id", "continuity_fact_id"),
    )


class GraphFactVersion(Base):
    """2026-08-05 用于保存事实 refine supersede 与 retract 的稳定版本关系"""

    __tablename__ = "graph_fact_versions"

    version_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    previous_stable_fact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    current_stable_fact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    change_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "previous_stable_fact_id",
            "current_stable_fact_id",
            name="uq_graph_fact_versions_edge",
        ),
        Index("idx_graph_fact_versions_previous", "run_id", "previous_stable_fact_id"),
    )
