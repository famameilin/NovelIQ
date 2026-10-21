"""
SSE 路由

SSE 端点用于获取任务状态和模型输出
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from src.sse.manager import event_manager
from src.storage import get_storage_factory

router = APIRouter()


def _task_run_belongs_to_novel(task_id: str, novel_id: str) -> dict[str, Any] | None:
    """
    校验 SSE 目标任务存在且属于当前小说

    按 run_id 前缀解析（与 /status 等路由同口径），防止对任意/编造的 task_id
    建立 SSE 订阅并产生 event_manager 条目；任务不存在或不属于该小说直接 404。
    """
    try:
        session_factory = get_storage_factory()
        session = session_factory()
        run = session.runs.get_run_by_task_id(task_id)
        return run if run is not None and run.get("novel_id") == novel_id else None
    except Exception:
        return None


@router.get("/novels/{novel_id}/events/tasks/{task_id}")
async def sse_endpoint(novel_id: str, task_id: str, request: Request) -> EventSourceResponse:
    """SSE 端点：获取任务状态和模型输出"""
    run = _task_run_belongs_to_novel(task_id, novel_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在或不属于该小说")
    consumer = getattr(request.app.state, "notifications", None)
    if consumer is not None:
        await consumer.watch(run["run_id"], task_id, terminal=run["status"] in {"completed", "failed", "cancelled"})
    queue, snapshot = await event_manager.connect_snapshot(task_id)
    snapshot["task_id"] = task_id
    consumer = getattr(request.app.state, "notifications", None)
    snapshot["sync_pending"] = bool(consumer and consumer.pending(task_id))

    async def event_generator() -> Any:
        cursor = int(snapshot["cursor"])
        last_sync = None
        try:
            yield {"event": "snapshot", "id": str(cursor), "data": json.dumps(snapshot, ensure_ascii=False)}
            while True:
                consumer = getattr(request.app.state, "notifications", None)
                warning = consumer.errors.get(task_id) if consumer is not None else None
                sync_pending = bool((consumer and consumer.pending(task_id)) or not queue.empty())
                sync = (warning, sync_pending)
                if sync != last_sync:
                    yield {"event": "notification_status", "data": json.dumps(
                        {"task_id": task_id, "warning": warning, "sync_pending": sync_pending}, ensure_ascii=False
                    )}
                    last_sync = sync
                if await request.is_disconnected():
                    break
                if not queue.empty():
                    pending = queue.get_nowait()
                    if pending.get("type") == "reconnect_required":
                        yield {"event": "reconnect_required", "data": json.dumps(pending["data"])}
                        break
                    if int(pending.get("seq", 0)) > cursor:
                        cursor = int(pending["seq"])
                        yield {
                            "event": pending["type"],
                            "id": str(cursor),
                            "data": json.dumps(pending["data"], ensure_ascii=False),
                        }
                    continue
                messages = await event_manager.replay(task_id, cursor)
                for message in messages:
                    sequence = int(message["seq"])
                    if sequence <= cursor:
                        continue
                    cursor = sequence
                    yield {
                        "event": message["type"],
                        "id": str(cursor),
                        "data": json.dumps(message["data"], ensure_ascii=False),
                    }
                if messages:
                    continue
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=0.5)
                except TimeoutError:
                    continue
                if message.get("type") == "reconnect_required":
                    yield {"event": "reconnect_required", "data": json.dumps(message["data"])}
                    break
                if 0 < int(message.get("seq", 0)) <= cursor:
                    continue
                cursor = max(cursor, int(message.get("seq", 0)))
                event_type = message.get("type", "message")
                data = message.get("data", {})
                seq = message.get("seq", 0)
                yield {"event": event_type, "id": str(seq), "data": json.dumps(data, ensure_ascii=False)}
        except asyncio.CancelledError:
            raise
        finally:
            await event_manager.disconnect(task_id, queue)
            if consumer is not None:
                consumer.unwatch(task_id)

    return EventSourceResponse(event_generator())


def _resolve_last_seq(request: Request) -> int | None:
    """
    从浏览器 Last-Event-ID 头或查询参数 last_seq 解析起始序号

    头优先；取首个合法非负 int，两者都缺失或非法时返回 None（回放全部缓冲）
    """
    for raw in (request.headers.get("last-event-id"), request.query_params.get("last_seq")):
        if raw is None:
            continue
        try:
            seq = int(raw)
        except (TypeError, ValueError):
            continue
        if seq >= 0:
            return seq
    return None
