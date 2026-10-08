"""
词向量模型运行契约表 ORM 模型定义

word2vec_model_runs 每个启用 Word2Vec 的分析运行保存一行模型契约
（《分析能力扩展路线图》§5.6）：维度、词表规模、参数快照、预训练来源
（source_uri）与 artifact 哈希；关闭 Word2Vec 时该运行无记录。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, naive_utcnow


class Word2VecModelRun(Base):
    """词向量模型运行表（每启用一次分析一行）"""

    __tablename__ = "word2vec_model_runs"
    __table_args__ = {"comment": "词向量模型运行表：每启用 Word2Vec 的 run 一行模型契约，维度约束 pos_embeddings 列宽"}

    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
        comment="所属分析运行（主键）",
    )
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False, comment="向量维度")
    vocabulary_size: Mapped[int] = mapped_column(Integer, nullable=False, comment="词表规模")
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="参数快照")
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True, comment="预训练来源（自训练为 NULL）")
    license_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="预训练许可名称")
    training_document_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="训练文档数")
    training_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="训练 token 数")
    artifact_key: Mapped[str] = mapped_column(Text, nullable=False, comment="模型文件 artifact 键")
    artifact_scope: Mapped[str] = mapped_column(String(20), nullable=False, comment="artifact 范围")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )

    def __repr__(self) -> str:
        return f"<Word2VecModelRun(run_id={self.run_id}, dim={self.embedding_dimension})>"
