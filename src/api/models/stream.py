"""
WebSocket 流式消息模型。

创建时间: 2026-04-07
创建者: TraeAI
任务: 实现 WebSocket 流式消息模型
说明: 定义流式消息类型枚举及相关数据模型，用于任务执行过程中的实时状态推送
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class StreamMessageType(StrEnum):
    """流式消息类型枚举"""

    stage_start = "stage_start"
    stage_progress = "stage_progress"
    stage_complete = "stage_complete"
    llm_output = "llm_output"
    llm_thinking = "llm_thinking"
    task_complete = "task_complete"
    task_error = "task_error"
    task_cancelled = "task_cancelled"


class ProgressDetail(BaseModel):
    """
    进度详情模型

    说明: 用于描述任务执行过程中的进度信息

    新增字段:
        phase: str - 当前 phase 名称（如 "phase1", "phase2", "phase3", "phase4"）
                 用于在 annotate 阶段内细分进度
    """

    stage: str = Field(description="当前阶段名称")
    sub_stage: str = Field(description="子阶段名称/phase名称")
    phase: str = Field(default="", description="当前执行的phase（如 phase1/phase2/phase3/phase4）")
    current: int = Field(ge=0, description="当前进度值")
    total: int = Field(ge=0, description="总进度值")
    percent: float = Field(ge=0, le=100, description="完成百分比")
    message: str = Field(description="进度描述信息")


class LLMOutputData(BaseModel):
    """
    LLM 输出数据模型

    说明: 用于封装 LLM 生成过程中的输出数据
    """

    phase: str = Field(description="生成阶段标识")
    chunk_id: int = Field(ge=0, description="数据块 ID")
    content: str = Field(description="输出内容")


class StreamMessage(BaseModel):
    """
    流式消息模型

    说明: WebSocket 推送的统一消息格式
    """

    type: StreamMessageType = Field(description="消息类型")
    task_id: str = Field(description="任务 ID")
    data: dict[str, Any] = Field(default_factory=dict, description="消息数据载荷")
    timestamp: datetime = Field(default_factory=datetime.now, description="消息时间戳")
