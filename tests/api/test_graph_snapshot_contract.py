from __future__ import annotations

import base64
import json
import uuid
from types import SimpleNamespace

import pytest

from src.api.routes.results_fetchers import _fetch_graph_events_page, _fetch_graph_snapshot
from src.api.routes.results_fetchers.fetchers import _serialize_graph_page_quality, _serialize_graph_page_summary
from src.knowledge.authority import (
    ConfirmedRelation,
    GraphConflictSample,
    GraphKeyRelationHighlight,
    GraphLowConfidenceSample,
    GraphPageQualityDetails,
    GraphPageSummary,
)
from src.storage.models import ChunkRelation
from src.storage.repositories import GraphRepository, RunRepository
from tests.support.graph_snapshot_helpers import (
    PaginatedGraphAuthorityService,
    StaticGraphAuthorityService,
    build_graph_authority_view,
    create_graph_annotation_repo,
    insert_focus_contract_cloud_analysis,
    insert_graph_test_chunks,
    insert_graph_test_novel,
    participant_state,
    patch_graph_authority_service,
    relation_event,
)
from tests.support.timeline_contract_helpers import create_timeline_contract_scenario


def _create_stale_graph_run(db_session) -> tuple[str, str, str]:
    novel_id = f"g{uuid.uuid4().hex[:7]}"
    insert_graph_test_novel(db_session, novel_id)
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Stale Participant Contract",
    )
    run_repo.update_run_status(run_id, "completed")
    insert_graph_test_chunks(db_session, run_id, range(1, 5))

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="贺伯安", first_seen_chunk=1, last_seen_chunk=3)
    ally = graph_repo.upsert_entity(run_id=run_id, canonical_name="柳婉儿", first_seen_chunk=1, last_seen_chunk=3)
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=ally.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=3,
        evidence="共同应敌",
        confidence=0.91,
        source_relation_row_id=9499,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, ally.entity_id)
    db_session.commit()
    insert_focus_contract_cloud_analysis(
        db_session,
        novel_id=novel_id,
        run_id=run_id,
        focus_characters=["贺伯安"],
        main_characters=["贺伯安", "柳婉儿"],
        core_cast=["贺伯安", "柳婉儿"],
    )
    return novel_id, run_id, run_id[:8]


def test_fetch_graph_snapshot_preserves_contract_shape(db_session) -> None:
    novel_id = f"g{uuid.uuid4().hex[:7]}"
    insert_graph_test_novel(db_session, novel_id)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Snapshot Contract",
    )
    insert_graph_test_chunks(db_session, run_id, range(1, 9))

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
    graph_repo.refresh_entity_participants(run_id, [bo_an.entity_id, liu_wan.entity_id])
    db_session.commit()

    annotation_repo = create_graph_annotation_repo(db_session)

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
    # GraphAuthorityView 节点现在只暴露稳定状态；瞬时情绪不再属于合同的一部分。
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


def test_fetch_graph_snapshot_returns_complete_empty_contract_without_events(db_session) -> None:
    novel_id = f"g{uuid.uuid4().hex[:7]}"
    insert_graph_test_novel(db_session, novel_id)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Snapshot Empty Contract",
    )

    graph_repo = GraphRepository(db_session)
    graph_repo.upsert_entity(run_id=run_id, canonical_name="贺伯安", first_seen_chunk=1, last_seen_chunk=3)
    graph_repo.upsert_entity(run_id=run_id, canonical_name="柳婉儿", first_seen_chunk=1, last_seen_chunk=3)
    db_session.commit()

    annotation_repo = create_graph_annotation_repo(db_session)

    snapshot = _fetch_graph_snapshot(run_id, annotation_repo)

    assert snapshot["nodes"] == []
    assert snapshot["edges"] == []
    assert snapshot["events"] == []
    assert snapshot["events_page"] == {
        "limit": 200,
        "returned_count": 0,
        "total": 0,
        "has_more": False,
        "next_cursor": None,
    }
    assert snapshot["summary"] == {
        "node_count": 0,
        "edge_count": 0,
        "density": 0.0,
        "core_characters": [],
        "key_relations": [],
    }
    assert snapshot["quality"] == {
        "conflict_count": 0,
        "low_confidence_count": 0,
        "conflicts": [],
        "low_confidence_samples": [],
    }


