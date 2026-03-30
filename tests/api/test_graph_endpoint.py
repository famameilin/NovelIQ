from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_get_graph_not_found_returns_empty_object():
    response = client.get("/api/novels/nonexistent/graph?task_id=nonexistent")
    assert response.status_code == 404
