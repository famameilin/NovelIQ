"""
段落事实源表 ORM 模型定义

paragraphs 是全文唯一的段落事实源（设计文档《章节粒度分析指标重设计》§5.1）：
段落单元（ParagraphSpan）无条件落库，Embedding、指标、主题、检索等派生数据
不得自行重新切段。paragraph_id 是 run 内按全文顺序生成的稠密整数（0, 1, 2, ...），
不随数据库自增推断。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

# 注：sql_text 为 sqlalchemy.text 的别名——本模块存在 Paragraph.text 列属性，
# 类体内 __table_args__ 直接引用 text 会解析到列对象而非函数（与 章节.py 同口径）


def _utcnow() -> datetime:
    """created_at 默认值：UTC 带时区当前时间（避免模块导入期求值）"""
    return datetime.now(UTC)


class Paragraph(Base):
    """
    段落事实源表

    存储 run 内全部段落单元的身份、来源、字符坐标与文本内容：
    - local_* 坐标相对所属 chunk 的 strip 后文本
    - global_* 坐标相对 run 级规范化全文（= chunk 全文偏移 + local 偏移）
    - char_count 恒等于 length(text) 与 global_end_char - global_start_char
    """

    __tablename__ = "paragraphs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paragraph_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # 章内段落顺序号（0 起），同一章内唯一且连续
    paragraph_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # 来源自然段在 章节 内的序号（0 起）；超长自然段拆出的片段共享该值
    source_paragraph_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # 超长自然段被拆分后的片段序号（0 起）；未拆分的自然段恒为 0
    fragment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    local_start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    local_end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    global_start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    global_end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256 hex，供派生数据校验段落内容未变
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    splitter_version: Mapped[str] = mapped_column(String, nullable=False)
    tokenizer_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id", "chapter_id", "paragraph_index", name="uq_paragraphs_run_chapter_index"
        ),
        ForeignKeyConstraint(
            ["chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("local_start_char < local_end_char", name="ck_paragraphs_local_order"),
        CheckConstraint("global_start_char < global_end_char", name="ck_paragraphs_global_order"),
        CheckConstraint(
            "char_count = global_end_char - global_start_char",
            name="ck_paragraphs_char_count_global",
        ),
        CheckConstraint("char_count = length(text)", name="ck_paragraphs_char_count_text"),
        Index("idx_paragraphs_run_chapter_index", "run_id", "chapter_id", "paragraph_index"),
        Index("idx_paragraphs_run_global_start", "run_id", "global_start_char"),
        Index("idx_paragraphs_run_chapter_local_start", "run_id", "chapter_id", "local_start_char"),
        # 2026-08-14 二期段落化：keyword_ops 直接扫 paragraphs 表的查询是
        # lower(text) LIKE '%kw%'，索引必须建在同一个表达式上（lower(text) gin_trgm_ops），
        # 裸 text 列上的 trgm 索引无法被规划器命中，等于死索引（与 chunks 的
        # idx_chunks_text_trgm 同口径；pg_trgm 扩展由 init_db 按需创建）
        Index(
            "idx_paragraphs_text_trgm",
            sql_text("lower(text) gin_trgm_ops"),
            postgresql_using="gin",
        ),
    )

    def __repr__(self) -> str:
        return f"<Paragraph(run_id={self.run_id}, paragraph_id={self.paragraph_id})>"
