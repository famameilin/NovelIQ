from __future__ import annotations

import uuid

import pytest

from src.chunking.chunker import Chunk
from src.models.local.disambiguation import DisambiguationState, ExtendedDisambigResult
from src.storage.models import ChunkCharacter, ChunkRelation, Novel
from src.storage.repositories import AnnotationRepository, ChunkRepository, GraphRepository, RunRepository
from src.storage.repositories.annotation.characters import fetch_relation_reference_candidates
from src.workflows.annotate_helpers.disambiguation.pipeline_stages import (
    persist_final_disambiguation,
    plan_final_disambiguation,
    plan_incremental_disambiguation,
)
from src.workflows.annotate_helpers.disambiguation.relations import _process_entity_relations
from src.workflows.annotate_helpers.graph_projection import project_graph_tables


def _create_relation_write_test_run(db_session, chunk_texts: list[str] | None = None) -> str:
    """
    2026-04-27，任务：graph readiness consistency fixes
    新建原因：终消歧关系写链测试需要真实 run/chunk 外键环境，避免只测到 mock 而漏掉图谱表约束。
    修改时间：2026-05-02
    任务：fix-graph-projection-relations
    修改原因：relation-only endpoint 消歧测试需要自定义 chunk 原文，
    因此这里扩成可注入文本的通用 run/chunk 构造器，避免重复搭测试环境。
    """
    chunk_texts = chunk_texts or ["测试文本-0", "测试文本-1", "测试文本-2"]
    novel_id = uuid.uuid4().hex[:8]
    db_session.add(
        Novel(
            novel_id=novel_id,
            filename="disambiguation-relations.txt",
            file_path="tests/disambiguation-relations.txt",
            title="Disambiguation Relations",
            file_size=128,
        )
    )
    db_session.commit()

    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Disambiguation Relations",
    )
    ChunkRepository(db_session).insert_chunks(
        run_id,
        [
            Chunk(index=index, text=text, start=index * 5, end=index * 5 + max(len(text) - 1, 0))
            for index, text in enumerate(chunk_texts)
        ],
    )
    return run_id


def _seed_relation_endpoint(
    db_session,
    *,
    run_id: str,
    chunk_id: int,
    from_char: str,
    to_char: str,
    evidence: str,
    add_character_slot: str | None = None,
) -> None:
    """
    创建时间：2026-05-02
    任务：fix-graph-projection-relations
    新建原因：relation-only endpoint 相关测试需要稳定写入 unresolved chunk_relations，
    同时部分场景要模拟“同一 slot 已经走过 chunk_characters 入口”的重复边界。
    """
    db_session.add(
        ChunkRelation(
            chunk_id=chunk_id,
            run_id=run_id,
            from_char=from_char,
            to_char=to_char,
            from_reference_kind=(
                "pov_slot" if from_char == "我" else ("generic_reference" if "REF" in from_char else "global_character")
            ),
            to_reference_kind=(
                "pov_slot"
                if to_char == "我"
                else (
                    "generic_reference"
                    if "REF" in to_char or to_char in {"他", "他们", "它"}
                    else "global_character"
                )
            ),
            resolved_from_global_name=None,
            resolved_to_global_name=None,
            reference_skip_reason="unresolved global-character endpoint",
            type="观察",
            change="新建",
            directionality="directed",
            evidence=evidence,
            confidence=1.0,
            source_model="phase4",
            projection_status="pending",
        )
    )
    if add_character_slot:
        db_session.add(
            ChunkCharacter(
                chunk_id=chunk_id,
                run_id=run_id,
                name=add_character_slot.rsplit("_", 1)[-1],
                surface_name=add_character_slot.rsplit("_", 1)[-1],
                reference_kind="generic_reference",
                reference_slot=add_character_slot,
                resolved_global_name=None,
                global_skip_reason="unresolved generic reference",
                role_function="客体",
                action="被提及",
                action_type="其他",
                emotion_score="neutral",
            )
        )
    db_session.commit()


