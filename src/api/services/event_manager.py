"""
SSE 事件管理器

创建时间: 2026-04-09
创建者: TraeAI
任务: 实现 SSE 路由和事件管理器
说明: 管理 SSE 连接和消息推送

修改时间: 2026-04-09
修改者: TraeAI
修改内容: 添加连接超时清理机制

修改时间: 2026-04-09
修改者: GLM-5
任务: sse-architecture-review
修改内容:
- 支持同一 task_id 的多客户端连接（每个连接独立 Queue）
- 新增消息缓冲（ring buffer），解决 late-joiner 问题
- connect 时自动回放缓冲消息
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

_MAX_BUFFER_SIZE = 64


class EventManager:
    """
    SSE 事件管理器

    管理 SSE 连接和消息推送，支持多客户端连接和消息缓冲
    """

    def __init__(self, idle_timeout: float = 3600.0, buffer_size: int = _MAX_BUFFER_SIZE) -> None:
        self._connections: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_activity: dict[str, float] = {}
        self._idle_timeout = idle_timeout
        self._buffer_size = buffer_size
        self._buffers: dict[str, deque[dict[str, Any]]] = {}
        self._cleanup_task: asyncio.Task[None] | None = None

    async def connect(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        """建立 SSE 连接，返回独立的 Queue，并回放缓冲消息"""
        if task_id not in self._connections:
            self._connections[task_id] = []
            self._locks[task_id] = asyncio.Lock()
            self._buffers[task_id] = deque(maxlen=self._buffer_size)
            self._start_cleanup_task()

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._connections[task_id].append(queue)
        self._last_activity[task_id] = time.monotonic()

        # 回放缓冲消息，让 late-joiner 不丢失关键事件
        for msg in self._buffers.get(task_id, []):
            await queue.put(msg)

        return queue

    def _start_cleanup_task(self) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_idle_connections())

    async def _cleanup_idle_connections(self) -> None:
        while True:
            await asyncio.sleep(300)
            current_time = time.monotonic()
            idle_ids = [
                task_id
                for task_id, last_time in self._last_activity.items()
                if current_time - last_time > self._idle_timeout
            ]
            for task_id in idle_ids:
                await self.disconnect_all(task_id)

    async def disconnect(self, task_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """断开指定的 SSE 连接（只移除自己的 Queue）"""
        if task_id in self._connections:
            try:
                self._connections[task_id].remove(queue)
            except ValueError:
                pass
            # 如果该 task_id 已无任何连接，清理全部资源
            if not self._connections[task_id]:
                del self._connections[task_id]
                del self._locks[task_id]
                del self._last_activity[task_id]
                if task_id in self._buffers:
                    del self._buffers[task_id]

    async def disconnect_all(self, task_id: str) -> None:
        """断开 task_id 的所有 SSE 连接"""
        if task_id in self._connections:
            del self._connections[task_id]
        if task_id in self._locks:
            del self._locks[task_id]
        if task_id in self._last_activity:
            del self._last_activity[task_id]
        if task_id in self._buffers:
            del self._buffers[task_id]

    async def send(self, task_id: str, event_type: str, data: dict[str, Any]) -> None:
        """发送消息到该 task_id 的所有 SSE 连接，并写入缓冲"""
        if task_id not in self._connections:
            return

        self._last_activity[task_id] = time.monotonic()
        message: dict[str, Any] = {"type": event_type, "data": data}

        # 写入环形缓冲
        if task_id in self._buffers:
            self._buffers[task_id].append(message)

        # 推送到所有活跃连接
        for queue in self._connections[task_id]:
            await queue.put(message)


event_manager = EventManager()
