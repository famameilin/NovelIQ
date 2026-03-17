"""
创建时间: 2026-03-15
创建者: TraeAI
任务: postgresql-migration
说明: 分块相关表 ORM 模型定义

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 使用 pgvector vector 类型，移除 LargeBinary

修改时间: 2026-03-16
修改者: TraeAI
修改内容: 将主键改为复合主键 (chunk_id, run_id)，支持多 run_id 数据隔离；使用复合外键引用 chunks 表

本模块定义分块相关的数据表：
- Chunk: 文本分块表
- ChunkStyle: 分块风格指标表
- ChunkCulture: 分块文化指标表
- ChunkTopic: 分块主题表
- ChunkEmbedding: 分块嵌入向量表（pgvector）
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKeyConstraint, Index, Integer, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

if TYPE_CHECKING:
    pass

EMBEDDING_DIM = 1536


class Chunk(Base):
    """
    文本分块表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储文本分块的基本信息

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 将主键改为复合主键 (chunk_id, run_id)，支持多 run_id 数据隔离
    """

    __tablename__ = "chunks"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    char_offset: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, primary_key=True, index=True
    )

    __table_args__ = (Index("idx_chunks_run_id", "run_id"),)

    def __repr__(self) -> str:
        return f"<Chunk(chunk_id={self.chunk_id}, run_id={self.run_id})>"


class ChunkStyle(Base):
    """
    分块风格指标表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储分块的文体风格指标数据

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 将主键改为复合主键 (chunk_id, run_id)，使用复合外键引用 chunks 表
    """

    __tablename__ = "chunk_style"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    mtld: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ttr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_sent_len: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sent_len_std: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    d_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pause_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fight_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exclaim_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dialogue_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    question_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sensory_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    metaphor_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cultural_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    function_word_vector: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category_density_combat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    category_density_body: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    category_density_relation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    category_density_faction: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    category_density_command: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    category_density_action: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    category_density_psychology: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    category_density_measure: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    category_density_emotion: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    category_density_color: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_chunk_style_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ChunkStyle(chunk_id={self.chunk_id}, run_id={self.run_id})>"


class ChunkCulture(Base):
    """
    分块文化指标表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储分块的传统文化指标数据

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 将主键改为复合主键 (chunk_id, run_id)，使用复合外键引用 chunks 表
    """

    __tablename__ = "chunk_culture"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    confucian_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    taoist_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    buddhist_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    folk_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    allusion_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    imagery_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_chunk_culture_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ChunkCulture(chunk_id={self.chunk_id}, run_id={self.run_id})>"


class ChunkTopic(Base):
    """
    分块主题表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储分块与主题的关联关系
    """

    __tablename__ = "chunk_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    topic_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    topic_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True, index=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_chunk_topics_chunk_id", "chunk_id"),
        Index("idx_chunk_topics_topic_id", "topic_id"),
        Index("idx_chunk_topics_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ChunkTopic(chunk_id={self.chunk_id}, topic_id={self.topic_id})>"


class ChunkEmbedding(Base):
    """
    分块嵌入向量表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储分块的嵌入向量，使用 pgvector 进行语义检索

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 将主键改为复合主键 (chunk_id, run_id)，使用复合外键引用 chunks 表
    """

    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    embedding_vector: Mapped[Optional[list]] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_chunk_embeddings_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ChunkEmbedding(chunk_id={self.chunk_id}, run_id={self.run_id})>"