def test_process_entity_relations_skips_self_loop_after_alias_resolution(db_session) -> None:
    run_id = _create_relation_write_test_run(db_session)

    success_count, skipped_relations = _process_entity_relations(
        db_session,
        novel_id="novel-1",
        run_id=run_id,
        entity_relations=[{"from": "阿顾", "to": "顾霜", "type": "盟友"}],
        entity_types={"顾霜": "character", "阿顾": "character"},
        alias_map={"阿顾": "顾霜"},
    )

    graph_repo = GraphRepository(db_session)

    assert success_count == 0
    assert skipped_relations == [
        {
            "relation": {"from": "阿顾", "to": "顾霜", "type": "盟友"},
            "reason": "self_loop_after_alias_resolution",
        }
    ]
    assert graph_repo.fetch_relation_events(run_id) == []
    assert graph_repo.fetch_current_relations(run_id, active_only=False) == []
    assert graph_repo.fetch_participant_entities(run_id) == []


def test_process_entity_relations_uses_shared_change_type_and_refreshes_projections(db_session) -> None:
    run_id = _create_relation_write_test_run(db_session)

    success_count, skipped_relations = _process_entity_relations(
        db_session,
        novel_id="novel-1",
        run_id=run_id,
        entity_relations=[{"from": "阿顾", "to": "苏镜", "type": "father_of"}],
        entity_types={"顾霜": "character", "苏镜": "character", "阿顾": "character"},
        alias_map={"阿顾": "顾霜"},
    )

    graph_repo = GraphRepository(db_session)
    relation_events = graph_repo.fetch_relation_events(run_id)
    current_relations = graph_repo.fetch_current_relations(run_id, active_only=False)
    participants = {participant.name: participant for participant in graph_repo.fetch_participant_entities(run_id)}

    assert success_count == 1
    assert skipped_relations == []
    assert len(relation_events) == 1
    assert relation_events[0].change_type == "新建"
    assert len(current_relations) == 1
    assert current_relations[0].from_name == "顾霜"
    assert current_relations[0].to_name == "苏镜"
    assert set(participants.keys()) == {"顾霜", "苏镜"}
    assert participants["顾霜"].current_degree == 1
    assert participants["苏镜"].current_degree == 1


def test_persist_final_disambiguation_relations_survive_graph_rebuild(db_session) -> None:
    run_id = _create_relation_write_test_run(db_session)

    ann_repo = AnnotationRepository(db_session)
    ann_repo.ensure_canonical_entities(
        run_id,
        frozenset({"顾霜", "苏镜", "贺家"}),
        novel_id="novel-1",
        entity_types={"顾霜": "character", "苏镜": "character", "贺家": "organization"},
    )

    state = DisambiguationState(
        known_canonical_names=frozenset({"顾霜", "苏镜", "贺家"}),
    )
    result = ExtendedDisambigResult(
        canonical_decisions={},
        entity_types={"顾霜": "character", "苏镜": "character", "贺家": "organization"},
        entity_relations=[{"from": "阿顾", "to": "贺家", "type": "belongs_to"}],
        alias_confidence={},
    )
    persisted_state = persist_final_disambiguation(
        db_session,
        novel_id="novel-1",
        run_id=run_id,
        previous_state=state,
        new_state=state.with_updates(alias_merges=frozenset({("阿顾", "顾霜")})),
        pending_relations=[],
        result=result,
    )
    assert persisted_state.pending_relations == ()

    project_graph_tables(run_id=run_id, to_chunk=2, session=db_session, rebuild=True)

    graph_repo = GraphRepository(db_session)
    current_relations = graph_repo.fetch_current_relations(run_id, active_only=False)
    relation_events = graph_repo.fetch_relation_events(run_id)

    assert len(current_relations) == 1
    assert current_relations[0].from_name == "顾霜"
    assert current_relations[0].to_name == "贺家"
    assert relation_events == []


def test_fetch_relation_reference_candidates_builds_slot_keys_for_unresolved_relation_endpoints(db_session) -> None:
    """
    创建时间：2026-05-02
    任务：fix-graph-projection-relations
    新建原因：relation-only endpoint 必须以 slot key 进入消歧候选，
    不能继续把“我/他”这类裸 surface 直接送进候选列表。
    """
    run_id = _create_relation_write_test_run(
        db_session,
        chunk_texts=["我看着他，没有继续说下去。", "测试文本-1", "测试文本-2"],
    )
    _seed_relation_endpoint(
        db_session,
        run_id=run_id,
        chunk_id=0,
        from_char="我",
        to_char="LOCAL_REF_C0_他",
        evidence="我看着他，没有继续说下去。",
    )

    candidates = fetch_relation_reference_candidates(db_session, run_id, max_chunk_id=0)

    assert {item["name"] for item in candidates} == {"POV_SLOT_C0_我", "LOCAL_REF_C0_他"}


