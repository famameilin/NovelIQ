"""
主题模型运行契约表 ORM 模型定义

topic_model_runs 每个启用主题建模的分析运行保存一行完整模型契约
（《分析能力扩展路线图》§5.8）：模型与管线版本、参数快照、训练语料摘要、
模型文件 artifact 键与目录哈希。主题 ID 只在同一 run_id 的同一模型内比较，
不跨运行按编号对齐主题。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, naive_utcnow


class TopicModelRun(Base):
    """
    主题模型运行表

    每行定义一个分析运行使用的完整 LDA 模型契约；参数快照覆盖
    alpha、eta、passes、iterations、random_state 等，实际主题数以
    num_topics 字段为准。
    """

    __tablename__ = "topic_model_runs"
    __table_args__ = {"comment": "主题模型运行表：每启用主题建模的 run 一行 LDA 模型契约（主题 id 不跨 run 对齐）"}

    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
        comment="所属分析运行（主键）",
    )
    model_key: Mapped[str] = mapped_column(String(255), nullable=False, comment="模型 key")
    library_version: Mapped[str] = mapped_column(String(64), nullable=False, comment="建模库版本")
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False, comment="预处理管线版本")
    num_topics: Mapped[int] = mapped_column(Integer, nullable=False, comment="实际主题数 K")
    parameters: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        comment="参数快照（alpha/eta/passes/iterations/random_state 等）",
    )
    dictionary_size: Mapped[int] = mapped_column(Integer, nullable=False, comment="词典规模")
    training_document_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="训练文档数")
    inference_paragraph_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="推断段落数")
    artifact_key: Mapped[str] = mapped_column(Text, nullable=False, comment="模型文件 artifact 键")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )

    def __repr__(self) -> str:
        return (
            f"<TopicModelRun(run_id={self.run_id}, num_topics={self.num_topics}, "
            f"model_key={self.model_key})>"
        )
