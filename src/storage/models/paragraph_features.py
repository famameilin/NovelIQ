"""
段落特征结果表 ORM 模型定义

paragraph_features 是封闭种类的段落向量与标量计算结果唯一落点。

feature_code 是封闭数学结果目录，不是任意属性名；三种值列（向量/标量/计数）
恰一适用，不加可由 feature_code 还原的重复 kind/group 列；模型、维度与曲线
参数从分析运行的运行级合同取得。
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, naive_utcnow

#: 语义向量 feature_code
FEATURE_SEMANTIC_VECTOR = "semantic_vector"
#: POS 分组向量 feature_code 前缀（完整代码为 pos_vector:<pos_group>）
FEATURE_POS_VECTOR_PREFIX = "pos_vector:"
#: 表层张力 z 分数 feature_code
FEATURE_TENSION_Z = "tension_z"
#: LOWESS 净密度平滑 feature_code
FEATURE_LOWESS_NET_DENSITY = "lowess_net_density"
#: LOWESS 表面张力平滑 feature_code
FEATURE_LOWESS_SURFACE_TENSION = "lowess_surface_tension"
#: 五个句式分类计数 feature_code（与句数总量分离，保留真实分类零项）
FEATURE_SENTENCE_CODES = (
    "sentence_short",
    "sentence_medium",
    "sentence_long",
    "sentence_compound",
    "sentence_parallel_candidate",
)


class ParagraphFeature(Base):
    """段落特征结果表（每段落、每封闭计算种类一行）"""

    __tablename__ = "paragraph_features"
    __table_args__ = (
        CheckConstraint(
            "(vector_value IS NOT NULL)::int + (scalar_value IS NOT NULL)::int "
            "+ (count_value IS NOT NULL)::int = 1"
            " OR (feature_code LIKE 'pos_vector:%' AND vector_value IS NULL AND scalar_value IS NULL"
            " AND count_value IS NULL AND in_vocabulary_token_count = 0)",
            name="ck_paragraph_features_exactly_one_value",
        ),
        CheckConstraint(
            "in_vocabulary_token_count IS NULL OR feature_code LIKE 'pos_vector:%'",
            name="ck_paragraph_features_in_vocab_only_pos",
        ),
        CheckConstraint("count_value IS NULL OR count_value >= 0", name="ck_paragraph_features_count_nonneg"),
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE",
            name="paragraph_features_paragraph_fkey",
        ),
        Index("idx_paragraph_features_code_paragraph", "run_id", "feature_code", "paragraph_id"),
        {"comment": "段落特征结果表：封闭计算种类（语义/POS 向量、张力 z、LOWESS 平滑、句式计数）"},
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="所属分析运行")
    paragraph_id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="所属段落编号")
    feature_code: Mapped[str] = mapped_column(String(64), primary_key=True, comment="封闭计算种类代码")
    vector_value: Mapped[list[float] | None] = mapped_column(
        Vector(), nullable=True, comment="向量值（语义/POS 向量；列宽按运行模型合同解析）"
    )
    scalar_value: Mapped[float | None] = mapped_column(Float, nullable=True, comment="标量值（张力 z/LOWESS 平滑）")
    count_value: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="计数值（句式分类命中数）")
    in_vocabulary_token_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="POS 向量词表内 token 数（仅 pos_vector 行有值）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="该结果真实产生时间"
    )

    def __repr__(self) -> str:
        return (
            f"<ParagraphFeature(run_id={self.run_id}, paragraph_id={self.paragraph_id}, "
            f"code={self.feature_code})>"
        )
