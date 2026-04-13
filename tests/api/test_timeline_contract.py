from __future__ import annotations

from fastapi.testclient import TestClient

from tests.support.timeline_contract_helpers import (
    create_timeline_contract_scenario,
    index_by_chunk_id,
    relation_change_names,
    relation_change_tuples,
)


def test_get_timeline_preserves_authority_backed_contract(api_client: TestClient, db_session) -> None:
    scenario = create_timeline_contract_scenario(db_session)

    response = api_client.get(
        f"/api/novels/{scenario.novel_id}/timeline",
        params={"task_id": scenario.task_id, "include_curve": "true"},
    )

    assert response.status_code == 200
    payload = response.json()
    nodes_by_chunk = index_by_chunk_id(payload["nodes"])

    assert payload["meta"]["novel_id"] == scenario.novel_id
    assert payload["meta"]["total_chunks"] == 5
    assert len(payload["phases"]) == 4
    assert payload["tension_curve"] == [0.15, 0.3, 0.95, 0.45, 0.1]

    assert [node["progress"] for node in payload["nodes"]] == sorted(node["progress"] for node in payload["nodes"])

    assert nodes_by_chunk[0]["node_type"] == "character_entry"
    assert nodes_by_chunk[0]["character_entries"] == [scenario.hero_name]
    assert nodes_by_chunk[1]["node_type"] == "character_entry"
    assert nodes_by_chunk[1]["character_entries"] == [scenario.rival_name]
    assert nodes_by_chunk[2]["node_type"] == "relation_change"
    assert relation_change_tuples(nodes_by_chunk[2]["relation_changes"]) == {
        (scenario.hero_name, scenario.rival_name, "新建")
    }
    assert scenario.organization_name not in relation_change_names(nodes_by_chunk[2]["relation_changes"])
    assert nodes_by_chunk[3]["node_type"] == "character_exit"
    assert nodes_by_chunk[3]["character_exits"] == [scenario.rival_name]
    assert nodes_by_chunk[4]["character_exits"] == [scenario.hero_name]
    assert relation_change_tuples(nodes_by_chunk[4]["relation_changes"]) == {
        (scenario.hero_name, scenario.rival_name, "断裂")
    }


def test_get_timeline_max_level_filter_only_changes_node_subset(api_client: TestClient, db_session) -> None:
    scenario = create_timeline_contract_scenario(db_session)

    full_response = api_client.get(
        f"/api/novels/{scenario.novel_id}/timeline",
        params={"task_id": scenario.task_id, "include_curve": "false", "max_level": 3},
    )
    filtered_response = api_client.get(
        f"/api/novels/{scenario.novel_id}/timeline",
        params={"task_id": scenario.task_id, "include_curve": "false", "max_level": 2},
    )

    assert full_response.status_code == 200
    assert filtered_response.status_code == 200

    full_payload = full_response.json()
    filtered_payload = filtered_response.json()

    assert full_payload["tension_curve"] is None
    assert filtered_payload["tension_curve"] is None
    assert len(filtered_payload["nodes"]) < len(full_payload["nodes"])
    assert all(node["level"] <= 2 for node in filtered_payload["nodes"])
    assert [node["progress"] for node in filtered_payload["nodes"]] == sorted(
        node["progress"] for node in filtered_payload["nodes"]
    )
    assert {
        node["chunk_id"] for node in filtered_payload["nodes"]
    }.issubset({node["chunk_id"] for node in full_payload["nodes"]})
