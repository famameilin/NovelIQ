"""
RAG 相关表 ORM 模型定义

本模块定义 RAG 相关的数据表：
- TokenUsage: Token 使用统计表
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TokenUsage(Base):
    """
    Token 使用统计表

    存储 API 调用的 token 使用统计

    - Agent 回合行与 agent_turns.id 一对一（agent_turn_id 唯一），
      增加 reasoning/cache/cost 字段
    - embedding 等非 Agent 行 agent_turn_id 为 NULL，仍按 task_type/call_type 归桶
    """

    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("novels.novel_id", ondelete="RESTRICT", name="token_usage_novel_id_fkey"),
        nullable=False,
    )
    chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    call_type: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    accounting_source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="reported"
    )
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True
    )
    agent_turn_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("agent_turns.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )

    __table_args__ = (
        Index("idx_token_usage_novel_id", "novel_id"),
        Index("idx_token_usage_task_type", "novel_id", "task_type"),
        Index("idx_token_usage_run_id", "run_id"),
        Index("idx_token_usage_agent_turn", "agent_turn_id"),
    )

    def __repr__(self) -> str:
        return f"<TokenUsage(id={self.id}, novel_id={self.novel_id}, task_type={self.task_type})>"
