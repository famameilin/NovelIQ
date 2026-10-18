"""API 图谱端点测试"""

from fastapi.testclient import TestClient


def test_get_graph_not_found_returns_empty_object(api_client: TestClient):
    response = api_client.get("/api/novels/nonexistent/graph?task_id=nonexistent")
    assert response.status_code == 404
