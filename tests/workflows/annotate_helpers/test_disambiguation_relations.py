from __future__ import annotations

import uuid

from src.chunking.chunker import Chunk
from src.models.local.disambiguation import DisambiguationState, ExtendedDisambigResult
from src.storage.models import Novel
from src.storage.repositories import AnnotationRepository, ChunkRepository, GraphRepository, RunRepository
from src.workflows.annotate_helpers.disambiguation.pipeline_stages import persist_final_disambiguation
from src.workflows.annotate_helpers.disambiguation.relations import _process_entity_relations
from src.workflows.annotate_helpers.graph_projection import project_graph_tables


def _create_relation_write_test_run(db_session) -> str:
    """
    2026-04-27，任务：graph readiness consistency fixes
    新建原因：终消歧关系写链测试需要真实 run/chunk 外键环境，避免只测到 mock 而漏掉图谱表约束。
    """
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
    ChunkRepository(db_session).insert_chunks(run_id, [Chunk(index=0, text="测试文本", start=0, end=4)])
    return run_id


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
        entity_relations=[{"from": "阿顾", "to": "苏镜", "type": "盟友"}],
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
        frozenset({"顾霜", "苏镜"}),
        novel_id="novel-1",
        entity_types={"顾霜": "character", "苏镜": "character"},
    )

    state = DisambiguationState(
        known_canonical_names=frozenset({"顾霜", "苏镜"}),
    )
    result = ExtendedDisambigResult(
        canonical_decisions={},
        entity_types={"顾霜": "character", "苏镜": "character"},
        entity_relations=[{"from": "阿顾", "to": "苏镜", "type": "盟友"}],
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

    project_graph_tables(run_id=run_id, to_chunk=0, session=db_session, rebuild=True)

    graph_repo = GraphRepository(db_session)
    current_relations = graph_repo.fetch_current_relations(run_id, active_only=False)
    relation_events = graph_repo.fetch_relation_events(run_id)

    assert len(current_relations) == 1
    assert current_relations[0].from_name == "顾霜"
    assert current_relations[0].to_name == "苏镜"
    assert len(relation_events) == 1
    assert relation_events[0].from_name == "顾霜"
    assert relation_events[0].to_name == "苏镜"
