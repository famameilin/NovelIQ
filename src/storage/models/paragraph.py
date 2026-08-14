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
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


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
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # chunk 内段落顺序号（0 起），同一 chunk 内唯一且连续
    paragraph_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # 来源自然段在 chunk 内的序号（0 起）；超长自然段拆出的片段共享该值
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
            "run_id", "chunk_id", "paragraph_index", name="uq_paragraphs_run_chunk_index"
        ),
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
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
        Index("idx_paragraphs_run_chunk_local_start", "run_id", "chunk_id", "local_start_char"),
    )

    def __repr__(self) -> str:
        return f"<Paragraph(run_id={self.run_id}, paragraph_id={self.paragraph_id})>"
