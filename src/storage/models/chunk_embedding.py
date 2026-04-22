"""
创建时间: 2026-04-10
创建者: TraeAI
任务: implement-level3-vector-retrieval
说明: Chunk 向量嵌入 ORM 模型定义

本模块定义 chunk 向量嵌入相关的数据表：
- ChunkEmbedding: 存储 chunk 文本的向量嵌入，用于语义相似度检索
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.config import settings

from .base import Base

EMBEDDING_DIM = settings.models.semantic_chunking.embedding_dim


class ChunkEmbedding(Base):
    """
    Chunk 向量嵌入表

    创建时间: 2026-04-10
    创建者: TraeAI
    任务: implement-level3-vector-retrieval
    说明: 存储 chunk 文本的向量嵌入，用于 Level 3 向量检索

    使用 pgvector 扩展进行向量相似度搜索。
    向量维度为 1536，与 EmbeddingClient 配置一致。
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
