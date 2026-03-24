from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.models.annotation import AnnotationClient
from src.workflows.annotate_helpers.client_init import _init_annotation_clients


def test_init_annotation_clients_respects_explicit_disambiguation_clients() -> None:
    annotation_client = AnnotationClient(task_type="annotation")
    incremental_client = MagicMock(name="incremental_disambig_client")
    full_client = MagicMock(name="full_disambig_client")

    _, _, resolved_incremental, resolved_full = _init_annotation_clients(
        analysis_logger=None,
        annotate_client=annotation_client,
        incremental_disambig_client=incremental_client,
        full_disambig_client=full_client,
    )

    assert resolved_incremental is incremental_client
    assert resolved_full is full_client


@patch("src.workflows.annotate_helpers.client_init.DisambiguationClient")
def test_init_annotation_clients_falls_back_to_annotation_config_when_disambig_missing(mock_disambiguation_client) -> None:
    annotation_client = AnnotationClient(task_type="annotation")
    fallback_incremental = MagicMock(name="fallback_incremental")
    fallback_full = MagicMock(name="fallback_full")

    calls = [
        ValueError("incremental config missing"),
        fallback_incremental,
        ValueError("full config missing"),
        fallback_full,
    ]
    mock_disambiguation_client.side_effect = calls

    _, _, resolved_incremental, resolved_full = _init_annotation_clients(
        analysis_logger=None,
        annotate_client=annotation_client,
        incremental_disambig_client=None,
        full_disambig_client=None,
    )

    assert resolved_incremental is fallback_incremental
    assert resolved_full is fallback_full

    assert mock_disambiguation_client.call_count == 4
    _, first_kwargs = mock_disambiguation_client.call_args_list[0]
    _, second_kwargs = mock_disambiguation_client.call_args_list[1]
    _, third_kwargs = mock_disambiguation_client.call_args_list[2]
    _, fourth_kwargs = mock_disambiguation_client.call_args_list[3]

    assert first_kwargs["task_type"] == "incremental_disambig"
    assert "config" not in first_kwargs
    assert second_kwargs["task_type"] == "incremental_disambig"
    assert second_kwargs["config"] is annotation_client._config
    assert second_kwargs["client"] is getattr(annotation_client, "_client", None)

    assert third_kwargs["task_type"] == "full_disambig"
    assert "config" not in third_kwargs
    assert fourth_kwargs["task_type"] == "full_disambig"
    assert fourth_kwargs["config"] is annotation_client._config
    assert fourth_kwargs["client"] is getattr(annotation_client, "_client", None)
