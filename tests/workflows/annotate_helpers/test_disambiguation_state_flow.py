from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.models.local.disambiguation import DisambiguationState, ExtendedDisambigResult
from src.workflows.annotate_helpers import disambiguation as disambig_mod
from src.workflows.annotate_helpers.disambiguation import pipeline as pipeline_mod


def test_apply_disambiguation_decisions_keeps_uncertain_self_map_in_review() -> None:
    result = ExtendedDisambigResult(
        canonical_decisions={"masked_person": "masked_person"},
        entity_types={},
        entity_relations=[],
        alias_confidence={"masked_person": "medium"},
    )

    state = disambig_mod.apply_disambiguation_decisions(DisambiguationState.empty(), result)
    review = state.get_review_status_dict()["masked_person"]

    assert review.status == disambig_mod.DISAMBIG_STATE_REVIEW
    assert review.confidence == "medium"
    assert "masked_person" not in state.known_canonical_names


def test_run_final_disambiguation_with_state_persists_canonicals_before_relations() -> None:
    captured: dict[str, object] = {}

    class _DummyAnnRepo:
        def __init__(self, conn) -> None:
            self.conn = conn

        def ensure_canonical_entities(self, run_id, known_canonical_names, novel_id=None, entity_types=None):
            captured["ensure"] = (run_id, set(known_canonical_names), novel_id, entity_types)
            return {name: index for index, name in enumerate(sorted(known_canonical_names), start=1)}

        def apply_alias_merges(self, run_id, alias_merges):
            captured["merges"] = (run_id, dict(alias_merges))

    class _DummyConn:
        def commit(self):
            pass

    state = DisambiguationState(
        discovered_names=frozenset({"bai_zhi", "hou_fei_bai"}),
        known_canonical_names=frozenset({"bai_zhi", "hou_fei_bai"}),
        pending_relations=(
            {"from": "bai_zhi", "to": "hou_fei_bai", "type": "师徒"},
        ),
    )

    with (
        patch.object(pipeline_mod, "AnnotationRepository", _DummyAnnRepo),
        patch.object(pipeline_mod, "fetch_all_character_names", return_value=[]),
        patch.object(pipeline_mod, "_process_entity_relations", return_value=(1, [])) as process_mock,
        patch.object(pipeline_mod, "_save_disambig_checkpoint", return_value=None),
    ):
        new_state = disambig_mod._run_final_disambiguation_with_state(
            conn=_DummyConn(),
            state=state,
            full_disambig_client=MagicMock(),
            alias_keywords=["alias"],
            novel_id="novel-1",
            run_id="run-1",
        )

    assert new_state.known_canonical_names == state.known_canonical_names
    assert captured["ensure"] == ("run-1", {"bai_zhi", "hou_fei_bai"}, "novel-1", {})
    assert captured["merges"] == ("run-1", {})
    process_mock.assert_called_once()


def test_run_final_disambiguation_with_state_skips_known_canonical_without_review_record() -> None:
    class _DummyConn:
        def commit(self):
            pass

    state = DisambiguationState(
        discovered_names=frozenset({"hou_fei_bai"}),
        known_canonical_names=frozenset({"hou_fei_bai"}),
    )

    with (
        patch.object(pipeline_mod, "AnnotationRepository", MagicMock()),
        patch.object(
            pipeline_mod,
            "fetch_all_character_names",
            return_value=[{"name": "hou_fei_bai", "count": 12}],
        ),
        patch.object(pipeline_mod, "_retry_disambig") as retry_mock,
        patch.object(pipeline_mod, "_process_entity_relations", return_value=(0, [])),
        patch.object(pipeline_mod, "_save_disambig_checkpoint", return_value=None),
    ):
        new_state = disambig_mod._run_final_disambiguation_with_state(
            conn=_DummyConn(),
            state=state,
            full_disambig_client=MagicMock(),
            alias_keywords=["alias"],
            novel_id="novel-1",
            run_id="run-1",
        )

    assert new_state.known_canonical_names == state.known_canonical_names
    assert new_state.alias_merges == state.alias_merges
    assert new_state.review_status == state.review_status
    assert new_state.pending_relations == state.pending_relations
    retry_mock.assert_not_called()
