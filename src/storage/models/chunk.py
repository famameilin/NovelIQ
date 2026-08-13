"""
分块相关表 ORM 模型定义

使用 pgvector vector 类型，移除 LargeBinary

将主键改为复合主键 (chunk_id, run_id)，支持多 run_id 数据隔离；使用复合外键引用 chunks 表

本模块定义分块相关的数据表：
- Chunk: 文本分块表
- ChunkStyle: 分块风格指标表
- ChunkTopic: 分块主题表
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Chunk(Base):
    """
    文本分块表

    存储文本分块的基本信息

    将主键改为复合主键 (chunk_id, run_id)，支持多 run_id 数据隔离

    持久化 chunk 的全文起止坐标，供 paragraph global offset 和后续原文定位复用
    """

    __tablename__ = "chunks"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    char_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, primary_key=True
    )

    __table_args__ = (
        Index("idx_chunks_run_id", "run_id"),
        # pg_trgm GIN 索引支撑章节内关键词检索（LIKE '%kw%' 全表扫描兜底）
        Index(
            "idx_chunks_text_trgm",
            "text",
            postgresql_using="gin",
            postgresql_ops={"text": "gin_trgm_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<Chunk(chunk_id={self.chunk_id}, run_id={self.run_id})>"


class ChunkStyle(Base):
    """
    分块风格指标表

    存储分块的文体风格指标数据

    将主键改为复合主键 (chunk_id, run_id)，使用复合外键引用 chunks 表
    """

    __tablename__ = "chunk_style"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mtld: Mapped[float | None] = mapped_column(Float, nullable=True)
    ttr: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_sent_len: Mapped[float | None] = mapped_column(Float, nullable=True)
    sent_len_std: Mapped[float | None] = mapped_column(Float, nullable=True)
    d_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    pause_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    fight_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    exclaim_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    dialogue_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    question_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    sensory_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    metaphor_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    function_word_vector: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_density_combat: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_density_body: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_density_relation: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_density_faction: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_density_command: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_density_action: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_density_psychology: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_density_measure: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_density_emotion: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_density_color: Mapped[float | None] = mapped_column(Float, nullable=True)
    imagery_lexicon_density: Mapped[float | None] = mapped_column(Float, nullable=True)

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


class ChunkTopic(Base):
    """
    分块主题表

    存储分块与主题的关联关系
    """

    __tablename__ = "chunk_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    topic_id: Mapped[int] = mapped_column(Integer, nullable=False)
    topic_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        # 2026-08-13 修复：此前无 (run_id, chunk_id, topic_id) 唯一约束，
        # 重分析（默认全阶段重跑）后 chunk_topics 翻倍、聚合 SUM 双倍计数
        UniqueConstraint("run_id", "chunk_id", "topic_id", name="uq_chunk_topics_run_chunk_topic"),
        Index("idx_chunk_topics_chunk_id", "chunk_id"),
        Index("idx_chunk_topics_topic_id", "topic_id"),
        Index("idx_chunk_topics_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ChunkTopic(chunk_id={self.chunk_id}, topic_id={self.topic_id})>"
