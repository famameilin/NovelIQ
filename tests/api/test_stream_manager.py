"""
StreamManager 单元测试

创建时间: 2026-04-07
创建者: TraeAI
任务: websocket-streaming-progress
说明: 测试 WebSocket 连接管理器的核心功能

修改时间: 2026-04-07
修改者: TraeAI
修改内容: 更新 get_connection_count 测试为异步方法
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.services.stream_manager import StreamManager


class TestStreamManager:
    """StreamManager 测试类"""

    def test_init(self):
        """测试初始化"""
        manager = StreamManager()
        assert manager._connections == {}
        assert manager._lock is not None

    @pytest.mark.asyncio
    async def test_connect(self):
        """测试连接注册"""
        manager = StreamManager()
        websocket = AsyncMock()
        task_id = "test-task-123"

        await manager.connect(websocket, task_id)

        assert task_id in manager._connections
        assert websocket in manager._connections[task_id]

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """测试连接断开"""
        manager = StreamManager()
        websocket = AsyncMock()
        task_id = "test-task-123"

        await manager.connect(websocket, task_id)
        await manager.disconnect(websocket)

        assert task_id not in manager._connections

    @pytest.mark.asyncio
    async def test_disconnect_multiple_connections(self):
        """测试多个连接时断开其中一个"""
        manager = StreamManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        task_id = "test-task-123"

        await manager.connect(ws1, task_id)
        await manager.connect(ws2, task_id)

        await manager.disconnect(ws1)

        assert task_id in manager._connections
        assert ws1 not in manager._connections[task_id]
        assert ws2 in manager._connections[task_id]

    @pytest.mark.asyncio
    async def test_broadcast(self):
        """测试消息广播"""
        manager = StreamManager()
        websocket = AsyncMock()
        task_id = "test-task-123"
        message = {"type": "test", "data": "hello"}

        await manager.connect(websocket, task_id)
        await manager.broadcast(task_id, message)

        websocket.send_json.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_connections(self):
        """测试向多个连接广播消息"""
        manager = StreamManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        task_id = "test-task-123"
        message = {"type": "test", "data": "hello"}

        await manager.connect(ws1, task_id)
        await manager.connect(ws2, task_id)
        await manager.broadcast(task_id, message)

        ws1.send_json.assert_called_once_with(message)
        ws2.send_json.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_broadcast_no_connections(self):
        """测试无连接时广播"""
        manager = StreamManager()
        task_id = "test-task-123"
        message = {"type": "test", "data": "hello"}

        # 应该不抛出异常
        await manager.broadcast(task_id, message)

    @pytest.mark.asyncio
    async def test_broadcast_removes_closed_connection(self):
        """测试广播时移除断开的连接"""
        manager = StreamManager()
        websocket = AsyncMock()
        websocket.send_json.side_effect = Exception("Connection closed")
        task_id = "test-task-123"
        message = {"type": "test", "data": "hello"}

        await manager.connect(websocket, task_id)
        await manager.broadcast(task_id, message)

        # 断开的连接应该被移除
        assert task_id not in manager._connections

    @pytest.mark.asyncio
    async def test_get_connection_count(self):
        """测试获取连接数量"""
        manager = StreamManager()

        # 无连接时
        assert await manager.get_connection_count() == 0

    @pytest.mark.asyncio
    async def test_get_connection_count_with_connections(self):
        """测试有连接时获取连接数量"""
        manager = StreamManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        task_id = "test-task-123"

        await manager.connect(ws1, task_id)
        await manager.connect(ws2, task_id)

        assert await manager.get_connection_count() == 2
        assert await manager.get_connection_count(task_id) == 2

    @pytest.mark.asyncio
    async def test_thread_safety(self):
        """测试线程安全性"""
        manager = StreamManager()
        task_id = "test-task-123"

        async def connect_task(i):
            ws = AsyncMock()
            await manager.connect(ws, f"{task_id}-{i}")

        # 并发连接
        tasks = [connect_task(i) for i in range(10)]
        await asyncio.gather(*tasks)

        # 所有连接应该都被记录
        assert await manager.get_connection_count() == 10
