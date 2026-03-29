from __future__ import annotations

import uuid

from src.knowledge import build_networkx_from_graph_tables
from src.storage.repositories import GraphRepository, RunRepository


def test_build_networkx_from_graph_tables_builds_graph(db_session) -> None:
    novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Test Novel",
    )
    graph_repo = GraphRepository(db_session)
    a = graph_repo.upsert_entity(run_id=run_id, canonical_name="方源", first_seen_chunk=1, last_seen_chunk=1)
    b = graph_repo.upsert_entity(run_id=run_id, canonical_name="白凝冰", first_seen_chunk=1, last_seen_chunk=1)
    event = graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=a.entity_id,
        to_entity_id=b.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=10,
        evidence="并肩",
        confidence=0.9,
        source_relation_row_id=3001,
        directionality="directed",
    )
    assert event is not None
    graph_repo.refresh_current_relation(run_id, a.entity_id, b.entity_id)
    db_session.commit()

    graph = build_networkx_from_graph_tables(run_id, session=db_session)

    assert graph.number_of_nodes() == 2
    assert graph.number_of_edges() == 1
    assert graph.nodes[a.entity_id]["name"] == "方源"
    assert graph.nodes[b.entity_id]["name"] == "白凝冰"


def test_build_networkx_from_graph_tables_respects_active_only(db_session) -> None:
    novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Test Novel",
    )
    graph_repo = GraphRepository(db_session)
    a = graph_repo.upsert_entity(run_id=run_id, canonical_name="叶凡", first_seen_chunk=1, last_seen_chunk=1)
    b = graph_repo.upsert_entity(run_id=run_id, canonical_name="姬紫月", first_seen_chunk=1, last_seen_chunk=1)

    first_event = graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=a.entity_id,
        to_entity_id=b.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=5,
        evidence="联手",
        confidence=0.9,
        source_relation_row_id=4001,
        directionality="directed",
    )
    assert first_event is not None
    second_event = graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=a.entity_id,
        to_entity_id=b.entity_id,
        relation_type="敌对",
        change_type="断裂",
        chunk_id=6,
        evidence="决裂",
        confidence=0.8,
        source_relation_row_id=4002,
        directionality="directed",
    )
    assert second_event is not None
    graph_repo.refresh_current_relation(run_id, a.entity_id, b.entity_id)
    db_session.commit()

    active_graph = build_networkx_from_graph_tables(run_id, active_only=True, session=db_session)
    full_graph = build_networkx_from_graph_tables(run_id, active_only=False, session=db_session)

    assert active_graph.number_of_nodes() == 2
    assert active_graph.number_of_edges() == 0
    assert full_graph.number_of_edges() == 1
