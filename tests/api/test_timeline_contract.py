from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from src.metrics.timeline_metrics import TimelineAuthorityContractError
from src.storage.models import ChunkRelation, GraphEntityParticipant
from tests.support.timeline_contract_helpers import (
    create_timeline_contract_scenario,
    nodes_for_anchor_chunk,
    relation_event_names,
    relation_event_tuples,
)


def test_get_timeline_returns_atomic_and_composite_nodes(api_client: TestClient, db_session) -> None:
    scenario = create_timeline_contract_scenario(db_session)

    response = api_client.get(
        f"/api/novels/{scenario.novel_id}/timeline",
        params={"task_id": scenario.task_id, "include_curve": "true"},
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["meta"]["novel_id"] == scenario.novel_id
    assert payload["meta"]["total_chunks"] == 5
    assert len(payload["phases"]) == 4
    assert payload["tension_curve"] == [0.15, 0.3, 0.95, 0.45, 0.1]
    assert [node["progress"] for node in payload["atomic_nodes"]] == sorted(
        node["progress"] for node in payload["atomic_nodes"]
    )
    assert [node["start_progress"] for node in payload["composite_nodes"]] == sorted(
        node["start_progress"] for node in payload["composite_nodes"]
    )

    anchor_chunk_zero_nodes = nodes_for_anchor_chunk(payload["atomic_nodes"], 0)
    anchor_chunk_two_nodes = nodes_for_anchor_chunk(payload["atomic_nodes"], 2)
    anchor_chunk_four_nodes = nodes_for_anchor_chunk(payload["atomic_nodes"], 4)
    composite_anchor_chunk_two_nodes = nodes_for_anchor_chunk(payload["composite_nodes"], 2)

    assert any(node["node_type"] == "plot" for node in anchor_chunk_zero_nodes)
    assert any(
        node["node_type"] == "lifecycle" and node["node_subtype"] == "entry" for node in anchor_chunk_zero_nodes
    )
    assert any(node["node_type"] == "plot" for node in anchor_chunk_two_nodes)
    relation_node = next(node for node in anchor_chunk_two_nodes if node["node_type"] == "relation")
    assert relation_event_tuples(relation_node["relation_events"]) == {
        (scenario.hero_name, scenario.rival_name, "新建")
    }
    assert scenario.organization_name not in relation_event_names(relation_node["relation_events"])
    assert any(node["node_type"] == "plot" for node in anchor_chunk_four_nodes)
    assert any(node["node_type"] == "relation" for node in composite_anchor_chunk_two_nodes)
    assert any(
        "relation:" in child_id
        for node in composite_anchor_chunk_two_nodes
        for child_id in node["child_node_ids"]
    )

def test_get_timeline_include_curve_only_controls_tension_curve_field(
    api_client: TestClient,
    db_session,
) -> None:
    scenario = create_timeline_contract_scenario(db_session)

    with_curve_response = api_client.get(
        f"/api/novels/{scenario.novel_id}/timeline",
        params={"task_id": scenario.task_id, "include_curve": "true"},
    )
    without_curve_response = api_client.get(
        f"/api/novels/{scenario.novel_id}/timeline",
        params={"task_id": scenario.task_id, "include_curve": "false"},
    )

    assert with_curve_response.status_code == 200
    assert without_curve_response.status_code == 200

    with_curve_payload = with_curve_response.json()
    without_curve_payload = without_curve_response.json()

    assert with_curve_payload["tension_curve"] == [0.15, 0.3, 0.95, 0.45, 0.1]
    assert without_curve_payload["tension_curve"] is None
    assert without_curve_payload["atomic_nodes"] == with_curve_payload["atomic_nodes"]
    assert without_curve_payload["composite_nodes"] == with_curve_payload["composite_nodes"]


def test_get_timeline_keeps_public_contract_decoupled_from_authority_internal_shapes(
    api_client: TestClient,
    db_session,
) -> None:
    scenario = create_timeline_contract_scenario(db_session)

    response = api_client.get(
        f"/api/novels/{scenario.novel_id}/timeline",
        params={"task_id": scenario.task_id, "include_curve": "true"},
    )

    assert response.status_code == 200
    payload = response.json()
    relation_node = next(node for node in payload["atomic_nodes"] if node["node_type"] == "relation")
    relation_event = relation_node["relation_events"][0]

    assert set(payload) == {"meta", "phases", "composite_nodes", "atomic_nodes", "tension_curve"}
    assert "character_entities" not in payload
    assert "entity_lifecycles" not in payload
    assert "relation_events" not in payload

    assert set(relation_node) == {
        "node_id",
        "anchor_chunk_id",
        "progress",
        "importance_score",
        "level",
        "summary",
        "characters",
        "phase_name",
        "node_type",
        "node_subtype",
        "score_breakdown",
        "plot_flags",
        "relation_events",
        "lifecycle_events",
    }
    assert set(relation_event) == {
        "relation_event_id",
        "from_char",
        "to_char",
        "relation_type",
        "change_type",
        "evidence",
        "confidence",
        "directionality",
    }
    assert relation_event["from_char"] == scenario.hero_name
    assert relation_event["to_char"] == scenario.rival_name
    assert relation_event["relation_type"] == "盟友"
    assert relation_event["change_type"] == "新建"
    assert relation_event["evidence"] == "二人正式结盟"

    composite_relation_node = next(node for node in payload["composite_nodes"] if node["node_type"] == "relation")
    assert set(composite_relation_node) == {
        "node_id",
        "anchor_chunk_id",
        "start_chunk_id",
        "end_chunk_id",
        "progress",
        "start_progress",
        "end_progress",
        "importance_score",
        "level",
        "summary",
        "characters",
        "phase_name",
        "node_type",
        "node_subtypes",
        "representative_node_id",
        "child_node_ids",
    }


def test_get_timeline_does_not_downgrade_authority_contract_failures_to_empty_payload(
    api_client: TestClient,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = create_timeline_contract_scenario(db_session)

    def _raise_contract_error(*_args, **_kwargs):
        raise TimelineAuthorityContractError("broken authority contract")

    monkeypatch.setattr("src.api.routes.timeline.build_timeline_plan", _raise_contract_error)

    with (
        patch("src.api.main._recover_orphaned_tasks", return_value=(0, 0)),
        patch("src.api.main._resume_pending_tasks", new=AsyncMock(return_value=(0, 0))),
        TestClient(api_client.app, raise_server_exceptions=False) as relaxed_client,
    ):
        response = relaxed_client.get(
            f"/api/novels/{scenario.novel_id}/timeline",
            params={"task_id": scenario.task_id, "include_curve": "true"},
        )

    assert response.status_code == 500
    assert response.json()["error_type"] == "InternalServerError"


def test_get_timeline_stale_participant_projection_returns_409(api_client: TestClient, db_session) -> None:
    scenario = create_timeline_contract_scenario(db_session)
    db_session.execute(delete(GraphEntityParticipant).where(GraphEntityParticipant.run_id == scenario.run_id))
    db_session.commit()

    response = api_client.get(
        f"/api/novels/{scenario.novel_id}/timeline",
        params={"task_id": scenario.task_id, "include_curve": "true"},
    )

    assert response.status_code == 409
    assert response.json()["error_type"] == "GraphReadinessError"


def test_get_timeline_pending_partial_graph_returns_409(api_client: TestClient, db_session) -> None:
    scenario = create_timeline_contract_scenario(db_session)
    db_session.add(
        ChunkRelation(
            chunk_id=4,
            run_id=scenario.run_id,
            from_char=scenario.hero_name,
            to_char=scenario.rival_name,
            type="盟友",
            change="强化",
            evidence="尚未投影的新关系变化",
            confidence=0.66,
            projection_status="pending",
        )
    )
    db_session.commit()

    response = api_client.get(
        f"/api/novels/{scenario.novel_id}/timeline",
        params={"task_id": scenario.task_id, "include_curve": "true"},
    )

    assert response.status_code == 409
    assert response.json()["error_type"] == "GraphReadinessError"
