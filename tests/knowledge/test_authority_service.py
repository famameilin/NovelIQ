from __future__ import annotations

import uuid

from src.knowledge.authority import KnowledgeGraphAuthorityService
from src.storage.repositories import GraphRepository, RunRepository


def test_build_timeline_view_only_exposes_character_subgraph_and_break_events(db_session) -> None:
    novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Timeline Authority View",
    )

    graph_repo = GraphRepository(db_session)
    protagonist = graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name="叶青",
        entity_type="character",
        first_seen_chunk=1,
        last_seen_chunk=8,
    )
    rival = graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name="沈昭",
        entity_type="character",
        first_seen_chunk=2,
        last_seen_chunk=9,
    )
    sect = graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name="玄霄宗",
        entity_type="organization",
        first_seen_chunk=1,
        last_seen_chunk=9,
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=protagonist.entity_id,
        to_entity_id=rival.entity_id,
        relation_type="盟友",
        change_type="断裂",
        chunk_id=9,
        evidence="二人决裂",
        confidence=0.81,
        source_relation_row_id=12001,
        directionality="directed",
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=protagonist.entity_id,
        to_entity_id=sect.entity_id,
        relation_type="归属",
        change_type="新建",
        chunk_id=3,
        evidence="加入宗门",
        confidence=0.95,
        source_relation_row_id=12002,
        directionality="directed",
    )
    db_session.commit()

    view = KnowledgeGraphAuthorityService.from_session(db_session).build_timeline_view(run_id)

    assert {entity.name for entity in view.character_entities} == {"叶青", "沈昭"}
    assert {(event.from_name, event.to_name, event.change_type) for event in view.relation_events} == {
        ("叶青", "沈昭", "断裂")
    }
    assert {(item.name, item.first_seen_chunk, item.last_seen_chunk) for item in view.entity_lifecycles} == {
        ("叶青", 1, 8),
        ("沈昭", 2, 9),
    }


def test_build_graph_view_exposes_stable_states_without_transient_local_context(db_session) -> None:
    novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Authority View",
    )

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name="周渡",
        entity_type="character",
        first_seen_chunk=1,
        last_seen_chunk=6,
        primary_role_function="protagonist",
        last_emotion_score="angry",
        last_action="拔刀",
        source_confidence=0.88,
    )
    ally = graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name="顾霜",
        entity_type="character",
        first_seen_chunk=2,
        last_seen_chunk=6,
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=ally.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=4,
        evidence="联手破阵",
        confidence=0.93,
        source_relation_row_id=13001,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, ally.entity_id)
    db_session.commit()

    view = KnowledgeGraphAuthorityService.from_session(db_session).build_graph_view(run_id)

    assert {(state.name, state.primary_role_function, state.status) for state in view.stable_states} == {
        ("周渡", "protagonist", "active"),
        ("顾霜", None, "active"),
    }
    assert all(not hasattr(state, "last_action") for state in view.stable_states)
    assert all(not hasattr(state, "last_emotion_score") for state in view.stable_states)
    assert view.summary["node_count"] == 2
    assert "quality" in view.summary


def test_build_level1_snapshot_keeps_inactive_relations_outside_confirmed_relations(db_session) -> None:
    novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Level1 Snapshot",
    )

    graph_repo = GraphRepository(db_session)
    han_li = graph_repo.upsert_entity(run_id=run_id, canonical_name="韩立", first_seen_chunk=1, last_seen_chunk=7)
    nan_gong = graph_repo.upsert_entity(run_id=run_id, canonical_name="南宫婉", first_seen_chunk=1, last_seen_chunk=7)
    graph_repo.upsert_alias(
        run_id=run_id,
        entity_id=han_li.entity_id,
        alias="韩道友",
        source_chunk_id=1,
        evidence="称呼",
        confidence=0.9,
        source_type="named",
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=han_li.entity_id,
        to_entity_id=nan_gong.entity_id,
        relation_type="爱慕",
        change_type="新建",
        chunk_id=3,
        evidence="暗生情愫",
        confidence=0.8,
        source_relation_row_id=14001,
        directionality="directed",
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=han_li.entity_id,
        to_entity_id=nan_gong.entity_id,
        relation_type="爱慕",
        change_type="断裂",
        chunk_id=7,
        evidence="关系断裂",
        confidence=0.75,
        source_relation_row_id=14002,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, han_li.entity_id, nan_gong.entity_id)
    db_session.commit()

    service = KnowledgeGraphAuthorityService.from_session(db_session)
    snapshot = service.build_level1_snapshot(run_id)
    graph_view = service.build_graph_view(run_id)

    assert ("韩立", "韩立") in {(item.alias, item.canonical) for item in snapshot.alias_mappings}
    assert snapshot.confirmed_relations == []
    assert {(event.from_name, event.to_name, event.change_type) for event in graph_view.relation_events} == {
        ("韩立", "南宫婉", "断裂"),
        ("韩立", "南宫婉", "新建"),
    }
