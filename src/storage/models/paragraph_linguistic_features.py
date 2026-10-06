"""
段落语言结构特征表 ORM 模型定义

paragraph_linguistic_features 每个段落一行保存 LTP 词性/词长/句式/依存
句法基础结果（《分析能力扩展路线图》§5.3）：原始结构数据与可加充分统计量，
不保存章节或全书比例；比例一律查询时计算。

tokens 与 dependency_arcs 固定 JSON 结构，词元区间、词长计数与词性计数
均与 ltp_token_count 守恒。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, naive_utcnow


class ParagraphLinguisticFeature(Base):
    """段落语言结构特征表（每段一行）"""

    __tablename__ = "paragraph_linguistic_features"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE"),
        Index("idx_linguistic_features_run_paragraph", "run_id", "paragraph_id"),
        {"comment": "段落语言结构特征表：LTP 分词/词性/句式/依存/语义弧基础结果（每段一行，只存可加计数）"},
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="所属分析运行")
    paragraph_id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="所属段落编号")
    ltp_token_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="LTP 分词 token 数")
    tokens: Mapped[list] = mapped_column(JSONB, nullable=False, comment="分词 token 列表（固定 JSON 结构）")
    word_length_counts: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="词长计数")
    pos_counts: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="词性计数")
    sentence_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="句数")
    sentence_pattern_counts: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="句式计数")
    dependency_arcs: Mapped[list] = mapped_column(JSONB, nullable=False, comment="依存句法弧列表（固定 JSON 结构）")
    dependency_node_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="依存节点数")
    dependency_root_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="依存根节点数")
    dependency_depth_sum: Mapped[int] = mapped_column(Integer, nullable=False, comment="依存深度和")
    dependency_depth_max: Mapped[int] = mapped_column(Integer, nullable=False, comment="依存最大深度")
    dependency_relation_counts: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="依存关系计数")
    # 2026-09-05 B 批：sdp 语义弧与词典情绪事件（sdp 未运行时为空数组/0）
    sdp_arcs: Mapped[list] = mapped_column(JSONB, nullable=False, comment="sdp 语义依存弧（未运行为空数组）")
    emotion_events: Mapped[list] = mapped_column(JSONB, nullable=False, comment="词典情绪事件列表")
    emotion_event_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="情绪事件总数")
    emotion_pos_event_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="正向情绪事件数")
    emotion_neg_event_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="负向情绪事件数")
    # 词典情绪计数对照（命中集=paragraph_metrics 同源短语匹配；翻转判定不同）
    lexicon_pos_count: Mapped[float] = mapped_column(Float, nullable=False, comment="词典正向计数（对照口径）")
    lexicon_neg_count: Mapped[float] = mapped_column(Float, nullable=False, comment="词典负向计数（对照口径）")
    mneg_pos_count: Mapped[float] = mapped_column(Float, nullable=False, comment="否定翻转后词典正向计数")
    mneg_neg_count: Mapped[float] = mapped_column(Float, nullable=False, comment="否定翻转后词典负向计数")
    # 2026-09-07 句级监督边界打分（按书边界；标签不足或类别单一时为 NULL）
    boundary_pos_score_sum: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="边界打分正向和（标签不足为 NULL）",
    )
    boundary_neg_score_sum: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="边界打分负向和（标签不足为 NULL）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )

    def __repr__(self) -> str:
        return f"<ParagraphLinguisticFeature(run_id={self.run_id}, paragraph_id={self.paragraph_id})>"
