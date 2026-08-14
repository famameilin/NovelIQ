"""
章节表 ORM 模型

存储解析出的完整章节目录（含部/卷/番外等层级与空正文条目），
chunks 表通过 chapter_id 引用本表的有正文章节。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text
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
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, primary_key=True
    )

    __table_args__ = (Index("idx_chapters_run_id", "run_id"),)

    def __repr__(self) -> str:
        return f"<Chapter(chapter_id={self.chapter_id}, run_id={self.run_id})>"
