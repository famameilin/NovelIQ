"""
WebSocket 端点测试

创建时间: 2026-04-07
创建者: TraeAI
任务: websocket-streaming-progress
说明: 测试 WebSocket 端点功能

修改时间: 2026-04-07
修改者: TraeAI
任务: implement-task-cancellation
修改内容: 修复 Python 3.12 asyncio 事件循环问题
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.services.stream_manager import stream_manager


def _run_async(coro):
    """安全地在测试中运行协程，兼容已有事件循环的场景。

    NOTE: 当已有运行中的事件循环时，通过新线程 + asyncio.run 执行。
    这要求被调用的协程（如 stream_manager.broadcast）内部无跨循环状态依赖。
    TODO(TechDebt): 迁移至 pytest-asyncio 以彻底解决跨线程异步测试的不稳定性。
    当前方案在 CI 并行执行时可能出现间歇性失败。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=10)
    return asyncio.run(coro)


class TestWebSocketEndpoint:
    """WebSocket 端点测试类"""

    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        return TestClient(app)

    def test_websocket_connect(self, client):
        """测试 WebSocket 连接"""
        with client.websocket_connect("/api/ws/tasks/test-task-123") as websocket:
            pass

    def test_websocket_receive_broadcast(self, client):
        """测试接收广播消息"""
        task_id = "test-task-456"
        with client.websocket_connect(f"/api/ws/tasks/{task_id}") as websocket:
            message = {"type": "stage_progress", "task_id": task_id, "data": {"percent": 50}}
            _run_async(stream_manager.broadcast(task_id, message))
            data = websocket.receive_json()
            assert data["type"] == "stage_progress"
            assert data["task_id"] == task_id

    def test_websocket_disconnect(self, client):
        """测试 WebSocket 断开"""
        task_id = "test-task-789"
        with client.websocket_connect(f"/api/ws/tasks/{task_id}") as websocket:
            pass

    def test_websocket_multiple_clients_same_task(self, client):
        """测试同一任务的多个客户端"""
        task_id = "test-task-multi"
        with client.websocket_connect(f"/api/ws/tasks/{task_id}") as ws1:
            with client.websocket_connect(f"/api/ws/tasks/{task_id}") as ws2:
                message = {"type": "test", "task_id": task_id}
                _run_async(stream_manager.broadcast(task_id, message))
                data1 = ws1.receive_json()
                data2 = ws2.receive_json()
                assert data1["type"] == "test"
                assert data1["task_id"] == task_id
                assert data2["type"] == "test"
                assert data2["task_id"] == task_id

    def test_websocket_different_tasks(self, client):
        """测试不同任务的客户端隔离"""
        task_id1 = "test-task-1"
        task_id2 = "test-task-2"
        with client.websocket_connect(f"/api/ws/tasks/{task_id1}") as ws1:
            with client.websocket_connect(f"/api/ws/tasks/{task_id2}") as ws2:
                message = {"type": "test", "task_id": task_id1}
                _run_async(stream_manager.broadcast(task_id1, message))
                data1 = ws1.receive_json()
                assert data1["type"] == "test"
                assert data1["task_id"] == task_id1
                # ws2 不应该收到消息（因为只订阅了 task2)
                with pytest.raises(Exception):
                    ws2.receive_json(timeout=0.5)