def test_fetch_relation_reference_candidates_skips_slots_already_present_in_chunk_characters(db_session) -> None:
    """
    创建时间：2026-05-02
    任务：fix-graph-projection-relations
    新建原因：这条补充入口只负责 relation-only endpoint；
    若同一 slot 已经出现在 chunk_characters，就不应再重复以 slot 形态进入消歧。
    """
    run_id = _create_relation_write_test_run(
        db_session,
        chunk_texts=["叶文洁注视着他们，没有继续开口。", "测试文本-1", "测试文本-2"],
    )
    _seed_relation_endpoint(
        db_session,
        run_id=run_id,
        chunk_id=0,
        from_char="叶文洁",
        to_char="LOCAL_REF_C0_他们",
        evidence="叶文洁注视着他们，没有继续开口。",
        add_character_slot="LOCAL_REF_C0_他们",
    )

    candidates = fetch_relation_reference_candidates(db_session, run_id, max_chunk_id=0)

    assert candidates == []


@pytest.mark.asyncio
async def test_plan_incremental_disambiguation_includes_relation_only_slot_candidate(
    db_session,
) -> None:
    """
    创建时间：2026-05-02
    任务：fix-graph-projection-relations
    新建原因：增量消歧不仅要收进 relation-only slot 候选，
    还要给模型提供 surface + chunk + 关系证据 + 原文的可读上下文。
    """
    run_id = _create_relation_write_test_run(
        db_session,
        chunk_texts=["叶文洁注视着他们，没有继续开口。", "测试文本-1", "测试文本-2"],
    )
    _seed_relation_endpoint(
        db_session,
        run_id=run_id,
        chunk_id=0,
        from_char="叶文洁",
        to_char="LOCAL_REF_C0_他们",
        evidence="叶文洁注视着他们，没有继续开口。",
    )
    state = DisambiguationState(
        discovered_names=frozenset({"叶文洁"}),
        known_canonical_names=frozenset({"叶文洁"}),
    )

    plan = await plan_incremental_disambiguation(
        db_session,
        state,
        alias_keywords=["叫作"],
        run_id=run_id,
        chunk_id=0,
        disambig_interval=1,
        evidence_service=None,
    )

    assert plan is not None
    assert [item["name"] for item in plan.candidate_payload] == ["LOCAL_REF_C0_他们"]
    assert "LOCAL_REF_C0_他们" in plan.context_sentences
    context = plan.context_sentences["LOCAL_REF_C0_他们"]
    assert "原文称呼：他们" in context
    assert "chunk 0" in context
    assert "关系证据：叶文洁注视着他们，没有继续开口。" in context
    assert "分块原文：叶文洁注视着他们，没有继续开口。" in context


def test_plan_final_disambiguation_includes_relation_only_slot_candidate_with_readable_context(db_session) -> None:
    """
    创建时间：2026-05-02
    任务：fix-graph-projection-relations
    新建原因：终态消歧也必须复用同一批 relation-only slot 候选和可读上下文，
    否则增量 deferred / 终态补收敛两条链路会重新分叉。
    """
    run_id = _create_relation_write_test_run(
        db_session,
        chunk_texts=["叶文洁注视着他们，没有继续开口。", "测试文本-1", "测试文本-2"],
    )
    _seed_relation_endpoint(
        db_session,
        run_id=run_id,
        chunk_id=0,
        from_char="叶文洁",
        to_char="LOCAL_REF_C0_他们",
        evidence="叶文洁注视着他们，没有继续开口。",
    )
    state = DisambiguationState(
        discovered_names=frozenset({"叶文洁"}),
        known_canonical_names=frozenset({"叶文洁"}),
    )

    plan = plan_final_disambiguation(
        db_session,
        state,
        alias_keywords=["叫作"],
        run_id=run_id,
    )

    assert plan is not None
    assert [item["name"] for item in plan.candidate_payload] == ["LOCAL_REF_C0_他们"]
    assert "LOCAL_REF_C0_他们" in plan.context_sentences
    context = plan.context_sentences["LOCAL_REF_C0_他们"]
    assert "原文称呼：他们" in context
    assert "chunk 0" in context
    assert "关系证据：叶文洁注视着他们，没有继续开口。" in context
    assert "分块原文：叶文洁注视着他们，没有继续开口。" in context
