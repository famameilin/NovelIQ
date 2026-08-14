"""
分块相关表 ORM 模型定义

使用 pgvector vector 类型，移除 LargeBinary

将主键改为复合主键 (chunk_id, run_id)，支持多 run_id 数据隔离；使用复合外键引用 chunks 表

本模块定义分块相关的数据表：
- Chunk: 文本分块表
- ChunkStyle: 分块风格指标表
"""

from __future__ import annotations

from sqlalchemy import (
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

# 注：sql_text 为 sqlalchemy.text 的别名——本模块存在 Chunk.text 列属性，
# 类体内 __table_args__ 直接引用 text 会解析到列对象而非函数


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
        # 2026-08-14 P1：keyword_ops 的查询是 lower(text) LIKE '%kw%'，
        # 索引必须建在同一个表达式上（lower(text) gin_trgm_ops），
        # 裸 text 列上的 trgm 索引无法被规划器命中，等于死索引
        Index(
            "idx_chunks_text_trgm",
            sql_text("lower(text) gin_trgm_ops"),
            postgresql_using="gin",
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
