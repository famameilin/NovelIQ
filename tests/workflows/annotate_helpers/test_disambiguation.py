from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.models.local.disambiguation import ExtendedDisambigResult, build_evidence_profile
from src.workflows.annotate_helpers import disambiguation as disambig_mod


def _candidates(*names: str) -> list[dict[str, int | str]]:
    return [{"name": name, "count": 1} for name in names]


class _FakeDisambigClient:
    def __init__(self) -> None:
        self._config = SimpleNamespace(model="test-model")
        self.received_existing_names: list[str] | None = None

    def disambiguate_characters(self, candidates, context_sentences=None, existing_names=None, rag_hint=None):
        self.received_existing_names = existing_names
        return ExtendedDisambigResult(alias_map={}, entity_types={}, entity_relations=[])

    def is_cloud_api(self) -> bool:
        return False


def test_retry_disambig_passes_existing_names_to_client_and_interaction_saver() -> None:
    client = _FakeDisambigClient()
    captured: dict[str, object] = {}

    def _fake_save(*args, **kwargs):
        captured["existing_names"] = kwargs.get("existing_names")
        captured["rag_hint"] = kwargs.get("rag_hint")

    with patch.object(disambig_mod, "_save_disambiguation_interaction", side_effect=_fake_save):
        disambig_mod._retry_disambig(
            client=client,
            candidates=_candidates("masked_person"),
            context_sentences={"masked_person": "identity reveal in scene"},
            existing_names=["bai_zhi", "hou_fei_bai"],
            stage_name="incremental disambiguation",
            run_id="run-1",
            rag_hint="anchor hint",
        )

    assert client.received_existing_names == ["bai_zhi", "hou_fei_bai"]
    assert captured["existing_names"] == ["bai_zhi", "hou_fei_bai"]
    assert captured["rag_hint"] == "anchor hint"


def test_run_final_disambiguation_uses_alias_map_values_and_only_unresolved_candidates() -> None:
    captured: dict[str, object] = {}

    def _fake_retry(client, candidates, context_sentences, existing_names, stage_name, run_id=None, rag_hint=None):
        captured["existing_names"] = existing_names
        captured["candidates"] = candidates
        captured["rag_hint"] = rag_hint
        return ExtendedDisambigResult(alias_map={}, entity_types={}, entity_relations=[])

    class _DummyAnnRepo:
        def __init__(self, conn):
            self.conn = conn

        def update_character_names(self, run_id, alias_map, novel_id=None):
            return None

    alias_map = {
        "masked_person": "bai_zhi",
        "bai_zhi": "bai_zhi",
        "monkey": "hou_fei_bai",
    }

    with (
        patch.object(disambig_mod, "_load_disambig_checkpoint", return_value=(None, None)),
        patch.object(disambig_mod, "_load_disambig_states", return_value=None),
        patch.object(
            disambig_mod,
            "fetch_all_character_names",
            return_value=[
                {"name": "masked_person", "count": 3},
                {"name": "bai_zhi", "count": 5},
                {"name": "monkey", "count": 2},
                {"name": "hou_fei_bai", "count": 4},
                {"name": "lin_li_guo", "count": 1},
            ],
        ),
        patch.object(disambig_mod, "build_context_sentences", side_effect=[{}, {"bai_zhi": "scene", "hou_fei_bai": "scene"}]),
        patch.object(disambig_mod, "_retry_disambig", side_effect=_fake_retry),
        patch.object(disambig_mod, "AnnotationRepository", _DummyAnnRepo),
        patch.object(disambig_mod, "_save_disambig_checkpoint", return_value=None),
    ):
        disambig_mod._run_final_disambiguation(
            conn=None,
            alias_map=alias_map,
            full_disambig_client=MagicMock(),
            alias_keywords=["alias", "name"],
            novel_id="novel-1",
            run_id="run-1",
        )

    assert set(captured["existing_names"]) == {"bai_zhi", "hou_fei_bai"}
    assert captured["candidates"] == [{"name": "lin_li_guo", "count": 1}]
    assert "已存在角色锚点" in str(captured["rag_hint"])


