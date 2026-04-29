from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from src.models.local.disambiguation import DisambiguationState, ExtendedDisambigResult, NameReviewState
from src.models.local.disambiguation.evidence import EVIDENCE_STRENGTH_STRONG, EvidenceProfile
from src.storage.models import ChunkCharacter, Novel
from src.storage.repositories.annotation.characters import (
    fetch_all_character_names,
    fetch_reference_aware_character_names,
)
from src.workflows.annotate_helpers import disambiguation as disambig_mod
from src.workflows.annotate_helpers.disambiguation.candidates import extract_new_names_from_db
from src.workflows.annotate_helpers.disambiguation import pipeline as pipeline_mod
from src.workflows.annotate_helpers.disambiguation import pipeline_stages as pipeline_stages_mod


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


@pytest.mark.asyncio
async def test_run_final_disambiguation_with_state_persists_canonicals_before_relations() -> None:
    captured: dict[str, object] = {}

    class _DummyAnnRepo:
        def __init__(self, conn) -> None:
            self.conn = conn

        def ensure_canonical_entities(self, run_id, known_canonical_names, novel_id=None, entity_types=None):
            captured["ensure"] = (run_id, set(known_canonical_names), novel_id, entity_types)
            return {name: index for index, name in enumerate(sorted(known_canonical_names), start=1)}

        def apply_alias_merges(self, run_id, alias_merges):
            captured["merges"] = (run_id, dict(alias_merges))

        def cleanup_self_loop_relations(self, run_id):
            captured["cleanup"] = run_id

    class _DummyConn:
        def commit(self):
            pass

    state = DisambiguationState(
        discovered_names=frozenset({"bai_zhi", "hou_fei_bai"}),
        known_canonical_names=frozenset({"bai_zhi", "hou_fei_bai"}),
        pending_relations=({"from": "bai_zhi", "to": "hou_fei_bai", "type": "师徒"},),
    )

    with (
        patch.object(pipeline_stages_mod, "AnnotationRepository", _DummyAnnRepo),
        patch.object(pipeline_stages_mod, "fetch_reference_aware_character_names", return_value=[]),
        patch.object(
            pipeline_stages_mod, "_replace_final_disambiguation_chunk_relations", return_value=None
        ) as replace_mock,
        patch.object(pipeline_stages_mod, "_save_disambig_checkpoint", return_value=None),
    ):
        new_state = await disambig_mod._run_final_disambiguation_with_state(
            conn=_DummyConn(),
            state=state,
            full_disambig_client=MagicMock(),
            alias_keywords=["alias"],
            novel_id="novel-1",
            run_id="run-1",
        )

    assert new_state.known_canonical_names == state.known_canonical_names
    assert captured["ensure"] == ("run-1", {"bai_zhi", "hou_fei_bai"}, "novel-1", None)
    assert captured["cleanup"] == "run-1"
    replace_mock.assert_called_once()


