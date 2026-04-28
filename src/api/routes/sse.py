"""
SSE 路由

说明: SSE 端点用于获取任务进度和 LLM 输出
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request

try:
    from sse_starlette import EventSourceResponse
except ImportError:
    from starlette.responses import EventSourceResponse  # type: ignore[no-redef,attr-defined]

from src.api.services.event_manager import event_manager

router = APIRouter()


@router.get("/events/tasks/{task_id}")
async def sse_endpoint(task_id: str, request: Request) -> EventSourceResponse:
    """SSE 端点：获取任务进度和 LLM 输出"""
    queue = await event_manager.connect(task_id)

    async def event_generator() -> Any:
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await queue.get()
                event_type = message.get("type", "message")
                data = message.get("data", {})

                yield {
                    "event": event_type,
                    "data": json.dumps(data, ensure_ascii=False),
                }
        except asyncio.CancelledError:
            raise
        finally:
            await event_manager.disconnect(task_id, queue)

    return EventSourceResponse(event_generator())
