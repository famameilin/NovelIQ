from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import results as results_mod

client = TestClient(app)


def test_get_graph_not_found_returns_empty_object():
    response = client.get("/api/novels/nonexistent/graph?task_id=nonexistent")
    assert response.status_code == 200
    assert response.json() == {}


def test_get_graph_returns_snapshot(monkeypatch):
    class _DummyConn:
        def close(self):
            return None

    class _DummyAnnotationRepo:
        def __init__(self, conn):
            self.conn = conn

    expected = {
        "nodes": [{"entity_id": 1, "name": "A"}],
        "edges": [{"relation_id": 1, "from_entity_id": 1, "to_entity_id": 2}],
        "events": [],
        "summary": {"node_count": 2, "edge_count": 1},
        "quality": {"conflict_count": 0},
    }

    monkeypatch.setattr(results_mod, "_get_session_and_run_id", lambda task_id, novel_service: (_DummyConn(), "run-1"))
    monkeypatch.setattr(results_mod, "AnnotationRepository", _DummyAnnotationRepo)
    monkeypatch.setattr(results_mod, "_fetch_graph_snapshot", lambda run_id, annotation_repo: expected)

    response = client.get("/api/novels/demo/graph?task_id=demo123")
    assert response.status_code == 200
    assert response.json() == expected