@pytest.mark.asyncio
async def test_run_final_disambiguation_with_state_skips_known_canonical_without_review_record() -> None:
    class _DummyConn:
        def commit(self):
            pass

    state = DisambiguationState(
        discovered_names=frozenset({"hou_fei_bai"}),
        known_canonical_names=frozenset({"hou_fei_bai"}),
    )

    with (
        patch.object(pipeline_stages_mod, "AnnotationRepository", MagicMock()),
        patch.object(
            pipeline_stages_mod,
            "fetch_reference_aware_character_names",
            return_value=[{"name": "hou_fei_bai", "count": 12}],
        ),
        patch.object(pipeline_mod, "_retry_disambig") as retry_mock,
        patch.object(pipeline_stages_mod, "_replace_final_disambiguation_chunk_relations", return_value=None),
        patch.object(pipeline_stages_mod, "_save_disambig_checkpoint", return_value=None),
    ):
        new_state = await disambig_mod._run_final_disambiguation_with_state(
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


def test_apply_disambiguation_decisions_removes_stale_alias_merge_on_demotion() -> None:
    state = DisambiguationState(
        discovered_names=frozenset({"masked_person", "bai_zhi"}),
        known_canonical_names=frozenset({"bai_zhi"}),
        alias_merges=frozenset({("masked_person", "bai_zhi")}),
        review_status=(
            (
                "masked_person",
                NameReviewState(
                    status=disambig_mod.DISAMBIG_STATE_RESOLVED,
                    confidence="high",
                    proposed_canonical="bai_zhi",
                    evidence_strength="strong",
                    decision_evidence_count=1,
                    decision_evidence_types=("identity_reveal",),
                ),
            ),
        ),
    )
    result = ExtendedDisambigResult(
        canonical_decisions={"masked_person": "bai_zhi"},
        entity_types={"bai_zhi": "character"},
        entity_relations=[],
        alias_confidence={"masked_person": "medium"},
    )

    new_state = disambig_mod.apply_disambiguation_decisions(state, result)
    review = new_state.get_review_status_dict()["masked_person"]

    assert review.status == disambig_mod.DISAMBIG_STATE_REVIEW
    assert review.proposed_canonical == "bai_zhi"
    assert ("masked_person", "bai_zhi") not in new_state.alias_merges


def test_apply_disambiguation_decisions_keeps_pronoun_self_map_out_of_canonicals() -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 未解析代词 self-map 只能进入 unresolved_references，不能提升为 known_canonical_names。
    """
    result = ExtendedDisambigResult(
        canonical_decisions={"她": "她"},
        entity_types={},
        entity_relations=[],
        alias_confidence={"她": "high"},
        evidence_profiles={"她": EvidenceProfile(strength=EVIDENCE_STRENGTH_STRONG)},
    )

    state = disambig_mod.apply_disambiguation_decisions(DisambiguationState.empty(), result)
    review = state.get_review_status_dict()["她"]

    assert "她" in state.discovered_names
    assert "她" in state.unresolved_references
    assert "她" not in state.known_canonical_names
    assert state.alias_merges == frozenset()
    assert state.reference_resolutions == frozenset()
    assert review.status == disambig_mod.DISAMBIG_STATE_UNRESOLVED
    assert review.proposed_canonical is None


def test_apply_disambiguation_decisions_records_pronoun_to_global_resolution() -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 代词解析到实名时应写入 reference_resolutions，而不是 alias_merges。
    """
    result = ExtendedDisambigResult(
        canonical_decisions={"她": "白芷"},
        entity_types={},
        entity_relations=[],
        alias_confidence={"她": "high"},
        evidence_profiles={"她": EvidenceProfile(strength=EVIDENCE_STRENGTH_STRONG)},
    )

    state = disambig_mod.apply_disambiguation_decisions(DisambiguationState.empty(), result)
    review = state.get_review_status_dict()["她"]

    assert "白芷" in state.known_canonical_names
    assert "她" not in state.known_canonical_names
    assert "她" not in state.unresolved_references
    assert state.get_reference_resolutions_dict() == {"她": "白芷"}
    assert state.alias_merges == frozenset()
    assert review.status == disambig_mod.DISAMBIG_STATE_RESOLVED
    assert review.proposed_canonical == "白芷"


def test_apply_final_disambiguation_result_does_not_promote_unresolved_reference() -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: final review promotion 路径不能把未解析代词提升为 canonical。
    """
    base_state = DisambiguationState(
        discovered_names=frozenset({"她"}),
        unresolved_references=frozenset({"她"}),
        review_status=(
            (
                "她",
                NameReviewState(
                    status=disambig_mod.DISAMBIG_STATE_REVIEW,
                    confidence="high",
                    proposed_canonical=None,
                    evidence_strength="strong",
                ),
            ),
        ),
    )
    result = ExtendedDisambigResult(
        canonical_decisions={},
        entity_types={},
        entity_relations=[],
    )

    new_state = pipeline_stages_mod.apply_final_disambiguation_result(
        base_state,
        result,
        final_global_freq={},
        context_sentences={},
    )

    assert "她" not in new_state.known_canonical_names
    assert "她" in new_state.unresolved_references


def test_disambiguation_state_v3_round_trips_reference_fields() -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: v3 checkpoint 必须同步保存/恢复 unresolved_references 与 reference_resolutions。
    """
    state = DisambiguationState(
        discovered_names=frozenset({"她", "白芷", "你"}),
        known_canonical_names=frozenset({"白芷"}),
        unresolved_references=frozenset({"你"}),
        reference_resolutions=frozenset({("她", "白芷")}),
    )

    restored = DisambiguationState.from_dict(state.to_dict())

    assert restored.version == 3
    assert restored.unresolved_references == frozenset({"你"})
    assert restored.get_reference_resolutions_dict() == {"她": "白芷"}


def test_persist_incremental_checkpoint_applies_reference_resolutions_to_history() -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: reference_resolutions 不能只留在 checkpoint，增量持久化时必须驱动 chunk_* 历史行回写。
    """
    captured: dict[str, object] = {}

    class _DummyAnnRepo:
        def __init__(self, conn) -> None:
            captured["conn"] = conn

        def apply_reference_resolutions_to_history(self, run_id, reference_resolutions):
            captured["apply"] = (run_id, dict(reference_resolutions))
            return {"chunk_characters": 0, "chunk_dialogues": 0, "chunk_relations": 0}

    old_state = DisambiguationState.empty()
    new_state = DisambiguationState(
        known_canonical_names=frozenset({"白芷"}),
        reference_resolutions=frozenset({("她", "白芷")}),
    )

    with (
        patch.object(pipeline_stages_mod, "AnnotationRepository", _DummyAnnRepo),
        patch.object(pipeline_stages_mod, "_save_disambig_checkpoint", return_value=None),
    ):
        pipeline_stages_mod.persist_incremental_checkpoint(object(), "run-1", old_state, new_state)

    assert captured["apply"] == ("run-1", {"她": "白芷"})


def test_extract_new_names_from_db_keeps_reference_candidates_before_global_filter(db_session) -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 消歧候选入口必须保留未解析 reference surface，不能在 fetch_all_character_names 这类 global-only 出口提前蒸发。
    """
    run_id = "run-ref-candidates"
    novel_id = "novref01"
    db_session.add(Novel(novel_id=novel_id, filename="test.txt", file_path="data/test.txt", file_size=128))
    db_session.commit()
    db_session.execute(
        text(
            "INSERT INTO analysis_runs ("
            "run_id, novel_id, source_path, title, status, progress, current, total, "
            "task_kind, cancel_requested, created_at, updated_at"
            ") VALUES (:run_id, :novel_id, 'test', 'Test', 'pending', 0, 0, 1, 'analysis', false, NOW(), NOW())"
        ),
        {"run_id": run_id, "novel_id": novel_id},
    )
    db_session.execute(
        text(
            "INSERT INTO chunks (chunk_id, run_id, text, chapter_id, char_offset, char_end_offset) "
            "VALUES (1, :run_id, '她看向白芷。', NULL, NULL, NULL)"
        ),
        {"run_id": run_id},
    )
    db_session.add_all(
        [
            ChunkCharacter(
                chunk_id=1,
                run_id=run_id,
                name="她",
                surface_name="她",
                reference_kind="pronoun",
                reference_slot="LOCAL_REF_C1_她",
                resolved_global_name=None,
                global_skip_reason="unresolved pronoun reference",
                role_function="主体",
                action="看向",
                action_type="其他",
                emotion_score="neutral",
            ),
            ChunkCharacter(
                chunk_id=1,
                run_id=run_id,
                name="白芷",
                surface_name="白芷",
                reference_kind="global_character",
                reference_slot=None,
                resolved_global_name="白芷",
                global_skip_reason=None,
                role_function="客体",
                action="被看向",
                action_type="其他",
                emotion_score="neutral",
            ),
        ]
    )
    db_session.commit()

    new_names = extract_new_names_from_db(db_session, {}, run_id, current_chunk_id=1)
    global_names = fetch_all_character_names(db_session, run_id, max_chunk_id=1)

    assert {item["name"] for item in new_names} == {"她", "白芷"}
    assert {item["name"] for item in global_names} == {"白芷"}


def test_fetch_reference_aware_character_names_keeps_name_count_contract(db_session) -> None:
    """
    创建时间: 2026-04-29
    任务: 验证 reference-aware 候选查询替换兼容性
    新建原因: `fetch_reference_aware_character_names()` 替换旧查询入口后，仍需稳定返回调用方期望的
              `{\"name\": str, \"count\": int}` 结构，避免 `extract_new_names_from_db()` / final candidate 组装断约。
    """
    run_id = "run-ref-contract"
    novel_id = "novref02"
    db_session.add(Novel(novel_id=novel_id, filename="test.txt", file_path="data/test.txt", file_size=128))
    db_session.commit()
    db_session.execute(
        text(
            "INSERT INTO analysis_runs ("
            "run_id, novel_id, source_path, title, status, progress, current, total, "
            "task_kind, cancel_requested, created_at, updated_at"
            ") VALUES (:run_id, :novel_id, 'test', 'Test', 'pending', 0, 0, 1, 'analysis', false, NOW(), NOW())"
        ),
        {"run_id": run_id, "novel_id": novel_id},
    )
    db_session.execute(
        text(
            "INSERT INTO chunks (chunk_id, run_id, text, chapter_id, char_offset, char_end_offset) "
            "VALUES (1, :run_id, '她看向白芷。', NULL, NULL, NULL)"
        ),
        {"run_id": run_id},
    )
    db_session.add_all(
        [
            ChunkCharacter(
                chunk_id=1,
                run_id=run_id,
                name="她",
                surface_name="她",
                reference_kind="pronoun",
                reference_slot="LOCAL_REF_C1_她",
                resolved_global_name=None,
                global_skip_reason="unresolved pronoun reference",
                role_function="主体",
                action="看向",
                action_type="其他",
                emotion_score="neutral",
            ),
            ChunkCharacter(
                chunk_id=1,
                run_id=run_id,
                name="白芷",
                surface_name="白芷",
                reference_kind="global_character",
                reference_slot=None,
                resolved_global_name="白芷",
                global_skip_reason=None,
                role_function="客体",
                action="被看向",
                action_type="其他",
                emotion_score="neutral",
            ),
        ]
    )
    db_session.commit()

    all_names = fetch_reference_aware_character_names(db_session, run_id, max_chunk_id=1)

    assert all(set(item.keys()) == {"name", "count"} for item in all_names)
    assert all(isinstance(item["name"], str) for item in all_names)
    assert all(isinstance(item["count"], int) for item in all_names)
    assert {item["name"] for item in all_names} == {"她", "白芷"}
