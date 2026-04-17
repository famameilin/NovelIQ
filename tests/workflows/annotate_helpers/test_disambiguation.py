from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.models.local.disambiguation import (
    DisambiguationPromptContext,
    ExtendedDisambigResult,
    build_evidence_profile,
)
from src.workflows.annotate_helpers import disambiguation as disambig_mod


def _candidates(*names: str) -> list[dict[str, int | str]]:
    return [{"name": name, "count": 1} for name in names]


class _FakeDisambigClient:
    def __init__(self) -> None:
        self._config = SimpleNamespace(model="test-model")
        self.received_existing_names: list[str] | None = None
        self.received_prompt_context: DisambiguationPromptContext | None = None

    async def disambiguate_characters(
        self,
        candidates,
        context_sentences=None,
        existing_names=None,
        prompt_context=None,
    ):
        self.received_existing_names = existing_names
        self.received_prompt_context = prompt_context
        return ExtendedDisambigResult(canonical_decisions={}, entity_types={}, entity_relations=[])

    def is_cloud_api(self) -> bool:
        return False


@pytest.mark.asyncio
async def test_retry_disambig_passes_existing_names_to_client() -> None:
    client = _FakeDisambigClient()

    with patch("src.workflows.annotate_helpers.disambiguation.pipeline.record_model_interaction"):
        await disambig_mod._retry_disambig(
            client=client,
            candidates=_candidates("masked_person"),
            context_sentences={"masked_person": "identity reveal in scene"},
            existing_names=["bai_zhi", "hou_fei_bai"],
            stage_name="incremental disambiguation",
            run_id="run-1",
            prompt_context=DisambiguationPromptContext(existing_character_hint="anchor hint"),
        )

    assert client.received_existing_names == ["bai_zhi", "hou_fei_bai"]
    assert client.received_prompt_context is not None
    assert client.received_prompt_context.existing_character_hint == "anchor hint"


def test_validate_confidence_with_evidence_promotes_unique_marker_merge() -> None:
    context = (
        "【前文总结】贺伯安为救同伴被火焰吞噬昏迷\n赵兰英想起贺伯安脊椎处的白金火焰符号，怀里的婴孩脊椎处也有同样印记"
    )
    result = ExtendedDisambigResult(
        canonical_decisions={"婴儿": "婴儿"},
        entity_types={"婴儿": "character"},
        entity_relations=[],
        alias_confidence={"婴儿": "medium"},
        evidence_profiles={"婴儿": build_evidence_profile(context)},
    )

    validated = disambig_mod.validate_confidence_with_evidence(result, ["贺伯安"], {"婴儿": context})

    assert validated.canonical_decisions["婴儿"] == "贺伯安"
    assert validated.alias_confidence["婴儿"] == "high"


def test_validate_confidence_with_evidence_does_not_merge_on_suffix_only_anchor_match() -> None:
    context = "王伯安肩头旧伤发作，额间冷汗密布"
    result = ExtendedDisambigResult(
        canonical_decisions={"灰衣公子": "灰衣公子"},
        entity_types={"灰衣公子": "character"},
        entity_relations=[],
        alias_confidence={"灰衣公子": "medium"},
        evidence_profiles={"灰衣公子": build_evidence_profile(context)},
    )

    validated = disambig_mod.validate_confidence_with_evidence(result, ["贺伯安"], {"灰衣公子": context})

    assert validated.canonical_decisions["灰衣公子"] == "灰衣公子"
    assert validated.alias_confidence["灰衣公子"] == "medium"


def test_collect_final_disambiguation_candidates_prefers_state_snapshot() -> None:
    snapshot = {
        "bai_zhi": {"state": "resolved", "confidence": "high", "canonical": "bai_zhi"},
        "lin_li_guo": {"state": "review", "confidence": "medium", "canonical": "bai_zhi"},
        "masked_person": {"state": "unresolved", "confidence": "low", "canonical": "bai_zhi"},
    }
    candidates = disambig_mod._collect_final_disambiguation_candidates(
        all_names=_candidates("bai_zhi", "lin_li_guo", "masked_person"),
        alias_map={"bai_zhi": "bai_zhi"},
        state_snapshot=snapshot,
    )
    assert set(candidates) == {"lin_li_guo", "masked_person"}


def test_collect_final_disambiguation_candidates_rereviews_self_resolved_extension_name() -> None:
    snapshot = {
        "伯安": {"state": "resolved", "confidence": "high", "canonical": "伯安"},
        "贺伯安": {"state": "resolved", "confidence": "high", "canonical": "贺伯安"},
    }
    candidates = disambig_mod._collect_final_disambiguation_candidates(
        all_names=[
            {"name": "伯安", "count": 33},
            {"name": "贺伯安", "count": 8},
        ],
        alias_map={"伯安": "伯安", "贺伯安": "贺伯安"},
        state_snapshot=snapshot,
    )
    assert candidates == ["贺伯安"]


@pytest.mark.asyncio
async def test_record_model_interaction_with_disambiguation() -> None:
    client = _FakeDisambigClient()

    with patch("src.workflows.annotate_helpers.disambiguation.pipeline.record_model_interaction") as mock_record:
        await disambig_mod._retry_disambig(
            client=client,
            candidates=_candidates("masked_person"),
            context_sentences={"masked_person": "scene"},
            existing_names=["bai_zhi"],
            stage_name="final disambiguation",
            run_id="run-1",
            prompt_context=DisambiguationPromptContext(existing_character_hint="anchor hint"),
        )

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["model_name"] == "test-model"
    assert call_kwargs["interaction_type"] == "disambiguate"
