"""
RAG 相关表 ORM 模型定义

本模块定义 RAG 相关的数据表：
- TokenUsage: Token 使用统计表
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TokenUsage(Base):
    """
    Token 使用统计表

    存储 API 调用的 token 使用统计

    为 novel_id 补充到 novels 表的外键约束，避免 token 记账继续写入 unknown 等脏值
    """

    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("novels.novel_id", ondelete="RESTRICT", name="token_usage_novel_id_fkey"),
        nullable=False,
    )
    chunk_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    call_type: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True
    )

    __table_args__ = (
        Index("idx_token_usage_novel_id", "novel_id"),
        Index("idx_token_usage_task_type", "novel_id", "task_type"),
        Index("idx_token_usage_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<TokenUsage(id={self.id}, novel_id={self.novel_id}, task_type={self.task_type})>"
