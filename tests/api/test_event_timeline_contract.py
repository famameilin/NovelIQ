"""独立变化接口使用持久化标注事实验证历史状态与来源边界"""

from tests.support.timeline_contract_helpers import create_timeline_contract_scenario


def test_character_history_and_source_mapping(api_client, db_session):
    scenario = create_timeline_contract_scenario(db_session)
    url = f"/api/novels/{scenario.novel_id}/timeline"
    params = {"task_id": scenario.task_id}
    first = api_client.get(url, params=params).json()
    assert first["through_chapter_id"] == 1
    assert all(item["subject_title"] != scenario.rival_name for item in first["subjects"])
    third = api_client.get(url, params={**params, "through_chapter_id": 3}).json()
    hero = next(item for item in third["states"] if item["subject_title"] == scenario.hero_name)
    assert hero["state"]["action"] == "结盟" and hero["state"]["emotion"] == -2
    change = next(
        item for item in third["changes"] if item["subject_id"] == hero["subject_id"] and item["chapter_id"] == 3
    )
    mapped = api_client.get(
        url, params={**params, "through_chapter_id": 3, "source_fact_id": change["source_fact_ids"][0]}
    ).json()
    assert mapped["changes"] == [change]
    source = api_client.get(
        f"{url}/changes/{change['progression_change_id']}/source", params={**params, "through_chapter_id": 3}
    )
    assert source.status_code == 200
    assert "结盟" in source.json()["paragraphs"][0]["text"]
    assert (
        api_client.get(
            f"{url}/changes/{change['progression_change_id']}", params={**params, "through_chapter_id": 1}
        ).status_code
        == 404
    )


def test_relationship_break_and_window_preserve_history(api_client, db_session):
    scenario = create_timeline_contract_scenario(db_session)
    url = f"/api/novels/{scenario.novel_id}/timeline"
    params = {"task_id": scenario.task_id, "through_chapter_id": 5, "dimension": "relationship"}
    result = api_client.get(url, params=params).json()
    ally = [item for item in result["changes"] if item["after"]["relation_type"] == "盟友"]
    assert [item["action"] for item in ally] == ["assert", "break"]
    assert ally[0]["before"] is None
    assert ally[1]["before"]["active"] is True and ally[1]["after"]["active"] is False
    window = api_client.get(url, params={**params, "window_start_chapter_id": 5}).json()
    assert window["changes"] == [ally[1]] and window["states"] == result["states"]


def test_retired_forest_route_is_unregistered(api_client):
    assert api_client.get("/api/novels/any/event-forest", params={"task_id": "any"}).status_code == 404
