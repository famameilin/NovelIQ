"""
段落词性聚合向量表 ORM 模型定义

paragraph_pos_embeddings 每行是一个段落内某一归一词性分组的 Word2Vec
加权均值向量（《分析能力扩展路线图》§5.7）；维度由 word2vec_model_runs
的 embedding_dimension 约束（pgvector 0.7+ 无维度 vector 类型，插入时
按模型维度校验）。in_vocabulary_token_count=0 时向量为空。
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, naive_utcnow


class ParagraphPosEmbedding(Base):
    """段落词性聚合向量表（每段落、词性分组一行）"""

    __tablename__ = "paragraph_pos_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(["run_id"], ["word2vec_model_runs.run_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraph_linguistic_features.run_id", "paragraph_linguistic_features.paragraph_id"],
            ondelete="CASCADE",
        ),
        Index("idx_pos_embeddings_run_pos_para", "run_id", "pos_group", "paragraph_id"),
        {"comment": "段落词性聚合向量表：段落内某归一词性分组的 Word2Vec 加权均值向量"},
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="所属分析运行")
    paragraph_id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="所属段落编号")
    pos_group: Mapped[str] = mapped_column(String(50), primary_key=True, comment="归一词性分组")
    embedding_vector: Mapped[list[float] | None] = mapped_column(
        Vector(None), nullable=True, comment="词性分组均值向量（维度随 word2vec 模型）"
    )
    source_token_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="来源 token 数")
    in_vocabulary_token_count: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="词表内 token 数（0 时向量为空）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )

    def __repr__(self) -> str:
        return f"<ParagraphPosEmbedding(run_id={self.run_id}, paragraph_id={self.paragraph_id}, pos={self.pos_group})>"
