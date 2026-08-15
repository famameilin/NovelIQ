"""
原文自然段向量嵌入 ORM 模型定义
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.config import settings

from .base import Base

EMBEDDING_DIM = settings.models.paragraph_embedding.embedding_dim


class ParagraphEmbedding(Base):
    """
    Paragraph 向量嵌入表（二期段落化结构，设计文档 §5.2）

    段落身份以 paragraphs 表为准（paragraph_id 稠密整数），本表只存向量与
    溯源元数据；旧结构（chapter_id/paragraph_index/paragraph_text/local/global
    坐标冗余列）已在 ensure_paragraph_embeddings_schema 中按不兼容策略
    DROP 重建，数据不回填。
    """

    __tablename__ = "paragraph_embeddings"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paragraph_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    embedding_vector: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    # 生成该向量的嵌入模型 key（settings.models.paragraph_embedding.model）
    embedding_model_key: Mapped[str | None] = mapped_column(String, nullable=True)
    # 生成该向量的嵌入维度（settings.models.paragraph_embedding.embedding_dim）
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 段落内容 sha256 hex，供派生数据校验段落内容未变（对照 paragraphs.content_hash）
    source_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE",
        ),
        Index("idx_paragraph_embeddings_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return (
            "<ParagraphEmbedding("
            f"run_id={self.run_id}, paragraph_id={self.paragraph_id})>"
        )
