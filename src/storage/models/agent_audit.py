"""模型回合台账 ORM 模型定义（Agent 审计与 token 计账统一落点）

2026-10-06 表合并：agent_invocations / agent_turns / audit_messages / token_usage
四表收敛为 model_turns 一张回合级台账——
- invocation 上下文（execution_id/attempt_number/chapter/work/role）反规范化到每个回合行；
- token 计账列内联在回合行上（原 token_usage 与 agent_turns 一对一，非 Agent 调用如
  embedding 以 execution_id 为空的行同表记账）；
- 原 audit_messages 回执表的幂等职责由 message_key 唯一列承担（每条审计消息自带唯一 id）。
每次审计写入使用独立短事务即时提交，不随候选状态或最终标注事务回滚；
审计写入失败时直接终止 Agent，不静默忽略。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ModelTurn(Base):
    """一行 = 一次模型调用：Agent 回合（execution_id 非空）或非 Agent 记账行"""

    __tablename__ = "model_turns"
    __table_args__ = (
        Index("idx_model_turns_run", "run_id"),
        Index("idx_model_turns_task_type", "run_id", "task_type"),
        Index("idx_model_turns_execution", "execution_id"),
        CheckConstraint(
            "row_kind IN ('agent_turn', 'usage', 'attempt_error')", name="ck_model_turns_row_kind"
        ),
        {"comment": "模型回合台账：Agent 回合（含 invocation 上下文与 token 计账）与非 Agent 模型调用统一记账"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        comment="所属分析运行",
    )
    # task_type: annotation/diagnosis/embedding；call_type: agent/diagnosis/local
    task_type: Mapped[str] = mapped_column(String(100), nullable=False, comment="任务类型")
    call_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="调用类型")
    model: Mapped[str] = mapped_column(String(100), nullable=False, comment="模型名")
    model_provider: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="模型提供方（local/cloud）")
    # Agent 上下文（非 Agent 记账行为空）
    execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="agent 执行身份（一次尝试）")
    attempt_number: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="第几次尝试（1 起）")
    chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="章节编号")
    work_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="关联标注工作")
    role: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="章内角色")
    turn_index: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="回合序号（执行内 1 起）")
    # 回合事实
    row_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="agent_turn", server_default="agent_turn",
        comment="行种类（agent_turn=Agent 回合/usage=非Agent记账/attempt_error=尝试派发失败行）",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running", server_default="running",
        comment="状态（running/success/error/interrupted）",
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="回合错误信息（派发行存最终错误）")
    raw_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="模型原始响应")
    context_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="上下文摘要")
    request_messages: Mapped[list | None] = mapped_column(JSONB, nullable=True, comment="请求消息列表")
    timing_notes: Mapped[list | None] = mapped_column(JSONB, nullable=True, comment="计时明细备注")
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="首 token 时间（毫秒）")
    first_visible_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="首个可见内容时间（毫秒）")
    reasoning_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="推理耗时（毫秒）")
    model_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="模型生成耗时（毫秒）")
    tool_wall_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="工具执行墙钟（毫秒）")
    turn_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="回合总耗时（毫秒）")
    # token 计账（原 token_usage 列）
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="输入 token 数")
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="输出 token 数")
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="总 token 数")
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="缓存读取 token 数")
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="推理 token 数")
    cost: Mapped[float | None] = mapped_column(Float, nullable=True, comment="成本")
    accounting_source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="reported", comment="计账来源（reported=服务商回执）"
    )
    # 幂等键：产生本行的审计消息 id（派发行/非 Agent 行同样携带），跨重启重放据此去重
    message_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True, comment="审计消息幂等键")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="结束时间")


class AgentToolCall(Base):
    """2026-08-10 用于保存每个工具的完整参数、完整结果、模型回执、独立状态和耗时"""

    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        Index("idx_agent_tool_calls_turn", "turn_id", "call_index"),
        {"comment": "Agent 工具调用审计表：每个工具调用一行，保存完整参数、结果、模型回执与耗时"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    turn_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("model_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属回合",
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="工具名")
    call_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="回合内调用序号")
    request_args: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="解析后的调用参数")
    raw_args: Mapped[str | None] = mapped_column(Text, nullable=True, comment="模型原始参数文本")
    response: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="工具执行结果")
    receipt: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="写入回执")
    status: Mapped[str] = mapped_column(String(20), nullable=False, comment="调用状态")
    error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="调用错误信息")
    tool_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="工具耗时（毫秒）")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="开始时间")
    message_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True, comment="审计消息幂等键")


__all__ = ["AgentToolCall", "ModelTurn"]
