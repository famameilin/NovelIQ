"""统一展示事件契约

展示消息由 pipeline 各层（workflows/agents/chunking）产生，API 层只按单向调用接收；
SSE 事件名映射与发送入口留在 src/api/models/events.py
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

# SSE 事件类型


class StreamMessageType(StrEnum):
    """流式消息类型枚举（SSE 线上事件名）"""

    llm_output = "llm_output"
    llm_thinking = "llm_thinking"
    tool_call = "tool_call"
    task_complete = "task_complete"
    task_error = "task_error"
    task_cancelled = "task_cancelled"


# 统一事件格式

StreamEventAction = Literal[
    "start", "progress", "complete", "output", "thinking", "tool_call", "work_reset", "work_saved", "chapter_reset"
]
"""StreamEvent.action 的合法值"""


@dataclass
class StreamEvent:
    """
    统一 SSE 事件格式

    所有层发送的事件都使用此格式，只是字段填充不同
    Event Bus 会自动补全缺失的上下文字段

    action 语义:
        start    — 阶段/phase/chunk 开始
        progress — 增量进度
        complete — 阶段/phase/chunk 完成
        output   — LLM 正式输出
        thinking — LLM 思考过程输出
    """

    action: StreamEventAction  # 开始 / 进度 / 完成 / 输出 / 思考 / 工具调用
    stage: str = ""
    sub_stage: str = ""
    chapter_id: int | None = None
    # 展示作用域取实际阶段作用域（stage:chapter:sub_stage，标注=章+角色、诊断=案例锚），
    # invocation_id 是判定“当前在编执行”的唯一依据
    invocation_id: str | None = None
    message_id: str | None = None
    stream_id: str | None = None
    current: int | None = None
    total: int | None = None
    percent: float | None = None  # 全局进度（stage 级别）
    sub_percent: float | None = None  # 子阶段进度（如 Agent 单章节内的领域写入进度）
    content: str = ""
    message: str = ""
    status: str | None = None  # 工具调用状态（tool_call 事件专用: started/success/failed）

    def to_dict(self) -> dict[str, Any]:
        """序列化统一 SSE 事件；LLM 事件必须携带流标识"""
        if self.action in {"output", "thinking", "tool_call"} and not self.stream_id:
            raise ValueError("LLM 流事件缺少 stream_id")
        return {
            "action": self.action,
            "stage": self.stage,
            "sub_stage": self.sub_stage,
            "chapter_id": self.chapter_id or 0,
            "stream_id": self.stream_id,
            "invocation_id": self.invocation_id,
            "message_id": self.message_id,
            "current": self.current or 0,
            "total": self.total or 0,
            "percent": self.percent or 0.0,
            "sub_percent": self.sub_percent or 0.0,
            "content": self.content,
            "message": self.message,
            "status": self.status or "",
            **({"event_type": "work_saved"} if self.action == "work_saved" else {}),
        }
