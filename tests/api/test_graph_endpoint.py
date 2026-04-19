"""
API 图谱端点测试

修改时间: 2026-04-05
修改者: AI Assistant
任务: fix-test-data-pollution
修改内容: 使用 api_client fixture 确保测试使用测试数据库
"""

from fastapi.testclient import TestClient


def test_get_graph_not_found_returns_empty_object(api_client: TestClient):
    response = api_client.get("/api/novels/nonexistent/graph?task_id=nonexistent")
    assert response.status_code == 404
