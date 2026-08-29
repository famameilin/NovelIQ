"""
词向量模型运行契约表 ORM 模型定义

word2vec_model_runs 每个启用 Word2Vec 的分析运行保存一行模型契约
（《分析能力扩展路线图》§5.6）：维度、词表规模、参数快照、预训练来源
（source_uri）与 artifact 哈希；关闭 Word2Vec 时该运行无记录。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CHAR, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    """created_at 默认值：UTC 带时区当前时间（避免模块导入期求值）"""
    return datetime.now(UTC)


class Word2VecModelRun(Base):
    """词向量模型运行表（每启用一次分析一行）"""

    __tablename__ = "word2vec_model_runs"

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    vocabulary_size: Mapped[int] = mapped_column(Integer, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    license_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    training_corpus_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    training_document_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    training_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_key: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    artifact_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def __repr__(self) -> str:
        return f"<Word2VecModelRun(run_id={self.run_id}, dim={self.embedding_dimension})>"