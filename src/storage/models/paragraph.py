"""
段落事实源表 ORM 模型定义

paragraphs 是全文唯一的段落事实源：
段落单元（ParagraphSpan）无条件落库，Embedding、指标、主题、检索等派生数据
不得自行重新切段。paragraph_id 是 run 内按全文顺序生成的稠密整数（0, 1, 2, ...），
不随数据库自增推断。

段落行只保留身份、来源与不可推导的章内起点；local_end_char、global 坐标、
char_count 均为读取投影。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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

from .base import Base, naive_utcnow

# 注：sql_text 为 sqlalchemy.text 别名——__table_args__ 直接引用 text 会解析到 Paragraph.text 列对象


class Paragraph(Base):
    """
    段落事实源表

    存储 run 内全部段落单元的身份、来源、章内起点与文本内容：
    - local_start_char 相对所属 chunk 的 strip 后文本；终点由长度投影
    - global 坐标相对 run 级规范化全文（= 所属 chapters.char_offset + local 偏移）
    - 正文长度不落列，读取时由字符长度表达式得到
    """

    __tablename__ = "paragraphs"
    __table_args__ = (
        UniqueConstraint("run_id", "chapter_id", "paragraph_index", name="uq_paragraphs_run_chapter_index"),
        UniqueConstraint(
            "run_id", "chapter_id", "source_paragraph_index", "fragment_index",
            name="uq_paragraphs_run_chapter_source_fragment",
        ),
        UniqueConstraint("run_id", "chapter_id", "local_start_char", name="uq_paragraphs_run_chapter_local_start"),
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
        Index("idx_paragraphs_run_chapter_index", "run_id", "chapter_id", "paragraph_index"),
        Index("idx_paragraphs_run_chapter_local_start", "run_id", "chapter_id", "local_start_char"),
        # keyword 检索按 lower(text) LIKE '%kw%' 定位，索引必须建在同一表达式上
        Index(
            "idx_paragraphs_text_trgm",
            sql_text("lower(text) gin_trgm_ops"),
            postgresql_using="gin",
        ),
        {"comment": "段落事实源表：全文唯一段落单元的身份、章内起点与原文，派生数据不得重新切段"},
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="所属分析运行")
    paragraph_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, comment="段落编号（run 内全文顺序稠密整数，0 起）"
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="所属章节编号")
    paragraph_index: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="章内段落顺序号（0 起，章内唯一连续）",
    )
    source_paragraph_index: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="来源自然段章内序号（0 起，拆分片段共享）",
    )
    fragment_index: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="超长自然段拆分片段序号（0 起，未拆分恒为 0）",
    )
    local_start_char: Mapped[int] = mapped_column(Integer, nullable=False, comment="章内切片局部起始字符偏移")
    text: Mapped[str] = mapped_column(Text, nullable=False, comment="段落原文")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )

    def __repr__(self) -> str:
        return f"<Paragraph(run_id={self.run_id}, paragraph_id={self.paragraph_id})>"
