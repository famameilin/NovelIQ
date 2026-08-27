"""
章节表 ORM 模型

存储解析出的完整章节目录（含部/卷/番外等层级与空正文条目）。

2026-08-14 M9a-2：chunks 表合并进本表——text/char_offset/char_end_offset
为正文切片列（trimmed 边界，段落 global 坐标的基准）；"chunk" 概念自此
只存在于 agent 运行时（章节正文运行时切子块，负 ID 不落库）。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Chapter(Base):
    """章节表：章节结构解析的持久化结果"""

    __tablename__ = "chapters"

    chapter_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    display_title: Mapped[str] = mapped_column(Text, nullable=False)
    display_index_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    start_pos: Mapped[int] = mapped_column(Integer, nullable=False)
    end_pos: Mapped[int] = mapped_column(Integer, nullable=False)
    # ---- 2026-08-14 M9a-2：正文切片列（原 chunks 表列，空正文章节为 NULL）----
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    char_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, primary_key=True
    )

    __table_args__ = (
        Index("idx_chapters_run_id", "run_id"),
        # 正文检索：keyword 检索与段落边界查询按 trimmed 正文切片定位
        Index(
            "idx_chapters_run_text_trgm",
            sql_text("lower(text) gin_trgm_ops"),
            postgresql_using="gin",
        ),
    )

    def __repr__(self) -> str:
        return f"<Chapter(chapter_id={self.chapter_id}, run_id={self.run_id})>"