def test_run_final_disambiguation_skips_model_call_when_no_unresolved_candidates() -> None:
    class _DummyAnnRepo:
        def __init__(self, conn):
            self.conn = conn

        def update_character_names(self, run_id, alias_map, novel_id=None):
            return None

    alias_map = {
        "masked_person": "bai_zhi",
        "bai_zhi": "bai_zhi",
        "monkey": "hou_fei_bai",
        "hou_fei_bai": "hou_fei_bai",
    }

    retry_mock = MagicMock()

    with (
        patch.object(disambig_mod, "_load_disambig_checkpoint", return_value=(None, None)),
        patch.object(disambig_mod, "_load_disambig_states", return_value=None),
        patch.object(
            disambig_mod,
            "fetch_all_character_names",
            return_value=[
                {"name": "masked_person", "count": 10},
                {"name": "bai_zhi", "count": 10},
                {"name": "monkey", "count": 10},
                {"name": "hou_fei_bai", "count": 10},
            ],
        ),
        patch.object(disambig_mod, "_retry_disambig", retry_mock),
        patch.object(disambig_mod, "AnnotationRepository", _DummyAnnRepo),
        patch.object(disambig_mod, "_save_disambig_checkpoint", return_value=None),
    ):
        disambig_mod._run_final_disambiguation(
            conn=None,
            alias_map=alias_map,
            full_disambig_client=MagicMock(),
            alias_keywords=["alias", "name"],
            novel_id="novel-1",
            run_id="run-1",
        )

    retry_mock.assert_not_called()


def test_validate_confidence_with_evidence_promotes_unique_marker_merge() -> None:
    context = (
        "【前文总结】贺伯安为救同伴被火焰吞噬昏迷\n"
        "赵兰英想起贺伯安脊椎处的白金火焰符号，怀里的婴孩脊椎处也有同样印记"
    )
    result = ExtendedDisambigResult(
        alias_map={"婴儿": "婴儿"},
        entity_types={"婴儿": "character"},
        entity_relations=[],
        alias_confidence={"婴儿": "medium"},
        evidence_profiles={"婴儿": build_evidence_profile(context)},
    )

    validated = disambig_mod.validate_confidence_with_evidence(result, ["贺伯安"], {"婴儿": context})

    assert validated.alias_map["婴儿"] == "贺伯安"
    assert validated.alias_confidence["婴儿"] == "high"


def test_validate_confidence_with_evidence_does_not_merge_on_suffix_only_anchor_match() -> None:
    context = "王伯安肩头旧伤发作，额间冷汗密布"
    result = ExtendedDisambigResult(
        alias_map={"灰衣公子": "灰衣公子"},
        entity_types={"灰衣公子": "character"},
        entity_relations=[],
        alias_confidence={"灰衣公子": "medium"},
        evidence_profiles={"灰衣公子": build_evidence_profile(context)},
    )

    validated = disambig_mod.validate_confidence_with_evidence(result, ["贺伯安"], {"灰衣公子": context})

    assert validated.alias_map["灰衣公子"] == "灰衣公子"
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


def test_build_alias_and_state_updates_from_confidence() -> None:
    result = ExtendedDisambigResult(
        alias_map={"monkey": "hou_fei_bai", "abacus": "bai_zhi", "gray_man": "bai_zhi"},
        entity_types={},
        entity_relations=[],
        alias_confidence={"monkey": "high", "abacus": "medium", "gray_man": "low"},
    )
    alias_updates, snapshot = disambig_mod._build_alias_and_state_updates(
        result=result,
        alias_map={"bai_zhi": "bai_zhi", "hou_fei_bai": "hou_fei_bai"},
        state_snapshot=None,
    )
    assert alias_updates["monkey"] == "hou_fei_bai"
    assert alias_updates["abacus"] == "abacus"
    assert alias_updates["gray_man"] == "gray_man"
    assert snapshot["monkey"]["state"] == disambig_mod.DISAMBIG_STATE_RESOLVED
    assert snapshot["abacus"]["state"] == disambig_mod.DISAMBIG_STATE_REVIEW
    assert snapshot["gray_man"]["state"] == disambig_mod.DISAMBIG_STATE_UNRESOLVED


