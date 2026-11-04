"图折叠复用只限当前请求与相同运行"

from types import SimpleNamespace

import pytest

from src.storage.read_scope import read_projection_scope
from src.storage.repositories.graph.repository import GraphRepository


def test_graph_fold_is_shared_across_operations_and_released_between_requests(monkeypatch):
    engine = object()
    builds = []

    def build(repository, run_id):
        result = object()
        builds.append((run_id, repository.internal))
        return result

    monkeypatch.setattr(GraphRepository, "_build_folded_graph", build)
    first = GraphRepository(SimpleNamespace(get_bind=lambda: engine))
    second = GraphRepository(SimpleNamespace(get_bind=lambda: engine))
    internal = GraphRepository(SimpleNamespace(get_bind=lambda: engine), internal=True)
    with read_projection_scope():
        snapshot = first._fold_graph("run")
        assert second._fold_graph("run") is snapshot
        assert internal._fold_graph("run") is not snapshot
        assert second._fold_graph("another") is not snapshot
    with read_projection_scope():
        assert second._fold_graph("run") is not snapshot
    assert builds == [("run", False), ("run", True), ("another", False), ("run", False)]


def test_projection_scope_restores_outer_context_after_failure(monkeypatch):
    monkeypatch.setattr(GraphRepository, "_build_folded_graph", lambda *args: object())
    repository = GraphRepository(SimpleNamespace(get_bind=lambda: None))
    with read_projection_scope():
        outer = repository._fold_graph("run")
        with pytest.raises(RuntimeError), read_projection_scope():
            assert repository._fold_graph("run") is not outer
            raise RuntimeError("failed")
        assert repository._fold_graph("run") is outer
    assert repository._fold_graph("run") is not repository._fold_graph("run")
