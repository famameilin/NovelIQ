"""
WebSocket 路由模块

创建时间: 2026-04-07
创建者: TraeAI
任务: WebSocket 流式传输与细粒度进度显示
说明: 提供 WebSocket 端点用于实时推送分析进度和 LLM 输出
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from src.api.services.stream_manager import stream_manager

router = APIRouter()


@router.websocket("/ws/tasks/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str) -> None:
    """
    WebSocket 端点，用于实时推送任务进度

    创建时间: 2026-04-07
    创建者: TraeAI
    任务: WebSocket 流式传输与细粒度进度显示
    说明: 客户端连接后，接收该任务的所有进度更新和 LLM 输出
    """
    await websocket.accept()
    await stream_manager.connect(websocket, task_id)
    logger.info(f"WebSocket connected for task: {task_id}")

    try:
        while True:
            data = await websocket.receive_text()
            logger.debug(f"WebSocket received from task {task_id}: {data}")
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await stream_manager.disconnect(websocket)
        logger.info(f"WebSocket disconnected for task: {task_id}")
    except Exception as e:
        logger.error(f"WebSocket error for task {task_id}: {e}")
        await stream_manager.disconnect(websocket)