def test_fetch_graph_snapshot_summary_counts_only_reflect_active_edges(db_session) -> None:
    novel_id = f"g{uuid.uuid4().hex[:7]}"
    insert_graph_test_novel(db_session, novel_id)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Snapshot Summary Contract",
    )
    insert_graph_test_chunks(db_session, run_id, range(1, 9))

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
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id, rival.entity_id])
    db_session.commit()

    annotation_repo = create_graph_annotation_repo(db_session)

    snapshot = _fetch_graph_snapshot(run_id, annotation_repo)

    assert snapshot["edges"] == []
    assert snapshot["summary"]["edge_count"] == 0
    assert snapshot["quality"]["low_confidence_count"] == 1
    assert {(event["from_name"], event["to_name"], event["change_type"]) for event in snapshot["events"]} == {
        ("贺伯安", "柳婉儿", "断裂"),
        ("贺伯安", "柳婉儿", "新建"),
    }


def test_fetch_graph_snapshot_keeps_page_summary_in_product_layer(monkeypatch) -> None:
    patch_graph_authority_service(
        monkeypatch,
        StaticGraphAuthorityService(
            expected_run_id="run-graph-page",
            forbid_report=True,
            view=build_graph_authority_view(
                participant_states=[
                    participant_state(entity_id=1, name="沈砚", last_seen_chunk=8),
                    participant_state(entity_id=2, name="陆明", last_seen_chunk=6),
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
                    relation_event(
                        11,
                        chunk_id=6,
                        change_type="新建",
                        confidence=0.55,
                    )
                ],
            ),
        ),
    )

    annotation_repo = create_graph_annotation_repo()

    snapshot = _fetch_graph_snapshot("run-graph-page", annotation_repo)

    assert snapshot["summary"] == {
        "node_count": 2,
        "edge_count": 1,
        "density": 0.0,
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


def test_fetch_graph_snapshot_core_characters_excludes_non_character_nodes(monkeypatch) -> None:
    patch_graph_authority_service(
        monkeypatch,
        StaticGraphAuthorityService(
            expected_run_id="run-graph-page-character-only",
            view=build_graph_authority_view(
                participant_states=[
                    participant_state(entity_id=10, name="天工阁", entity_type="organization", last_seen_chunk=10),
                    participant_state(entity_id=1, name="沈砚", last_seen_chunk=8),
                    participant_state(entity_id=2, name="陆明", last_seen_chunk=6),
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
                relation_events=[],
            ),
        ),
    )

    annotation_repo = create_graph_annotation_repo()

    snapshot = _fetch_graph_snapshot("run-graph-page-character-only", annotation_repo)

    assert snapshot["summary"]["core_characters"] == ["沈砚", "陆明"]
    assert "天工阁" not in snapshot["summary"]["core_characters"]


# 2026-04-28，任务：统一关系图谱密度口径。
# 新建原因：锁住“重复关系对只算一条简单边，但孤立参与者仍进入分母”的回归语义。
def test_fetch_graph_snapshot_density_deduplicates_same_pair_and_keeps_isolated_nodes(monkeypatch) -> None:
    patch_graph_authority_service(
        monkeypatch,
        StaticGraphAuthorityService(
            expected_run_id="run-graph-density-shape",
            view=build_graph_authority_view(
                participant_states=[
                    participant_state(entity_id=1, name="沈砚", last_seen_chunk=9),
                    participant_state(entity_id=2, name="陆明", last_seen_chunk=8),
                    participant_state(entity_id=3, name="秦昭", last_seen_chunk=7),
                    participant_state(entity_id=4, name="潘寒", last_seen_chunk=6),
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
                    ),
                    ConfirmedRelation(
                        from_name="陆明",
                        to_name="沈砚",
                        relation_type="战友",
                        from_entity_id=2,
                        to_entity_id=1,
                        support_count=2,
                        last_seen_chunk=7,
                    ),
                    ConfirmedRelation(
                        from_name="陆明",
                        to_name="秦昭",
                        relation_type="敌对",
                        from_entity_id=2,
                        to_entity_id=3,
                        support_count=1,
                        last_seen_chunk=6,
                    ),
                ],
                relation_events=[],
            ),
        ),
    )

    snapshot = _fetch_graph_snapshot("run-graph-density-shape", create_graph_annotation_repo())

    assert snapshot["summary"]["node_count"] == 4
    assert snapshot["summary"]["edge_count"] == 2
    assert snapshot["summary"]["density"] == 0.6667


def test_fetch_graph_snapshot_core_characters_is_empty_without_character_nodes(monkeypatch) -> None:
    patch_graph_authority_service(
        monkeypatch,
        StaticGraphAuthorityService(
            expected_run_id="run-graph-page-no-character",
            view=build_graph_authority_view(
                participant_states=[],
                confirmed_relations=[],
                relation_events=[],
            ),
        ),
    )

    annotation_repo = create_graph_annotation_repo()

    snapshot = _fetch_graph_snapshot("run-graph-page-no-character", annotation_repo)

    assert snapshot["nodes"] == []
    assert snapshot["summary"]["node_count"] == 0
    assert snapshot["summary"]["core_characters"] == []


def test_fetch_graph_snapshot_accepts_graph_page_allowlist_without_full_graph_view(monkeypatch) -> None:
    patch_graph_authority_service(
        monkeypatch,
        StaticGraphAuthorityService(
            expected_run_id="run-graph-page-allowlist",
            # route assembler 只应该依赖 graph page allowlist；
            # 这里故意不给 canonical_entities，防止测试重新把它当必需依赖。
            view=SimpleNamespace(
                participant_states=[
                    participant_state(entity_id=1, name="沈砚", last_seen_chunk=8),
                    participant_state(entity_id=2, name="陆明", last_seen_chunk=6),
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
                    relation_event(
                        11,
                        chunk_id=6,
                        change_type="新建",
                        confidence=0.55,
                    )
                ],
            ),
        ),
    )

    annotation_repo = create_graph_annotation_repo()

    snapshot = _fetch_graph_snapshot("run-graph-page-allowlist", annotation_repo)

    assert snapshot["summary"]["node_count"] == 2
    assert snapshot["summary"]["edge_count"] == 1
    assert snapshot["quality"]["low_confidence_count"] == 1
    assert snapshot["events_page"]["total"] == 1


def test_graph_page_public_dto_is_owned_by_route_layer() -> None:
    import src.knowledge.authority.graph_outputs as graph_outputs

    # authority 只保留 page facts builder，不再定义 `/graph` 的公开 DTO，
    # 防止其他 consumer 继续直接 import authority serializer 借用页面字段。
    assert not hasattr(graph_outputs, "serialize_graph_page_summary")
    assert not hasattr(graph_outputs, "serialize_graph_page_quality")

    summary = _serialize_graph_page_summary(
        GraphPageSummary(
            node_count=2,
            edge_count=1,
            density=0.5,
            core_characters=["沈砚", "陆明"],
            key_relations=[
                GraphKeyRelationHighlight(
                    from_name="沈砚",
                    to_name="陆明",
                    relation_type="盟友",
                    support_count=3,
                )
            ],
        )
    )
    quality = _serialize_graph_page_quality(
        GraphPageQualityDetails(
            conflict_count=1,
            low_confidence_count=2,
            conflicts=[
                GraphConflictSample(
                    entity_pair=[1, 2],
                    entity_names=["沈砚", "陆明"],
                    relation_types=["盟友", "敌对"],
                    relation_count=2,
                    latest_event_ids=[11, 12],
                )
            ],
            low_confidence_samples=[
                GraphLowConfidenceSample(
                    relation_event_id=11,
                    chunk_id=6,
                    from_name="沈砚",
                    to_name="陆明",
                    relation_type="盟友",
                    change_type="强化",
                    confidence=0.55,
                )
            ],
        )
    )

    assert summary == {
        "node_count": 2,
        "edge_count": 1,
        "density": 0.5,
        "core_characters": ["沈砚", "陆明"],
        "key_relations": [{"from": "沈砚", "to": "陆明", "type": "盟友", "support_count": 3}],
    }
    assert quality == {
        "conflict_count": 1,
        "low_confidence_count": 2,
        "conflicts": [
            {
                "entity_pair": [1, 2],
                "entity_names": ["沈砚", "陆明"],
                "relation_types": ["盟友", "敌对"],
                "relation_count": 2,
                "latest_event_ids": [11, 12],
            }
        ],
        "low_confidence_samples": [
            {
                "relation_event_id": 11,
                "chunk_id": 6,
                "from_name": "沈砚",
                "to_name": "陆明",
                "relation_type": "盟友",
                "change_type": "强化",
                "confidence": 0.55,
            }
        ],
    }


def test_fetch_graph_snapshot_quality_counts_full_history_but_caps_page_events(monkeypatch) -> None:
    relation_events = [
        relation_event(index + 1, chunk_id=500 - index, change_type="强化", confidence=0.55) for index in range(205)
    ]
    patch_graph_authority_service(
        monkeypatch,
        StaticGraphAuthorityService(
            expected_run_id="run-graph-quality",
            forbid_report=True,
            view=build_graph_authority_view(
                participant_states=[
                    participant_state(entity_id=1, name="沈砚", last_seen_chunk=500),
                    participant_state(entity_id=2, name="陆明", last_seen_chunk=499),
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
            ),
        ),
    )

    annotation_repo = create_graph_annotation_repo()

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
    relation_events = [
        relation_event(index + 1, chunk_id=500 - index, change_type="强化", confidence=0.55) for index in range(205)
    ]
    patch_graph_authority_service(
        monkeypatch,
        PaginatedGraphAuthorityService(
            expected_run_id="run-graph-events-page",
            relation_events=relation_events,
            forbid_report=True,
            view=build_graph_authority_view(
                participant_states=[],
                confirmed_relations=[],
                relation_events=relation_events,
            ),
        ),
    )

    annotation_repo = create_graph_annotation_repo()

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


def test_fetch_graph_events_page_returns_complete_empty_page(monkeypatch) -> None:
    patch_graph_authority_service(
        monkeypatch,
        PaginatedGraphAuthorityService(
            expected_run_id="run-empty-graph-events-page",
            relation_events=[],
            view=build_graph_authority_view(
                canonical_entities=[],
                participant_states=[],
                confirmed_relations=[],
                relation_events=[],
            ),
        ),
    )

    annotation_repo = create_graph_annotation_repo()

    page = _fetch_graph_events_page(
        "run-empty-graph-events-page",
        annotation_repo,
    )

    assert page == {
        "events": [],
        "page_info": {
            "limit": 200,
            "returned_count": 0,
            "total": 0,
            "has_more": False,
            "next_cursor": None,
        },
    }


def test_fetch_graph_events_page_rejects_missing_participant_projection(db_session) -> None:
    _novel_id, run_id, _task_id = _create_stale_graph_run(db_session)

    annotation_repo = create_graph_annotation_repo(db_session)

    with pytest.raises(RuntimeError, match="graph participant projection is stale or incomplete"):
        _fetch_graph_events_page(run_id, annotation_repo)


def test_fetch_graph_events_page_ignores_filtered_final_disambiguation_history(db_session) -> None:
    """
    创建时间: 2026-04-29
    任务: graph events consistency blocker 修复
    说明: 只剩被 history 过滤掉的 synthetic final_disambiguation event 时，
          `/graph/events` 增量分页应返回空页，而不是误报 stale participant projection。
    """
    novel_id = f"g{uuid.uuid4().hex[:7]}"
    insert_graph_test_novel(db_session, novel_id)
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Events Synthetic History Filter",
    )
    run_repo.update_run_status(run_id, "completed")
    insert_graph_test_chunks(db_session, run_id, range(1, 3))

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="顾霜", first_seen_chunk=2, last_seen_chunk=2)
    ally = graph_repo.upsert_entity(run_id=run_id, canonical_name="贺家", first_seen_chunk=2, last_seen_chunk=2)
    source_relation = ChunkRelation(
        chunk_id=2,
        run_id=run_id,
        from_char="阿顾",
        to_char="贺家",
        resolved_from_global_name="顾霜",
        resolved_to_global_name="贺家",
        type="belongs_to",
        change="新建",
        evidence="阿顾属于贺家",
        confidence=0.91,
        source_model="final_disambiguation",
        projection_status="projected",
    )
    db_session.add(source_relation)
    db_session.flush()

    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=ally.entity_id,
        relation_type="belongs_to",
        change_type="新建",
        chunk_id=2,
        evidence="阿顾属于贺家",
        confidence=0.91,
        source_relation_row_id=source_relation.id,
        directionality="directed",
    )
    db_session.commit()

    annotation_repo = create_graph_annotation_repo(db_session)

    page = _fetch_graph_events_page(run_id, annotation_repo)

    assert page == {
        "events": [],
        "page_info": {
            "limit": 200,
            "returned_count": 0,
            "total": 0,
            "has_more": False,
            "next_cursor": None,
        },
    }


