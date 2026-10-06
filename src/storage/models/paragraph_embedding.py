"""
原文自然段向量嵌入 ORM 模型定义
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ParagraphEmbedding(Base):
    """
    Paragraph 向量嵌入表（二期段落化结构，设计文档 §5.2）

    段落身份以 paragraphs 表为准（paragraph_id 稠密整数），本表只存向量与
    溯源元数据；旧结构（chunk_id/paragraph_index/paragraph_text/local/global
    坐标冗余列）已在 ensure_paragraph_embeddings_schema 中按不兼容策略
    DROP 重建，数据不回填。

    2026-09-10：列维度不再是配置——真实列宽由 ensure_paragraph_embeddings_schema
    按 preprocess 探测的模型实测维度建表固化，ORM 侧用无维度 Vector() 适配。
    """

    __tablename__ = "paragraph_embeddings"
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
        {
            "comment": "段落向量嵌入表：段落语义向量与溯源（动态建表，列宽按嵌入模型实测维度固化）",
        },
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="所属分析运行")
    paragraph_id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="所属段落编号")
    embedding_vector: Mapped[list[float] | None] = mapped_column(
        Vector(), nullable=True, comment="段落语义向量（列宽按嵌入模型维度固化）"
    )
    # 生成该向量的嵌入模型 key（settings.models.paragraph_embedding.model）
    embedding_model_key: Mapped[str | None] = mapped_column(
        String, nullable=True,
        comment="生成向量的嵌入模型 key",
    )
    # 生成该向量的嵌入维度（preprocess 探测值，写入期随行落库）
    embedding_dimension: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="嵌入维度（preprocess 探测值）"
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="创建时间")

    def __repr__(self) -> str:
        return f"<ParagraphEmbedding(run_id={self.run_id}, paragraph_id={self.paragraph_id})>"
