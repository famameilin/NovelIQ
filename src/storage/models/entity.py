"""
创建时间: 2026-03-15
创建者: TraeAI
任务: postgresql-migration
说明: 实体相关表 ORM 模型定义

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 使用 pgvector vector 类型，移除 LargeBinary

本模块定义实体相关的数据表：
- Entity: 实体表
- EntityAlias: 实体别名表
- EntityRelation: 实体关系表
- EntitySnapshot: 实体快照表
- EntityRegistry: 实体注册表
"""

from __future__ import annotations

from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, Index, Integer, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

EMBEDDING_DIM = 1536


class Entity(Base):
    """
    实体表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储识别出的实体（人物、地点等），使用 pgvector 进行语义检索
    """

    __tablename__ = "entities"

    entity_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    canonical: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    first_chunk: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_chunk: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    embedding_vector: Mapped[Optional[list]] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True, index=True
    )

    __table_args__ = (
        UniqueConstraint("novel_id", "canonical", name="uq_entities_novel_canonical"),
        Index("idx_entities_novel_id", "novel_id"),
        Index("idx_entities_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<Entity(entity_id={self.entity_id}, canonical={self.canonical})>"


class EntityAlias(Base):
    """
    实体别名表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储实体的别名/绰号等
    """

    __tablename__ = "entity_aliases"

    alias_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    alias_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_chunk: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confirm_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True, index=True
    )

    __table_args__ = (
        UniqueConstraint("entity_id", "alias", name="uq_entity_aliases_entity_alias"),
        Index("idx_entity_aliases_alias", "alias"),
        Index("idx_entity_aliases_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<EntityAlias(alias_id={self.alias_id}, alias={self.alias})>"


class EntityRelation(Base):
    """
    实体关系表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储实体之间的关系
    """

    __tablename__ = "entity_relations"

    rel_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    from_entity: Mapped[int] = mapped_column(
        Integer, ForeignKey("entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    to_entity: Mapped[int] = mapped_column(
        Integer, ForeignKey("entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    rel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    first_chunk: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_chunk: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tension: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True, index=True
    )

    __table_args__ = (
        UniqueConstraint("novel_id", "from_entity", "to_entity", "rel_type", name="uq_entity_relations"),
        Index("idx_entity_relations_novel_id", "novel_id"),
        Index("idx_entity_relations_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<EntityRelation(rel_id={self.rel_id}, type={self.rel_type})>"


class EntitySnapshot(Base):
    """
    实体快照表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储实体在特定分块的状态快照
    """

    __tablename__ = "entity_snapshots"

    snap_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    state_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True, index=True
    )

    __table_args__ = (
        UniqueConstraint("novel_id", "entity_id", "chunk_id", name="uq_entity_snapshots"),
        Index("idx_entity_snapshots_novel_chunk", "novel_id", "chunk_id"),
        Index("idx_entity_snapshots_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<EntitySnapshot(snap_id={self.snap_id}, entity_id={self.entity_id})>"


class EntityRegistry(Base):
    """
    实体注册表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储活跃实体的状态信息
    """

    __tablename__ = "entity_registry"

    entity_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chunks.chunk_id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_emotion: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    emotion_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True, index=True
    )

    __table_args__ = (
        Index("idx_entity_registry_chunk_id", "chunk_id"),
        Index("idx_entity_registry_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<EntityRegistry(entity_id={self.entity_id}, name={self.name})>"