def test_get_graph_stale_participant_projection_returns_409(api_client, db_session) -> None:
    novel_id, _run_id, task_id = _create_stale_graph_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/graph",
        params={"task_id": task_id},
    )

    assert response.status_code == 409
    assert response.json()["error_type"] == "GraphReadinessError"


def test_get_graph_events_stale_participant_projection_returns_409(api_client, db_session) -> None:
    novel_id, _run_id, task_id = _create_stale_graph_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/graph/events",
        params={"task_id": task_id},
    )

    assert response.status_code == 409
    assert response.json()["error_type"] == "GraphReadinessError"


def test_get_graph_pending_projection_returns_409(api_client, db_session) -> None:
    novel_id = f"g{uuid.uuid4().hex[:7]}"
    insert_graph_test_novel(db_session, novel_id)
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Pending Projection",
    )
    run_repo.update_run_status(run_id, "completed")
    insert_graph_test_chunks(db_session, run_id, range(1, 3))
    insert_focus_contract_cloud_analysis(
        db_session,
        novel_id=novel_id,
        run_id=run_id,
        focus_characters=["贺伯安"],
        main_characters=["贺伯安", "柳婉儿"],
        core_cast=["贺伯安", "柳婉儿"],
    )
    db_session.add(
        ChunkRelation(
            chunk_id=1,
            run_id=run_id,
            from_char="贺伯安",
            to_char="柳婉儿",
            type="盟友",
            change="新建",
            evidence="共同应敌",
            confidence=0.91,
            projection_status="pending",
        )
    )
    db_session.commit()

    response = api_client.get(
        f"/api/novels/{novel_id}/graph",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 409
    assert response.json()["error_type"] == "GraphReadinessError"


def test_get_graph_rejects_non_terminal_run_status(api_client, db_session) -> None:
    novel_id = f"g{uuid.uuid4().hex[:7]}"
    insert_graph_test_novel(db_session, novel_id)
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Non Terminal Run",
    )
    run_repo.update_run_status(run_id, "running")

    response = api_client.get(
        f"/api/novels/{novel_id}/graph",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 400
    assert response.json()["error_type"] == "AnalysisNotCompleteError"


def test_get_graph_events_rejects_non_terminal_run_status(api_client, db_session) -> None:
    novel_id = f"g{uuid.uuid4().hex[:7]}"
    insert_graph_test_novel(db_session, novel_id)
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Events Non Terminal Run",
    )
    run_repo.update_run_status(run_id, "running")

    response = api_client.get(
        f"/api/novels/{novel_id}/graph/events",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 400
    assert response.json()["error_type"] == "AnalysisNotCompleteError"


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
    events = [relation_event(1, chunk_id=3, change_type="新建", confidence=0.8)]
    patch_graph_authority_service(
        monkeypatch,
        PaginatedGraphAuthorityService(
            expected_run_id="run-invalid-graph-cursor",
            relation_events=events,
            view=build_graph_authority_view(
                participant_states=[],
                confirmed_relations=[],
                relation_events=events,
            ),
        ),
    )

    annotation_repo = create_graph_annotation_repo()

    with pytest.raises(ValueError, match="invalid graph events cursor"):
        _fetch_graph_events_page(
            "run-invalid-graph-cursor",
            annotation_repo,
            events_cursor=cursor,
        )


def test_fetch_graph_events_page_uses_incremental_authority_page_builder(monkeypatch) -> None:
    events = [
        relation_event(11, chunk_id=9, change_type="新建", confidence=0.79),
        relation_event(12, chunk_id=8, change_type="强化", confidence=0.77),
        relation_event(13, chunk_id=7, change_type="弱化", confidence=0.73),
        relation_event(14, chunk_id=6, change_type="强化", confidence=0.72),
        relation_event(15, chunk_id=5, change_type="断裂", confidence=0.71),
    ]
    patch_graph_authority_service(
        monkeypatch,
        PaginatedGraphAuthorityService(
            expected_run_id="run-incremental-graph-events",
            relation_events=events,
            forbid_view=True,
        ),
    )

    annotation_repo = create_graph_annotation_repo()

    cursor = base64.urlsafe_b64encode(json.dumps({"offset": 1}).encode("utf-8")).decode("ascii").rstrip("=")
    page = _fetch_graph_events_page(
        "run-incremental-graph-events",
        annotation_repo,
        events_cursor=cursor,
        events_limit=2,
    )

    assert [event["relation_event_id"] for event in page["events"]] == [12, 13]
    assert page["page_info"] == {
        "limit": 2,
        "returned_count": 2,
        "total": 5,
        "has_more": True,
        "next_cursor": base64.urlsafe_b64encode(json.dumps({"offset": 3}, separators=(",", ":")).encode("utf-8"))
        .decode("ascii")
        .rstrip("="),
    }


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
    out_of_range_cursor = (
        base64.urlsafe_b64encode(json.dumps({"offset": 99}).encode("utf-8")).decode("ascii").rstrip("=")
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


def test_fetch_graph_events_page_skips_filtered_legacy_rows_without_stalling(db_session) -> None:
    """
    创建时间: 2026-04-29
    任务: graph-diagnosis-mainline-blockers
    说明: `/graph/events` 分页必须先过滤旧 pronoun 脏边，再计算 offset/limit，
          否则第一页会空掉但 cursor 仍声称可继续翻页。
    """
    novel_id = f"g{uuid.uuid4().hex[:7]}"
    insert_graph_test_novel(db_session, novel_id)
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Events Cursor Filter",
    )
    insert_graph_test_chunks(db_session, run_id, range(1, 5))

    graph_repo = GraphRepository(db_session)
    stale = graph_repo.upsert_entity(run_id=run_id, canonical_name="我", first_seen_chunk=4, last_seen_chunk=4)
    hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="沈砚", first_seen_chunk=1, last_seen_chunk=4)
    ally = graph_repo.upsert_entity(run_id=run_id, canonical_name="陆明", first_seen_chunk=1, last_seen_chunk=3)
    rival = graph_repo.upsert_entity(run_id=run_id, canonical_name="秦昭", first_seen_chunk=1, last_seen_chunk=2)

    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=stale.entity_id,
        to_entity_id=hero.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=4,
        evidence="旧代词脏边",
        confidence=0.42,
        source_relation_row_id=9801,
        directionality="directed",
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=ally.entity_id,
        relation_type="盟友",
        change_type="强化",
        chunk_id=3,
        evidence="有效事件1",
        confidence=0.88,
        source_relation_row_id=9802,
        directionality="directed",
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=rival.entity_id,
        relation_type="敌对",
        change_type="新建",
        chunk_id=2,
        evidence="有效事件2",
        confidence=0.79,
        source_relation_row_id=9803,
        directionality="directed",
    )
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id, ally.entity_id, rival.entity_id])
    db_session.commit()

    annotation_repo = create_graph_annotation_repo(db_session)

    first_page = _fetch_graph_events_page(run_id, annotation_repo, events_limit=1)
    second_page = _fetch_graph_events_page(
        run_id,
        annotation_repo,
        events_limit=1,
        events_cursor=first_page["page_info"]["next_cursor"],
    )

    assert [event["chunk_id"] for event in first_page["events"]] == [3]
    assert first_page["page_info"]["limit"] == 1
    assert first_page["page_info"]["returned_count"] == 1
    assert first_page["page_info"]["total"] == 2
    assert first_page["page_info"]["has_more"] is True
    assert first_page["page_info"]["next_cursor"] is not None
    assert [event["chunk_id"] for event in second_page["events"]] == [2]
    assert second_page["page_info"]["returned_count"] == 1
    assert second_page["page_info"]["total"] == 2
    assert second_page["page_info"]["has_more"] is False
    assert second_page["page_info"]["next_cursor"] is None


def test_fetch_graph_snapshot_keeps_shared_counts_aligned_with_graph_report(monkeypatch) -> None:
    patch_graph_authority_service(
        monkeypatch,
        StaticGraphAuthorityService(
            expected_run_id="run-graph-shared-counts",
            view=build_graph_authority_view(
                participant_states=[
                    participant_state(entity_id=1, name="沈砚", last_seen_chunk=9),
                    participant_state(entity_id=2, name="陆明", last_seen_chunk=8),
                    participant_state(entity_id=3, name="秦昭", last_seen_chunk=7),
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
                    relation_event(
                        31,
                        chunk_id=8,
                        change_type="新建",
                        confidence=0.82,
                    ),
                    relation_event(
                        32,
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
            ),
        ),
    )

    annotation_repo = create_graph_annotation_repo()

    snapshot = _fetch_graph_snapshot("run-graph-shared-counts", annotation_repo)

    assert snapshot["summary"]["node_count"] == 3
    assert snapshot["summary"]["edge_count"] == 2
    assert snapshot["summary"]["density"] == 1.0
    assert snapshot["quality"]["conflict_count"] == 0
    assert snapshot["quality"]["low_confidence_count"] == 1
