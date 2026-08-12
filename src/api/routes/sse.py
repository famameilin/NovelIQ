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
    last_seq = _resolve_last_seq(request)
    queue = await event_manager.connect(task_id, last_seq=last_seq)

    async def event_generator() -> Any:
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await queue.get()
                event_type = message.get("type", "message")
                data = message.get("data", {})
                seq = message.get("seq", 0)

                yield {
                    "event": event_type,
                    "id": str(seq),
                    "data": json.dumps(data, ensure_ascii=False),
                }
        except asyncio.CancelledError:
            raise
        finally:
            await event_manager.disconnect(task_id, queue)

    return EventSourceResponse(event_generator())


def _resolve_last_seq(request: Request) -> int | None:
    """
    从查询参数 last_seq 或浏览器原生重连自动携带的 Last-Event-ID 头解析起始序号

    契约: 取首个合法非负 int；两者都缺失或非法时返回 None（回放全部缓冲）
    """
    for raw in (
        request.query_params.get("last_seq"),
        request.headers.get("last-event-id"),
    ):
        if raw is None:
            continue
        try:
            seq = int(raw)
        except (TypeError, ValueError):
            continue
        if seq >= 0:
            return seq
    return None
