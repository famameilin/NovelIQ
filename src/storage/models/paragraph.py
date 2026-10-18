"段落事实源表 ORM 模型定义"

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Integer, Text, UniqueConstraint
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base, naive_utcnow

# 注：sql_text 为 sqlalchemy.text 的别名——本模块存在 Paragraph.text 列属性，
# 类体内 __table_args__ 直接引用 text 会解析到列对象而非函数（与 章节.py 同口径）


class Paragraph(Base):
    "段落事实源表"

    __tablename__ = "paragraphs"
    __table_args__ = (
        UniqueConstraint("run_id", "paragraph_id", name="uq_paragraphs_business_key"),
        UniqueConstraint("run_id", "chapter_id", "paragraph_index", name="uq_paragraphs_run_chapter_index"),
        UniqueConstraint(
            "run_id",
            "chapter_id",
            "source_paragraph_index",
            "fragment_index",
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

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=new_id, autoincrement=False, comment="UUIDv7 独立主键"
    )
    run_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), comment="所属分析运行", nullable=False)
    paragraph_id: Mapped[int] = mapped_column(
        Integer, comment="段落编号（run 内全文顺序稠密整数，0 起）", nullable=False
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="所属章节编号")
    # 章内段落顺序号（0 起），同一章内唯一且连续
    paragraph_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="章内段落顺序号（0 起，章内唯一连续）",
    )
    # 来源自然段在章节内的序号（0 起）；超长自然段拆出的片段共享该值
    source_paragraph_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="来源自然段章内序号（0 起，拆分片段共享）",
    )
    # 超长自然段被拆分后的片段序号（0 起）；未拆分的自然段恒为 0
    fragment_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="超长自然段拆分片段序号（0 起，未拆分恒为 0）",
    )
    local_start_char: Mapped[int] = mapped_column(Integer, nullable=False, comment="章内切片局部起始字符偏移")
    text: Mapped[str] = mapped_column(Text, nullable=False, comment="段落原文")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow, comment="创建时间")

    def __repr__(self) -> str:
        return f"<Paragraph(run_id={self.run_id}, paragraph_id={self.paragraph_id})>"
