"""
SSE 路由

创建时间: 2026-04-09
创建者: TraeAI
任务: 实现 SSE 路由和事件管理器
说明: SSE 端点用于获取任务进度和 LLM 输出

修改时间: 2026-04-09
修改者: TraeAI
修改内容: 初始版本
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse

from src.api.services.event_manager import event_manager

router = APIRouter()


@router.get("/events/tasks/{task_id}")
async def sse_endpoint(task_id: str, request: Request) -> EventSourceResponse:
    """
    SSE 端点：获取任务进度和 LLM 输出

    创建时间: 2026-04-09
    创建者: TraeAI
    任务: 实现 SSE 路由和事件管理器
    """
    queue = await event_manager.connect(task_id)

    async def event_generator() -> Any:
        try:
            while True:
                message = await queue.get()
                event_type = message.get("type", "message")
                data = message.get("data", {})

                yield {
                    "event": event_type,
                    "data": json.dumps(data, ensure_ascii=False),
                }
        except asyncio.CancelledError:
            await event_manager.disconnect(task_id)
            raise

    return EventSourceResponse(event_generator())
