"""
主题模型运行契约表 ORM 模型定义

topic_model_runs 每个启用主题建模的分析运行保存一行完整模型契约
（《分析能力扩展路线图》§5.8）：模型与管线版本、参数快照、训练语料摘要、
模型文件 artifact 键与目录哈希。主题 ID 只在同一 run_id 的同一模型内比较，
不跨运行按编号对齐主题。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    """created_at 默认值：UTC 带时区当前时间（避免模块导入期求值）"""
    return datetime.now(UTC)


class TopicModelRun(Base):
    """
    主题模型运行表

    每行定义一个分析运行使用的完整 LDA 模型契约；参数快照覆盖
    alpha、eta、passes、iterations、random_state 等，实际主题数以
    num_topics 字段为准。
    """

    __tablename__ = "topic_model_runs"

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    model_key: Mapped[str] = mapped_column(String(255), nullable=False)
    library_version: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False)
    num_topics: Mapped[int] = mapped_column(Integer, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    dictionary_size: Mapped[int] = mapped_column(Integer, nullable=False)
    training_document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    inference_paragraph_count: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def __repr__(self) -> str:
        return (
            f"<TopicModelRun(run_id={self.run_id}, num_topics={self.num_topics}, "
            f"model_key={self.model_key})>"
        )
