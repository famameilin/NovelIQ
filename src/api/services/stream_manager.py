"""
WebSocket 连接管理器模块

创建时间: 2026-04-07
创建者: TraeAI
任务: 实现 WebSocket 连接管理器
说明: 管理 WebSocket 连接池，支持按 task_id 分组连接和广播消息

修改时间: 2026-04-07
修改者: TraeAI
修改内容: 将 get_connection_count 改为异步方法，确保线程安全
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from fastapi import WebSocket


class StreamManager:
    """
    WebSocket 连接管理器

    说明: 管理所有 WebSocket 连接，支持按 task_id 分组，
          提供线程安全的连接注册、注销和消息广播功能

    线程安全说明:
        - 所有方法都是异步方法，通过 asyncio.Lock 保护共享状态
        - 通过 asyncio.run_coroutine_threadsafe() 从工作线程调用时，
          协程会被调度到主事件循环执行，确保 asyncio.Lock 正确工作
    """

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, task_id: str) -> None:
        """
        注册新的 WebSocket 连接到连接池

        Args:
            websocket: WebSocket 连接对象
            task_id: 任务 ID，用于分组管理连接
        """
        async with self._lock:
            if task_id not in self._connections:
                self._connections[task_id] = []
            self._connections[task_id].append(websocket)
            logger.debug(f"WebSocket connected: task_id={task_id}, total connections={len(self._connections[task_id])}")

    async def disconnect(self, websocket: WebSocket) -> None:
        """
        从连接池移除 WebSocket 连接

        Args:
            websocket: 要移除的 WebSocket 连接对象
        """
        async with self._lock:
            for task_id, connections in list(self._connections.items()):
                if websocket in connections:
                    connections.remove(websocket)
                    logger.debug(f"WebSocket disconnected: task_id={task_id}, remaining={len(connections)}")
                    if not connections:
                        del self._connections[task_id]
                    break

    async def broadcast(self, task_id: str, message: dict) -> None:
        """
        向指定 task_id 的所有连接广播消息

        Args:
            task_id: 目标任务 ID
            message: 要发送的消息字典
        """
        async with self._lock:
            connections = self._connections.get(task_id, [])
            if not connections:
                logger.debug(f"No connections found for task_id={task_id}")
                return

            disconnected = []
            for connection in connections:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.warning(f"Failed to send message to connection: {e}")
                    disconnected.append(connection)

            for connection in disconnected:
                connections.remove(connection)
                logger.debug(f"Removed disconnected WebSocket from task_id={task_id}")

            if not connections:
                del self._connections[task_id]

    async def get_connection_count(self, task_id: str | None = None) -> int:
        """
        获取连接数量

        Args:
            task_id: 可选，指定任务 ID。如果提供则返回该任务的连接数，
                    否则返回总连接数

        Returns:
            连接数量
        """
        async with self._lock:
            if task_id:
                return len(self._connections.get(task_id, []))
            return sum(len(conns) for conns in self._connections.values())


# 模块级单例实例
stream_manager = StreamManager()
