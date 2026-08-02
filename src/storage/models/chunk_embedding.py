"""
Chunk / paragraph 向量嵌入 ORM 模型定义

本模块定义 chunk 向量嵌入相关的数据表：
- ChunkEmbedding: 存储 chunk 文本的向量嵌入，用于语义相似度检索
- ParagraphEmbedding: 存储 chunk 内 paragraph 文本的向量嵌入，用于 Level3 局部 evidence rerank
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKeyConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.config import settings

from .base import Base

EMBEDDING_DIM = settings.models.paragraph_embedding.embedding_dim


class ChunkEmbedding(Base):
    """
    Chunk 向量嵌入表

    存储 chunk 文本的向量嵌入，用于 Level 3 向量检索

    使用 pgvector 扩展进行向量相似度搜索
    向量维度为 1536，与 EmbeddingClient 配置一致
    """

    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    embedding_vector: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

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


class ParagraphEmbedding(Base):
    """
    Paragraph 向量嵌入表

    存储 chunk 内 paragraph 的文本、局部字符范围与 embedding，
          仅用于命中 chunk 范围内的局部 evidence rerank，不承担全库召回入口

    旧的 start_char/end_char 字段已替换为显式 local/global offset，
              避免继续使用含义模糊的字段名
    """

    __tablename__ = "paragraph_embeddings"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paragraph_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    paragraph_text: Mapped[str] = mapped_column(Text, nullable=False)
    local_start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    local_end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    global_start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    global_end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_vector: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

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
        Index("idx_paragraph_embeddings_run_id", "run_id"),
        Index("idx_paragraph_embeddings_run_chunk", "run_id", "chunk_id"),
    )

    def __repr__(self) -> str:
        return (
            "<ParagraphEmbedding("
            f"chunk_id={self.chunk_id}, paragraph_index={self.paragraph_index}, run_id={self.run_id})>"
        )
