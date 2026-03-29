from unittest.mock import MagicMock, patch

import pytest

from src.metrics.aggregate.fetchers import fetch_relation_data


class _DummyAnnotationRepo:
    def __init__(self, pending=None):
        self.session = object()
        self._pending = pending or []

    def fetch_pending_chunk_relations(self, run_id, to_chunk=None, limit=200):
        return self._pending


def test_fetch_relation_data_raises_when_pending_exists_and_graph_empty():
    annotation_repo = _DummyAnnotationRepo(pending=[object()])
    mock_graph_repo = MagicMock()
    mock_graph_repo.fetch_current_relations.return_value = []
    mock_graph_repo.fetch_relation_events.return_value = []

    with patch("src.storage.repositories.GraphRepository", return_value=mock_graph_repo):
        with pytest.raises(RuntimeError, match="pending relations"):
            fetch_relation_data(annotation_repo, "run-1")


def test_fetch_relation_data_allows_empty_graph_when_no_pending():
    annotation_repo = _DummyAnnotationRepo(pending=[])
    mock_graph_repo = MagicMock()
    mock_graph_repo.fetch_current_relations.return_value = []
    mock_graph_repo.fetch_relation_events.return_value = []

    with patch("src.storage.repositories.GraphRepository", return_value=mock_graph_repo):
        data = fetch_relation_data(annotation_repo, "run-1")

    assert data.relations == []
    assert data.full_relations == []