def test_build_alias_and_state_updates_keeps_high_self_resolution_in_alias_map() -> None:
    result = ExtendedDisambigResult(
        alias_map={"hou_zheng_de": "hou_zheng_de"},
        entity_types={},
        entity_relations=[],
        alias_confidence={"hou_zheng_de": "high"},
    )
    alias_updates, snapshot = disambig_mod._build_alias_and_state_updates(
        result=result,
        alias_map={},
        state_snapshot=None,
    )

    assert alias_updates["hou_zheng_de"] == "hou_zheng_de"
    assert snapshot["hou_zheng_de"]["state"] == disambig_mod.DISAMBIG_STATE_RESOLVED


def test_build_alias_and_state_updates_does_not_revert_existing_alias_on_medium_or_low() -> None:
    result = ExtendedDisambigResult(
        alias_map={"masked_person": "bai_zhi", "gray_man": "bai_zhi"},
        entity_types={},
        entity_relations=[],
        alias_confidence={"masked_person": "medium", "gray_man": "low"},
    )
    alias_updates, snapshot = disambig_mod._build_alias_and_state_updates(
        result=result,
        alias_map={"masked_person": "bai_zhi", "gray_man": "bai_zhi", "bai_zhi": "bai_zhi"},
        state_snapshot=None,
    )
    assert "masked_person" not in alias_updates
    assert "gray_man" not in alias_updates
    assert snapshot["masked_person"]["state"] == disambig_mod.DISAMBIG_STATE_REVIEW
    assert snapshot["gray_man"]["state"] == disambig_mod.DISAMBIG_STATE_UNRESOLVED
    assert snapshot["masked_person"]["canonical"] == "bai_zhi"
    assert snapshot["gray_man"]["canonical"] == "bai_zhi"


def test_extract_new_names_from_db_uses_combined_character_sources() -> None:
    all_names = [
        {"name": "柳婉儿", "count": 5},
        {"name": "二妈妈", "count": 3},
        {"name": "赵兰英", "count": 2},
        {"name": "王成", "count": 1},
    ]

    with patch.object(disambig_mod, "fetch_all_character_names", return_value=all_names) as fetch_mock:
        result = disambig_mod.extract_new_names_from_db(
            conn=None,
            alias_map={"柳婉儿": "柳婉儿", "二妈妈": "赵兰英"},
            run_id="run-1",
            current_chunk_id=12,
        )

    fetch_mock.assert_called_once_with(None, "run-1", max_chunk_id=12)
    assert result == [
        {"name": "王成", "count": 1},
    ]


def test_save_disambiguation_interaction_rebuilds_prompt_with_existing_names() -> None:
    client = _FakeDisambigClient()
    captured: dict[str, object] = {}

    def _fake_build_messages(candidates, context_sentences, existing_names, rag_hint):
        captured["existing_names"] = existing_names
        return [
            {"role": "system", "content": f"anchors={existing_names}"},
            {"role": "user", "content": "u"},
        ]

    class _DummySession:
        def close(self):
            return None

    class _DummyRepo:
        def __init__(self, session):
            self.session = session

        def save_interaction(self, **kwargs):
            captured["prompt"] = kwargs.get("prompt", "")

    with (
        patch("src.models.local.disambiguation.build_disambiguate_messages", side_effect=_fake_build_messages),
        patch("src.storage.db.get_session_factory", return_value=lambda: _DummySession()),
        patch("src.storage.repositories.model_interaction_repository.ModelInteractionRepository", _DummyRepo),
    ):
        disambig_mod._save_disambiguation_interaction(
            client=client,
            run_id="run-1",
            candidates=_candidates("masked_person"),
            context_sentences={"masked_person": "scene"},
            existing_names=["bai_zhi"],
            rag_hint="anchor hint",
            result={"masked_person": "bai_zhi"},
            stage_name="final disambiguation",
            attempt_number=1,
            duration_ms=10,
        )

    assert captured["existing_names"] == ["bai_zhi"]
    assert "anchors=['bai_zhi']" in str(captured["prompt"])
