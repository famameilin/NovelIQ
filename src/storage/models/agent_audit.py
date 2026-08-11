"""
Agent 审计三表 ORM 模型定义

说明: agent_invocations / agent_turns / agent_tool_calls 是 Annotation 与 Diagnosis
共用的新审计结构。每次审计写入使用独立短事务即时提交，
不随候选状态或最终标注事务回滚；审计写入失败时直接终止 Agent，不静默忽略。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from .base import Base


class AgentInvocation(Base):
    """2026-08-10 用于表示一次 Annotation/Diagnosis 尝试的审计行"""

    __tablename__ = "agent_invocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_type: Mapped[str] = mapped_column(String(20), nullable=False)  # annotation / diagnosis
    chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)  # local / cloud
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success / error
    final_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_agent_invocations_run_task", "run_id", "task_type"),
    )


class AgentTurn(Base):
    """2026-08-10 用于保存每次模型请求、原始响应、上下文摘要与逐回合计时"""

    __tablename__ = "agent_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invocation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("agent_invocations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    context_summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_messages: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    timing_notes: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_visible_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_wall_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    turn_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_agent_turns_invocation_index", "invocation_id", "turn_index"),
    )


class AgentToolCall(Base):
    """2026-08-10 用于保存每个工具的完整参数、完整结果、模型回执、独立状态和耗时"""

    __tablename__ = "agent_tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    turn_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("agent_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    call_index: Mapped[int] = mapped_column(Integer, nullable=False)
    request_args: Mapped[dict] = mapped_column(JSONB, nullable=False)
    response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    receipt: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_agent_tool_calls_turn", "turn_id", "call_index"),
    )


__all__ = ["AgentInvocation", "AgentToolCall", "AgentTurn"]
