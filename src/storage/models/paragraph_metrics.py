"""
段落指标表 ORM 模型定义

paragraph_metrics 保存段落级原始计数与充分统计量（设计文档
《章节粒度分析指标重设计》§5.3）：主数据是分子计数与分母，密度值
（pos_density 等）在 paragraph_curves 阶段按 分子/分母 计算，
本表不保存密度，避免把"以为可加、实际不可加"的均值当作聚合来源。

surface_tension_z / surface_tension 按设计 §5.3 一并持久化：
z 为 run 内稳健标准化（MAD）后的等权分量均值，surface_tension = sigmoid(z)。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    """created_at 默认值：UTC 带时区当前时间（避免模块导入期求值）"""
    return datetime.now(UTC)


class ParagraphMetric(Base):
    """
    段落指标表（原始计数与充分统计量）

    每行对应一个真实段落（paragraphs 为唯一事实源），
    章节/全书汇总必须从本表分子分母聚合，禁止平均段落密度。
    """

    __tablename__ = "paragraph_metrics"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paragraph_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_version: Mapped[str] = mapped_column(String, nullable=False)

    # 分母与基础计数
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # 句长充分统计量（count / sum / sum_sq）
    sentence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sentence_char_sum: Mapped[float] = mapped_column(Float, nullable=False)
    sentence_char_sum_sq: Mapped[float] = mapped_column(Float, nullable=False)

    # 情绪/战斗分子（权重命中）
    positive_weight_sum: Mapped[float] = mapped_column(Float, nullable=False)
    negative_weight_sum: Mapped[float] = mapped_column(Float, nullable=False)
    fight_weight_sum: Mapped[float] = mapped_column(Float, nullable=False)

    # 标点与对话计数
    exclaim_count: Mapped[int] = mapped_column(Integer, nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pause_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dialogue_char_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # 感官/意象/修辞计数
    sensory_hit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    imagery_hit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metaphor_sentence_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # 功能词与语义类别计数（只保存计数，不保存密度）
    function_word_counts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    semantic_category_counts: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # 表层张力（run 内稳健标准化 + sigmoid），由计算阶段统一填充
    surface_tension_z: Mapped[float | None] = mapped_column(Float, nullable=True)
    surface_tension: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_paragraph_metrics_run_paragraph", "run_id", "paragraph_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ParagraphMetric(run_id={self.run_id}, paragraph_id={self.paragraph_id})>"
        )
