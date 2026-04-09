"""
SSE 事件管理器

创建时间: 2026-04-09
创建者: TraeAI
任务: 实现 SSE 路由和事件管理器
说明: 管理 SSE 连接和消息推送

修改时间: 2026-04-09
修改者: TraeAI
修改内容: 添加连接超时清理机制
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class EventManager:
    """
    SSE 事件管理器

    管理 SSE 连接和消息推送，支持连接超时清理
    """

    def __init__(self, idle_timeout: float = 3600.0) -> None:
        """
        初始化事件管理器

        Args:
            idle_timeout: 空闲超时时间（秒），默认 1 小时
        """
        self._connections: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_activity: dict[str, float] = {}
        self._idle_timeout = idle_timeout
        self._cleanup_task: asyncio.Task[None] | None = None

    async def connect(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        """建立 SSE 连接"""
        if task_id not in self._connections:
            self._connections[task_id] = asyncio.Queue()
            self._locks[task_id] = asyncio.Lock()
            self._last_activity[task_id] = time.monotonic()
            self._start_cleanup_task()
        return self._connections[task_id]

    def _start_cleanup_task(self) -> None:
        """启动定期清理任务"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_idle_connections())

    async def _cleanup_idle_connections(self) -> None:
        """定期清理空闲连接"""
        while True:
            await asyncio.sleep(300)
            current_time = time.monotonic()
            idle_ids = [
                task_id
                for task_id, last_time in self._last_activity.items()
                if current_time - last_time > self._idle_timeout
            ]
            for task_id in idle_ids:
                await self.disconnect(task_id)

    async def disconnect(self, task_id: str) -> None:
        """断开 SSE 连接"""
        if task_id in self._connections:
            del self._connections[task_id]
        if task_id in self._locks:
            del self._locks[task_id]
        if task_id in self._last_activity:
            del self._last_activity[task_id]

    async def send(self, task_id: str, event_type: str, data: dict[str, Any]) -> None:
        """发送消息到 SSE 连接"""
        if task_id in self._connections:
            self._last_activity[task_id] = time.monotonic()
            message: dict[str, Any] = {"type": event_type, "data": data}
            await self._connections[task_id].put(message)

    async def get_message(self, task_id: str) -> dict[str, Any]:
        """获取消息（阻塞）"""
        if task_id in self._connections:
            self._last_activity[task_id] = time.monotonic()
            return await self._connections[task_id].get()
        else:
            return {"type": "error", "data": {"message": "Connection not found"}}


event_manager = EventManager()
