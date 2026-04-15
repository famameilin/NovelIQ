from __future__ import annotations

import base64
import json
import uuid
from unittest.mock import MagicMock

import pytest

from src.api.routes.results_fetchers import _fetch_graph_events_page, _fetch_graph_snapshot
from src.knowledge.authority import ConfirmedRelation, GraphAuthorityView, RelationEvent, StableState
from src.storage.repositories import GraphRepository, RunRepository
from tests.support.timeline_contract_helpers import create_timeline_contract_scenario


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

    assert set(snapshot.keys()) == {"nodes", "edges", "events", "events_page", "summary", "quality"}
    assert len(snapshot["nodes"]) == 2
    assert len(snapshot["edges"]) == 1
    assert len(snapshot["events"]) == 1
    assert snapshot["events_page"] == {
        "limit": 200,
        "returned_count": 1,
        "total": 1,
        "has_more": False,
        "next_cursor": None,
    }
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


def test_fetch_graph_snapshot_keeps_page_summary_in_product_layer(monkeypatch) -> None:
    class FakeAuthorityService:
        def build_graph_view(self, run_id: str) -> GraphAuthorityView:
            assert run_id == "run-graph-page"
            return GraphAuthorityView(
                stable_states=[
                    StableState(entity_id=1, name="沈砚", entity_type="character", last_seen_chunk=8),
                    StableState(entity_id=2, name="陆明", entity_type="character", last_seen_chunk=6),
                ],
                confirmed_relations=[
                    ConfirmedRelation(
                        from_name="沈砚",
                        to_name="陆明",
                        relation_type="盟友",
                        from_entity_id=1,
                        to_entity_id=2,
                        support_count=3,
                        last_seen_chunk=6,
                    )
                ],
                relation_events=[
                    RelationEvent(
                        relation_event_id=11,
                        chunk_id=6,
                        from_entity_id=1,
                        to_entity_id=2,
                        from_name="沈砚",
                        to_name="陆明",
                        relation_type="盟友",
                        change_type="新建",
                        confidence=0.55,
                    )
                ],
            )

        def build_graph_report(self, *_args, **_kwargs):
            raise AssertionError("/graph page should not consume diagnosis/export graph report")

    monkeypatch.setattr(
        "src.api.routes.results_fetchers.fetchers.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: FakeAuthorityService(),
    )

    annotation_repo = MagicMock()
    annotation_repo.session = object()
    annotation_repo.fetch_pending_chunk_relations.return_value = []

    snapshot = _fetch_graph_snapshot("run-graph-page", annotation_repo)

    assert snapshot["summary"] == {
        "node_count": 2,
        "edge_count": 1,
        "density": 0.5,
        "core_characters": ["沈砚", "陆明"],
        "key_relations": [{"from": "沈砚", "to": "陆明", "type": "盟友", "support_count": 3}],
    }
    assert snapshot["quality"]["conflict_count"] == 0
    assert snapshot["quality"]["low_confidence_count"] == 1
    assert snapshot["quality"]["low_confidence_samples"][0]["relation_event_id"] == 11
    assert snapshot["events_page"] == {
        "limit": 200,
        "returned_count": 1,
        "total": 1,
        "has_more": False,
        "next_cursor": None,
    }


def test_fetch_graph_snapshot_quality_counts_full_history_but_caps_page_events(monkeypatch) -> None:
    class FakeAuthorityService:
        def build_graph_view(self, run_id: str) -> GraphAuthorityView:
            assert run_id == "run-graph-quality"
            relation_events = [
                RelationEvent(
                    relation_event_id=index + 1,
                    chunk_id=500 - index,
                    from_entity_id=1,
                    to_entity_id=2,
                    from_name="沈砚",
                    to_name="陆明",
                    relation_type="盟友",
                    change_type="波动",
                    confidence=0.55,
                )
                for index in range(205)
            ]
            return GraphAuthorityView(
                stable_states=[
                    StableState(entity_id=1, name="沈砚", entity_type="character", last_seen_chunk=500),
                    StableState(entity_id=2, name="陆明", entity_type="character", last_seen_chunk=499),
                ],
                confirmed_relations=[
                    ConfirmedRelation(
                        from_name="沈砚",
                        to_name="陆明",
                        relation_type="盟友",
                        from_entity_id=1,
                        to_entity_id=2,
                        support_count=205,
                        last_seen_chunk=500,
                    )
                ],
                relation_events=relation_events,
            )

        def build_graph_report(self, *_args, **_kwargs):
            raise AssertionError("/graph page should not consume diagnosis/export graph report")

    monkeypatch.setattr(
        "src.api.routes.results_fetchers.fetchers.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: FakeAuthorityService(),
    )

    annotation_repo = MagicMock()
    annotation_repo.session = object()
    annotation_repo.fetch_pending_chunk_relations.return_value = []

    snapshot = _fetch_graph_snapshot("run-graph-quality", annotation_repo)

    assert len(snapshot["events"]) == 200
    assert snapshot["events"][0]["relation_event_id"] == 1
    assert snapshot["events"][-1]["relation_event_id"] == 200
    assert snapshot["events_page"]["returned_count"] == 200
    assert snapshot["events_page"]["total"] == 205
    assert snapshot["events_page"]["has_more"] is True
    assert snapshot["events_page"]["next_cursor"] is not None
    assert snapshot["quality"]["low_confidence_count"] == 205
    assert len(snapshot["quality"]["low_confidence_samples"]) == 5
    assert snapshot["quality"]["low_confidence_samples"][0]["relation_event_id"] == 1


