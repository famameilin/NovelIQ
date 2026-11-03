"""语言结构的词元、情绪观测、实体候选和短语区间

情绪持有者引用同运行同段词元，词面按原文区间读取"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base, naive_utcnow

#: 关系码命名空间前缀：依存（dep:）与语义依存（sdp:）
ARC_RELATION_PREFIXES = ("dep:", "sdp:")


class LinguisticSpan(Base):
    "原文区间标注表（词元 / NER / 短语三种有限形状互斥）"

    __tablename__ = "paragraph_spans"
    __table_args__ = (
        CheckConstraint("start_char < end_char", name="ck_linguistic_spans_char_order"),
        CheckConstraint(
            "(token_index IS NOT NULL)::int + (raw_entity_type IS NOT NULL)::int "
            "+ (phrase_match_kind IS NOT NULL)::int = 1",
            name="ck_linguistic_spans_exactly_one_shape",
        ),
        CheckConstraint("(token_index IS NULL) = (raw_pos IS NULL)", name="ck_linguistic_spans_pos_with_token"),
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE",
            name="linguistic_spans_paragraph_fkey",
        ),
        UniqueConstraint(
            "run_id", "paragraph_id", "token_index", name="uq_linguistic_spans_token_index",
        ),
        ForeignKeyConstraint(
            ["run_id", "paragraph_id", "emotion_holder_token_index"],
            ["paragraph_spans.run_id", "paragraph_spans.paragraph_id", "paragraph_spans.token_index"],
            deferrable=True,
            initially="DEFERRED",
            name="linguistic_spans_emotion_holder_fkey",
        ),
        CheckConstraint(
            "(emotion_polarity IS NULL AND emotion_negated IS NULL AND emotion_holder_token_index IS NULL) OR "
            "(token_index IS NOT NULL AND emotion_polarity IS NOT NULL "
            "AND emotion_polarity IN ('positive', 'negative') AND emotion_negated IS NOT NULL)",
            name="ck_linguistic_spans_emotion_observation",
        ),
        CheckConstraint("token_index IS NULL OR token_index >= 0", name="ck_linguistic_spans_token_nonneg"),
        Index(
            "uq_linguistic_spans_token_start",
            "run_id",
            "paragraph_id",
            "start_char",
            unique=True,
            postgresql_where=sql_text("token_index IS NOT NULL"),
        ),
        Index(
            "uq_linguistic_spans_token_end",
            "run_id",
            "paragraph_id",
            "end_char",
            unique=True,
            postgresql_where=sql_text("token_index IS NOT NULL"),
        ),
        Index(
            "uq_linguistic_spans_ner",
            "run_id",
            "paragraph_id",
            "start_char",
            "end_char",
            "raw_entity_type",
            unique=True,
            postgresql_where=sql_text("raw_entity_type IS NOT NULL"),
        ),
        Index(
            "uq_linguistic_spans_phrase",
            "run_id",
            "paragraph_id",
            "start_char",
            "end_char",
            "phrase_match_kind",
            unique=True,
            postgresql_where=sql_text("phrase_match_kind IS NOT NULL"),
        ),
        Index("idx_linguistic_spans_run_para_start", "run_id", "paragraph_id", "start_char"),
        Index(
            "idx_linguistic_spans_emotion", "run_id", "paragraph_id", "token_index",
            postgresql_where=sql_text("emotion_polarity IS NOT NULL"),
        ),
        {"comment": "原文区间标注表：词元/NER/短语三类互斥形状（词面与归一类型读取投影）"},
    )

    span_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="区间标注主键（uuid）", default=new_id, autoincrement=False
    )
    run_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, comment="所属分析运行")
    paragraph_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="所属段落编号")
    start_char: Mapped[int] = mapped_column(Integer, nullable=False, comment="段内起始字符偏移")
    end_char: Mapped[int] = mapped_column(Integer, nullable=False, comment="段内结束字符偏移")
    token_index: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="词元序号（0 起；词元分支）")
    raw_pos: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="LTP 原始 POS 标签（词元分支）")
    emotion_polarity: Mapped[str | None] = mapped_column(String(8), nullable=True, comment="情绪谓词极性")
    emotion_negated: Mapped[bool | None] = mapped_column(Boolean, nullable=True, comment="情绪谓词的语义否定观测")
    emotion_holder_token_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="同段持有者词元序号（0 起）"
    )
    raw_entity_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="LTP 原始实体类型（NER 分支）"
    )
    phrase_match_kind: Mapped[str | None] = mapped_column(String(30), nullable=True, comment="短语匹配方式（短语分支）")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow, comment="创建时间")

    def __repr__(self) -> str:
        return f"<LinguisticSpan(span_id={self.span_id}, run_id={self.run_id}, paragraph_id={self.paragraph_id})>"


class LinguisticArc(Base):
    "依存/语义依存的有序词元弧"

    __tablename__ = "paragraph_arcs"
    __table_args__ = (
        CheckConstraint(
            "relation_code LIKE 'dep:%' OR relation_code LIKE 'sdp:%'",
            name="ck_linguistic_arcs_namespace",
        ),
        Index(
            "uq_linguistic_arcs_dep_dependent",
            "dependent_span_id",
            unique=True,
            postgresql_where=sql_text("relation_code LIKE 'dep:%'"),
        ),
        Index(
            "uq_linguistic_arcs_sdp_arc",
            "dependent_span_id",
            "head_span_id",
            "relation_code",
            unique=True,
            postgresql_where=sql_text("relation_code LIKE 'sdp:%'"),
        ),
        Index("idx_linguistic_arcs_dependent", "dependent_span_id"),
        Index("idx_linguistic_arcs_head", "head_span_id"),
        {"comment": "词元弧表：依存（dep）与语义依存（sdp）有序弧（端点外键指向词元区间）"},
    )

    arc_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="弧主键（uuid）", default=new_id, autoincrement=False
    )
    dependent_span_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("paragraph_spans.span_id", ondelete="CASCADE", name="linguistic_arcs_dependent_fkey"),
        nullable=False,
        comment="依存词元区间 id",
    )
    head_span_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("paragraph_spans.span_id", ondelete="CASCADE", name="linguistic_arcs_head_fkey"),
        nullable=True,
        comment="中心词元区间 id（dep ROOT 为空）",
    )
    relation_code: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="带命名空间的关系码（dep:SBV/sdp:AGT）"
    )
    source_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, comment="段落内该层真实源顺序（0 起）")

    def __repr__(self) -> str:
        return f"<LinguisticArc(arc_id={self.arc_id}, code={self.relation_code})>"
