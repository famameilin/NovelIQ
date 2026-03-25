from __future__ import annotations

from src.models.local.disambiguation import build_extended_result_from_response
from src.models.local.schema import DisambiguateResponseModel


def test_disambiguate_response_model_accepts_alias_confidence() -> None:
    response = DisambiguateResponseModel(
        alias_map={"monkey": "hou_fei_bai"},
        alias_confidence={"monkey": "high"},
        entity_types={},
        entity_relations=[],
    )
    assert response.alias_confidence["monkey"] == "high"


def test_build_extended_result_defaults_confidence_to_medium() -> None:
    response = DisambiguateResponseModel(
        alias_map={"monkey": "hou_fei_bai"},
        entity_types={},
        entity_relations=[],
    )
    result = build_extended_result_from_response(response, ["monkey", "abacus"])
    assert result.alias_confidence["monkey"] == "medium"
    assert result.alias_confidence["abacus"] == "medium"
