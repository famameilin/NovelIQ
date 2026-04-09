"""
WebSocket 流式消息模型。

创建时间: 2026-04-07
创建者: TraeAI
任务: 实现 WebSocket 流式消息模型
说明: 定义流式消息类型枚举及相关数据模型，用于任务执行过程中的实时状态推送

修改时间: 2026-04-09
修改者: GLM-5
任务: refactor/sse-unified-event-bus
修改内容: StreamMessageType 迁移到 events.py，此文件仅保留 StreamMessage 模型
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.api.models.events import StreamMessageType


class StreamMessage(BaseModel):
    """
    流式消息模型

    说明: WebSocket 推送的统一消息格式
    """

    type: StreamMessageType = Field(description="消息类型")
    task_id: str = Field(description="任务 ID")
    data: dict[str, Any] = Field(default_factory=dict, description="消息数据载荷")
    timestamp: datetime = Field(default_factory=datetime.now, description="消息时间戳")