def test_fetch_graph_events_page_uses_cursor_for_incremental_history(monkeypatch) -> None:
    class FakeAuthorityService:
        def build_graph_view(self, run_id: str) -> GraphAuthorityView:
            assert run_id == "run-graph-events-page"
            relation_events = [
                RelationEvent(
                    relation_event_id=index + 1,
                    chunk_id=500 - index,
                    from_entity_id=1,
                    to_entity_id=2,
                    from_name="沈砚",
                    to_name="陆明",
                    relation_type="盟友",
                    change_type="波动",
                    confidence=0.55,
                )
                for index in range(205)
            ]
            return GraphAuthorityView(
                stable_states=[],
                confirmed_relations=[],
                relation_events=relation_events,
            )

        def build_graph_report(self, *_args, **_kwargs):
            raise AssertionError("graph events pagination should not depend on graph report")

    monkeypatch.setattr(
        "src.api.routes.results_fetchers.fetchers.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: FakeAuthorityService(),
    )

    annotation_repo = MagicMock()
    annotation_repo.session = object()
    annotation_repo.fetch_pending_chunk_relations.return_value = []

    snapshot = _fetch_graph_snapshot("run-graph-events-page", annotation_repo)
    next_cursor = snapshot["events_page"]["next_cursor"]

    page = _fetch_graph_events_page(
        "run-graph-events-page",
        annotation_repo,
        events_cursor=next_cursor,
    )

    assert [event["relation_event_id"] for event in page["events"]] == [201, 202, 203, 204, 205]
    assert page["page_info"] == {
        "limit": 200,
        "returned_count": 5,
        "total": 205,
        "has_more": False,
        "next_cursor": None,
    }


@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64",
        base64.urlsafe_b64encode(json.dumps({"offset": True}).encode("utf-8")).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(json.dumps({"offset": False}).encode("utf-8")).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(json.dumps({"offset": "1"}).encode("utf-8")).decode("ascii").rstrip("="),
    ],
)
def test_fetch_graph_events_page_rejects_invalid_cursor_payloads(monkeypatch, cursor: str) -> None:
    class FakeAuthorityService:
        def build_graph_view(self, run_id: str) -> GraphAuthorityView:
            assert run_id == "run-invalid-graph-cursor"
            return GraphAuthorityView(
                stable_states=[],
                confirmed_relations=[],
                relation_events=[
                    RelationEvent(
                        relation_event_id=1,
                        chunk_id=3,
                        from_entity_id=1,
                        to_entity_id=2,
                        from_name="沈砚",
                        to_name="陆明",
                        relation_type="盟友",
                        change_type="新建",
                        confidence=0.8,
                    )
                ],
            )

    monkeypatch.setattr(
        "src.api.routes.results_fetchers.fetchers.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: FakeAuthorityService(),
    )

    annotation_repo = MagicMock()
    annotation_repo.session = object()
    annotation_repo.fetch_pending_chunk_relations.return_value = []

    with pytest.raises(ValueError, match="invalid graph events cursor"):
        _fetch_graph_events_page(
            "run-invalid-graph-cursor",
            annotation_repo,
            events_cursor=cursor,
        )


