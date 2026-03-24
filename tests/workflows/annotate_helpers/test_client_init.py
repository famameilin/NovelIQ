from __future__ import annotations

from unittest.mock import patch

import pytest

from src.models.annotation import AnnotationClient
from src.models.interfaces import DisambiguationLike
from src.workflows.annotate_helpers.client_init import _init_annotation_clients


class _DisambiguationCapableAnnotationClient(AnnotationClient):
    def disambiguate_characters(self, candidates, context_sentences=None, existing_names=None, rag_hint=None):
        raise NotImplementedError

    def is_cloud_api(self) -> bool:
        return False


@patch("src.workflows.annotate_helpers.client_init.UnifiedModelClient")
def test_init_annotation_clients_requires_disambiguation_capable_fallback(mock_unified_model_client) -> None:
    mock_unified_model_client.side_effect = ValueError("missing config")

    annotation_client = AnnotationClient(task_type="annotation")

    with pytest.raises(TypeError, match="does not implement disambiguate_characters"):
        _init_annotation_clients(
            analysis_logger=None,
            annotate_client=annotation_client,
            incremental_disambig_client=None,
            full_disambig_client=None,
        )


@patch("src.workflows.annotate_helpers.client_init.UnifiedModelClient")
def test_init_annotation_clients_uses_annotation_fallback_when_disambiguation_capable(mock_unified_model_client) -> None:
    mock_unified_model_client.side_effect = ValueError("missing config")
    annotation_client = _DisambiguationCapableAnnotationClient(task_type="annotation")

    _, _, incremental_client, full_client = _init_annotation_clients(
        analysis_logger=None,
        annotate_client=annotation_client,
        incremental_disambig_client=None,
        full_disambig_client=None,
    )

    assert isinstance(incremental_client, DisambiguationLike)
    assert isinstance(full_client, DisambiguationLike)
    assert incremental_client is annotation_client
    assert full_client is annotation_client
