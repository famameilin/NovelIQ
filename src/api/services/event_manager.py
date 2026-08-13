"""
SSE 事件管理器

说明: 管理 SSE 连接和消息推送
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

_MAX_BUFFER_SIZE = 256


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
        self._seq_counters: dict[str, int] = {}
        self._cleanup_task: asyncio.Task[None] | None = None

    async def connect(
        self,
        task_id: str,
        last_seq: int | None = None,
    ) -> asyncio.Queue[dict[str, Any]]:
        """建立 SSE 连接，返回独立的 Queue，并按 last_seq 增量回放缓冲消息"""
        if task_id not in self._connections:
            self._connections[task_id] = []
            self._locks[task_id] = asyncio.Lock()
            self._start_cleanup_task()
        # 缓冲可能已在 send() 阶段创建（连接建立前的事件），此处只补建不覆盖
        if task_id not in self._buffers:
            self._buffers[task_id] = deque(maxlen=self._buffer_size)

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        # 注册 queue 与快照缓冲必须在同一把锁内完成，与 send() 的"append + 收集推送目标"互斥：
        # 1) 避免并发 append 使迭代中的 deque 被修改（RuntimeError: deque mutated during iteration）
        # 2) 保证"先入缓冲后注册"或"先注册后实时推送"的严格时序，杜绝同一消息回放+实时双投
        async with self._locks[task_id]:
            self._connections[task_id].append(queue)
            self._last_activity[task_id] = time.monotonic()
            buffered = [
                msg
                for msg in self._buffers.get(task_id, ())
                if last_seq is None or msg.get("seq", 0) > last_seq
            ]

        # 锁外回放：asyncio.Queue 无界 put 不会真正阻塞，但避免在锁内 await
        for msg in buffered:
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
        """断开指定的 SSE 连接（只移除自己的 Queue，保留消息缓冲供重连回放）"""
        if task_id in self._connections:
            try:
                self._connections[task_id].remove(queue)
            except ValueError:
                pass
            # 如果该 task_id 已无任何连接，清理连接级资源；
            # 消息缓冲保留给晚到/重连的客户端回放，_last_activity 也保留，
            # 由 idle cleanup 在超时后统一回收（disconnect_all 会清理缓冲）
            if not self._connections[task_id]:
                del self._connections[task_id]
                del self._locks[task_id]

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
        if task_id in self._seq_counters:
            del self._seq_counters[task_id]

    def clear_buffer(self, task_id: str) -> None:
        """清空指定任务的缓冲（保留连接），用于 resume 新轮次前丢弃上一轮终态事件"""
        if task_id in self._buffers:
            self._buffers[task_id].clear()

    async def send(self, task_id: str, event_type: str, data: dict[str, Any]) -> None:
        """发送消息到该 task_id 的所有 SSE 连接，并写入缓冲（无连接也缓冲）"""
        self._last_activity[task_id] = time.monotonic()
        if task_id not in self._buffers:
            self._buffers[task_id] = deque(maxlen=self._buffer_size)
            # 纯 API 任务（从未 connect 过、无 SSE 连接）也会产生缓冲条目，
            # 必须在此确保 idle cleanup 协程在运行，否则该条目永不回收
            self._start_cleanup_task()

        message: dict[str, Any] = {"type": event_type, "data": data}
        # 锁内完成"编号 + 入缓冲 + 快照推送目标"，锁外 await put：
        # 与 connect 的"注册 + 快照"互斥（见 connect 注释），且不阻塞其它连接操作
        async with self._locks.setdefault(task_id, asyncio.Lock()):
            seq = self._seq_counters.get(task_id, 0) + 1
            self._seq_counters[task_id] = seq
            message["seq"] = seq
            self._buffers[task_id].append(message)
            targets = list(self._connections.get(task_id, ()))

        for queue in targets:
            await queue.put(message)

    async def shutdown(self) -> None:
        """
        停止事件管理器后台任务并清空连接状态
        """

        cleanup_task = self._cleanup_task
        self._cleanup_task = None
        if cleanup_task is not None and not cleanup_task.done():
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass

        self._connections.clear()
        self._locks.clear()
        self._last_activity.clear()
        self._buffers.clear()
        self._seq_counters.clear()

    def reset_for_testing(self) -> None:
        """
        为测试夹具同步清空单例状态
        """

        cleanup_task = self._cleanup_task
        self._cleanup_task = None
        if cleanup_task is not None and not cleanup_task.done():
            cleanup_task.cancel()

        self._connections.clear()
        self._locks.clear()
        self._last_activity.clear()
        self._buffers.clear()
        self._seq_counters.clear()


event_manager = EventManager()
