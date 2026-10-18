"""API 图谱端点测试"""

from fastapi.testclient import TestClient

from tests.support.storage_fixtures import fixture_id


def test_get_graph_not_found_returns_empty_object(api_client: TestClient):
    response = api_client.get(f"/api/novels/{fixture_id(__name__, 'nonexistent')}/graph?task_id=nonexistent")
    assert response.status_code == 404
