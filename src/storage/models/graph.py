"""
图谱权威层 ORM 模型定义。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "canonical_name", name="uq_graph_entities_run_canonical"),
        Index("idx_graph_entities_run_last_seen", "run_id", "last_seen_chunk"),
    )


class GraphEntityAlias(Base):
    __tablename__ = "graph_entity_aliases"

    alias_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), index=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    source_chunk_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "entity_id", "alias", name="uq_graph_entity_aliases_entity_alias"),
        Index("idx_graph_entity_aliases_run_alias", "run_id", "alias"),
    )


class GraphRelationEvent(Base):
    __tablename__ = "graph_relation_events"

    relation_event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), index=True)
    from_entity_id: Mapped[int] = mapped_column(Integer, ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), index=True)
    to_entity_id: Mapped[int] = mapped_column(Integer, ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), index=True)
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_relation_row_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    directionality: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=datetime.utcnow)

    __table_args__ = (
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
    from_entity_id: Mapped[int] = mapped_column(Integer, ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), index=True)
    to_entity_id: Mapped[int] = mapped_column(Integer, ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), index=True)
    current_type: Mapped[str] = mapped_column(String(50), nullable=False)
    first_seen_chunk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_chunk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    support_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_event_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("graph_relation_events.relation_event_id", ondelete="SET NULL"), nullable=True)
    tension_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "from_entity_id", "to_entity_id", name="uq_graph_relations_current_pair"),
        Index("idx_graph_relations_current_active", "run_id", "is_active"),
    )
