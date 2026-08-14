"""
SSE 路由

说明: SSE 端点用于获取任务进度和 LLM 输出
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

try:
    from sse_starlette import EventSourceResponse
except ImportError:
    from starlette.responses import EventSourceResponse  # type: ignore[no-redef,attr-defined]

from src.api.services.event_manager import event_manager
from src.storage.db import get_session_factory
from src.storage.repositories import RunRepository

router = APIRouter()


def _task_run_exists(task_id: str) -> bool:
    """
    2026-08-14 P2-11：校验 SSE 目标任务存在

    按 run_id 前缀解析（与 /status 等路由同口径），防止对任意/编造的 task_id
    建立 SSE 订阅并产生 event_manager 条目；任务不存在直接 404。
    """
    try:
        session_factory = get_session_factory()
        with session_factory() as session:
            run = RunRepository(session.connection()).get_run_by_run_id_prefix(task_id)
            return run is not None
    except Exception:
        return False


@router.get("/events/tasks/{task_id}")
async def sse_endpoint(task_id: str, request: Request) -> EventSourceResponse:
    """SSE 端点：获取任务进度和 LLM 输出"""
    if not _task_run_exists(task_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
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
    从浏览器 Last-Event-ID 头或查询参数 last_seq 解析起始序号

    契约: 2026-08-14 P1-6 改为「头优先」——浏览器原生自动重连每次都会携带
    Last-Event-ID（始终是最近一条已收事件），而 query 中的 last_seq 是前端
    重建 EventSource 时冻结的旧值，若 query 优先会永远压过原生重连的头，
    导致每次原生重连都重复回放已收事件。取首个合法非负 int；
    两者都缺失或非法时返回 None（回放全部缓冲）
    """
    for raw in (
        request.headers.get("last-event-id"),
        request.query_params.get("last_seq"),
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
