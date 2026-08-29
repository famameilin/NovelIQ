"""
段落语言结构特征表 ORM 模型定义

paragraph_linguistic_features 每个段落一行保存 LTP 词性/词长/句式/依存
句法基础结果（《分析能力扩展路线图》§5.3）：原始结构数据与可加充分统计量，
不保存章节或全书比例；比例一律查询时计算。

tokens 与 dependency_arcs 固定 JSON 结构，词元区间、词长计数与词性计数
均与 ltp_token_count 守恒。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CHAR, DateTime, ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    """created_at 默认值：UTC 带时区当前时间（避免模块导入期求值）"""
    return datetime.now(UTC)


class ParagraphLinguisticFeature(Base):
    """段落语言结构特征表（每段一行）"""

    __tablename__ = "paragraph_linguistic_features"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paragraph_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    ltp_token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens: Mapped[list] = mapped_column(JSONB, nullable=False)
    word_length_counts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pos_counts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sentence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sentence_pattern_counts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    dependency_arcs: Mapped[list] = mapped_column(JSONB, nullable=False)
    dependency_node_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dependency_root_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dependency_depth_sum: Mapped[int] = mapped_column(Integer, nullable=False)
    dependency_depth_max: Mapped[int] = mapped_column(Integer, nullable=False)
    dependency_relation_counts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE"),
        Index("idx_linguistic_features_run_paragraph", "run_id", "paragraph_id"),
    )

    def __repr__(self) -> str:
        return f"<ParagraphLinguisticFeature(run_id={self.run_id}, paragraph_id={self.paragraph_id})>"