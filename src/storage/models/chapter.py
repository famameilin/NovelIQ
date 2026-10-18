"""
章节与正文表 ORM 模型

chapters 保留完整章节身份与章节原始区域；正文切片与全文起点一对一合并于本表：
text 与 char_offset 同空或同有；正文终点由 char_offset + 字符长度投影，char_end_offset 不落列。
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base

# 注：sql_text 为 sqlalchemy.text 的别名——本模块存在 Chapter.text 列属性，
# __table_args__ 直接引用 text 会解析到列对象而非函数（与既有段落表同口径）


class Chapter(Base):
    "章节表：章节结构解析的持久化结果（目录与正文同键一对一，空正文无切片）"

    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("run_id", "chapter_id", name="uq_chapters_business_key"),
        UniqueConstraint("run_id", "sequence", name="uq_chapters_run_sequence"),
        CheckConstraint("(text IS NULL) = (char_offset IS NULL)", name="ck_chapters_text_offset_pair"),
        ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE", name="chapters_run_fkey"),
        Index("idx_chapters_run_id", "run_id"),
        # 原文检索按 lower(text) LIKE '%kw%' 定位，索引必须建在同一表达式上
        Index(
            "idx_chapters_text_trgm",
            sql_text("lower(text) gin_trgm_ops"),
            postgresql_using="gin",
        ),
        {"comment": "章节表：章节结构解析结果（目录+正文同键一对一），含部/卷/番外层级与空正文条目"},
    )

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=new_id, autoincrement=False, comment="UUIDv7 独立主键"
    )
    run_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), comment="所属分析运行", nullable=False)
    chapter_id: Mapped[int] = mapped_column(Integer, comment="章节编号（run 内）", nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, comment="全书顺序号（run 内唯一）")
    title: Mapped[str] = mapped_column(Text, nullable=False, comment="解析标题")
    display_title: Mapped[str] = mapped_column(Text, nullable=False, comment="前端展示标题（解析器实际结果）")
    display_index_label: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="展示用层级编号标签")
    level: Mapped[str] = mapped_column(String(20), nullable=False, comment="章节层级类型")
    start_pos: Mapped[int] = mapped_column(Integer, nullable=False, comment="章节原始区域全文起始字符位置")
    end_pos: Mapped[int] = mapped_column(Integer, nullable=False, comment="章节原始区域全文结束字符位置")
    text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="正文切片文本（trimmed 边界；空正文 NULL）")
    char_offset: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="正文切片起始全局字符偏移（空正文 NULL）"
    )

    def __repr__(self) -> str:
        return f"<Chapter(chapter_id={self.chapter_id}, run_id={self.run_id})>"
