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

from datetime import datetime

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

from .base import Base, naive_utcnow


class ParagraphMetric(Base):
    """
    段落指标表（原始计数与充分统计量）

    每行对应一个真实段落（paragraphs 为唯一事实源），
    章节/全书汇总必须从本表分子分母聚合，禁止平均段落密度。
    """

    __tablename__ = "paragraph_metrics"
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
        {"comment": "段落指标表：原始计数与充分统计量（分子/分母），密度一律查询时计算，禁止平均段落密度"},
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="所属分析运行")
    paragraph_id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="所属段落编号")
    # 分母与基础计数
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="token 数（分母）")
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="字符数（分母）")

    # 句长充分统计量（count / sum / sum_sq）
    sentence_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="句数")
    sentence_char_sum: Mapped[float] = mapped_column(Float, nullable=False, comment="句长字符和")
    sentence_char_sum_sq: Mapped[float] = mapped_column(Float, nullable=False, comment="句长字符平方和")

    # 情绪/战斗分子（权重命中）
    positive_weight_sum: Mapped[float] = mapped_column(Float, nullable=False, comment="正向情绪权重命中和")
    negative_weight_sum: Mapped[float] = mapped_column(Float, nullable=False, comment="负向情绪权重命中和")
    fight_weight_sum: Mapped[float] = mapped_column(Float, nullable=False, comment="战斗权重命中和")

    # 标点与对话计数
    exclaim_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="感叹号数")
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="问号数")
    pause_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="停顿标点数")
    dialogue_char_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="对话字符数")

    # 感官/意象/修辞计数
    sensory_hit_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="感官词命中数")
    imagery_hit_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="意象词命中数")
    metaphor_sentence_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="比喻句数")
    # 2026-09-05 C 批：身体反应转喻命中（皱眉/颤抖等；独立计数不进正负极性）
    body_reaction_hit_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="身体反应转喻命中数（不进正负极性）"
    )

    # 功能词与语义类别计数（只保存计数，不保存密度）
    function_word_counts: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="功能词计数（不存密度）")
    semantic_category_counts: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="语义类别计数（不存密度）")

    # 表层张力（run 内稳健标准化 + sigmoid），由计算阶段统一填充
    surface_tension_z: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="表层张力 z 分数（run 内 MAD 稳健标准化）",
    )
    surface_tension: Mapped[float | None] = mapped_column(Float, nullable=True, comment="表层张力（sigmoid(z)）")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )

    def __repr__(self) -> str:
        return f"<ParagraphMetric(run_id={self.run_id}, paragraph_id={self.paragraph_id})>"
