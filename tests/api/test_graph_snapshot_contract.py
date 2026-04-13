from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from src.api.routes.results_fetchers import _fetch_graph_snapshot
from src.storage.repositories import GraphRepository, RunRepository


def test_fetch_graph_snapshot_preserves_contract_shape(db_session) -> None:
    novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Snapshot Contract",
    )

    graph_repo = GraphRepository(db_session)
    bo_an = graph_repo.upsert_entity(run_id=run_id, canonical_name="贺伯安", first_seen_chunk=1, last_seen_chunk=6)
    liu_wan = graph_repo.upsert_entity(run_id=run_id, canonical_name="柳婉儿", first_seen_chunk=2, last_seen_chunk=8)
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=bo_an.entity_id,
        to_entity_id=liu_wan.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=6,
        evidence="共同应敌",
        confidence=0.91,
        source_relation_row_id=9201,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, bo_an.entity_id, liu_wan.entity_id)
    db_session.commit()

    annotation_repo = MagicMock()
    annotation_repo.session = db_session
    annotation_repo.fetch_pending_chunk_relations.return_value = []

    snapshot = _fetch_graph_snapshot(run_id, annotation_repo)

    assert set(snapshot.keys()) == {"nodes", "edges", "events", "summary", "quality"}
    assert len(snapshot["nodes"]) == 2
    assert len(snapshot["edges"]) == 1
    assert len(snapshot["events"]) == 1
    assert "quality" not in snapshot["summary"]
    assert "recent_events" not in snapshot["summary"]
    assert set(snapshot["quality"].keys()) == {
        "conflict_count",
        "low_confidence_count",
        "conflicts",
        "low_confidence_samples",
    }

    node = snapshot["nodes"][0]
    # GraphAuthorityView nodes now expose stable state only; transient emotion no longer belongs to the contract.
    assert set(node.keys()) == {
        "entity_id",
        "name",
        "entity_type",
        "first_seen_chunk",
        "last_seen_chunk",
        "role",
        "status",
    }
    assert "emotion_score" not in node


def test_fetch_graph_snapshot_summary_counts_only_reflect_active_edges(db_session) -> None:
    novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Snapshot Summary Contract",
    )

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="贺伯安", first_seen_chunk=1, last_seen_chunk=8)
    rival = graph_repo.upsert_entity(run_id=run_id, canonical_name="柳婉儿", first_seen_chunk=2, last_seen_chunk=8)
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=rival.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=3,
        evidence="联手查案",
        confidence=0.88,
        source_relation_row_id=9301,
        directionality="directed",
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=rival.entity_id,
        relation_type="盟友",
        change_type="断裂",
        chunk_id=8,
        evidence="分道扬镳",
        confidence=0.57,
        source_relation_row_id=9302,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, rival.entity_id)
    db_session.commit()

    annotation_repo = MagicMock()
    annotation_repo.session = db_session
    annotation_repo.fetch_pending_chunk_relations.return_value = []

    snapshot = _fetch_graph_snapshot(run_id, annotation_repo)

    assert snapshot["edges"] == []
    assert snapshot["summary"]["edge_count"] == 0
    assert snapshot["quality"]["low_confidence_count"] == 1
    assert {(event["from_name"], event["to_name"], event["change_type"]) for event in snapshot["events"]} == {
        ("贺伯安", "柳婉儿", "断裂"),
        ("贺伯安", "柳婉儿", "新建"),
    }