def test_get_graph_events_invalid_cursor_returns_400(api_client, db_session) -> None:
    scenario = create_timeline_contract_scenario(db_session)

    response = api_client.get(
        f"/api/novels/{scenario.novel_id}/graph/events",
        params={"task_id": scenario.task_id, "events_cursor": "not-base64"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid graph events cursor"


def test_get_graph_events_out_of_range_cursor_returns_400(api_client, db_session) -> None:
    scenario = create_timeline_contract_scenario(db_session)
    out_of_range_cursor = base64.urlsafe_b64encode(json.dumps({"offset": 99}).encode("utf-8")).decode("ascii").rstrip(
        "="
    )

    response = api_client.get(
        f"/api/novels/{scenario.novel_id}/graph/events",
        params={"task_id": scenario.task_id, "events_cursor": out_of_range_cursor},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "graph events cursor is out of range"


def test_get_graph_events_pagination_contract_is_continuous(api_client, db_session) -> None:
    scenario = create_timeline_contract_scenario(db_session)

    first_page = api_client.get(
        f"/api/novels/{scenario.novel_id}/graph/events",
        params={"task_id": scenario.task_id, "events_limit": 1},
    )

    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert [event["chunk_id"] for event in first_payload["events"]] == [4]
    assert first_payload["page_info"]["returned_count"] == 1
    assert first_payload["page_info"]["total"] == 3
    assert first_payload["page_info"]["has_more"] is True

    second_page = api_client.get(
        f"/api/novels/{scenario.novel_id}/graph/events",
        params={
            "task_id": scenario.task_id,
            "events_limit": 1,
            "events_cursor": first_payload["page_info"]["next_cursor"],
        },
    )

    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert [event["chunk_id"] for event in second_payload["events"]] == [2]
    assert second_payload["page_info"]["returned_count"] == 1
    assert second_payload["page_info"]["total"] == 3
    assert second_payload["page_info"]["has_more"] is True
    assert second_payload["page_info"]["next_cursor"] != first_payload["page_info"]["next_cursor"]
    assert second_payload["events"][0]["relation_event_id"] != first_payload["events"][0]["relation_event_id"]


def test_fetch_graph_snapshot_keeps_shared_counts_aligned_with_graph_report(monkeypatch) -> None:
    class FakeAuthorityService:
        def build_graph_view(self, run_id: str) -> GraphAuthorityView:
            assert run_id == "run-graph-shared-counts"
            return GraphAuthorityView(
                stable_states=[
                    StableState(entity_id=1, name="沈砚", entity_type="character", last_seen_chunk=9),
                    StableState(entity_id=2, name="陆明", entity_type="character", last_seen_chunk=8),
                    StableState(entity_id=3, name="秦昭", entity_type="character", last_seen_chunk=7),
                ],
                confirmed_relations=[
                    ConfirmedRelation(
                        from_name="沈砚",
                        to_name="陆明",
                        relation_type="盟友",
                        from_entity_id=1,
                        to_entity_id=2,
                        support_count=3,
                        last_seen_chunk=8,
                        latest_event_id=31,
                    ),
                    ConfirmedRelation(
                        from_name="陆明",
                        to_name="秦昭",
                        relation_type="敌对",
                        from_entity_id=2,
                        to_entity_id=3,
                        support_count=2,
                        last_seen_chunk=7,
                        latest_event_id=32,
                    ),
                ],
                relation_events=[
                    RelationEvent(
                        relation_event_id=31,
                        chunk_id=8,
                        from_entity_id=1,
                        to_entity_id=2,
                        from_name="沈砚",
                        to_name="陆明",
                        relation_type="盟友",
                        change_type="新建",
                        confidence=0.82,
                    ),
                    RelationEvent(
                        relation_event_id=32,
                        chunk_id=7,
                        from_entity_id=2,
                        to_entity_id=3,
                        from_name="陆明",
                        to_name="秦昭",
                        relation_type="敌对",
                        change_type="新建",
                        confidence=0.51,
                    ),
                ],
            )

    monkeypatch.setattr(
        "src.api.routes.results_fetchers.fetchers.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: FakeAuthorityService(),
    )

    annotation_repo = MagicMock()
    annotation_repo.session = object()
    annotation_repo.fetch_pending_chunk_relations.return_value = []

    snapshot = _fetch_graph_snapshot("run-graph-shared-counts", annotation_repo)

    assert snapshot["summary"]["node_count"] == 3
    assert snapshot["summary"]["edge_count"] == 2
    assert snapshot["summary"]["density"] == 0.3333
    assert snapshot["quality"]["conflict_count"] == 0
    assert snapshot["quality"]["low_confidence_count"] == 1
