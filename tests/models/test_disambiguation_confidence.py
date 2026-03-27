from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.local.disambiguation import build_extended_result_from_response
from src.models.local.schema import DisambiguateResponseModel


def _candidates(*names: str) -> list[dict[str, int | str]]:
    return [{"name": name, "count": 1} for name in names]


def test_disambiguate_response_model_accepts_alias_confidence() -> None:
    response = DisambiguateResponseModel(
        canonical_decisions={"monkey": "hou_fei_bai"},
        alias_confidence={"monkey": "high"},
        entity_types={},
        entity_relations=[],
    )
    assert response.alias_confidence["monkey"] == "high"


def test_build_extended_result_defaults_confidence_to_medium() -> None:
    response = DisambiguateResponseModel(
        canonical_decisions={"monkey": "hou_fei_bai"},
        entity_types={},
        entity_relations=[],
    )
    result = build_extended_result_from_response(response, _candidates("monkey", "abacus"))
    assert result.alias_confidence["monkey"] == "medium"
    assert result.alias_confidence["abacus"] == "medium"


def test_disambiguate_response_model_rejects_legacy_merge_target_map() -> None:
    with pytest.raises(ValidationError):
        DisambiguateResponseModel(
            merge_target_map={"monkey": "hou_fei_bai"},
            entity_types={},
            entity_relations=[],
        )
