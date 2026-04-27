from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.knowledge.authority import TIMELINE_AUTHORITY_DEPENDENCY_FIELDS, KnowledgeGraphAuthorityService
from src.metrics.timeline_metrics import (
    TimelineAuthorityContractError,
    _resolve_timeline_authority_contract,
    build_timeline_plan,
)
from src.storage.repositories import AnnotationRepository, ChunkRepository, StatsRepository
from tests.support.timeline_contract_helpers import (
    create_timeline_contract_scenario,
    nodes_for_anchor_chunk,
    relation_event_names,
    relation_event_tuples,
)


def test_build_timeline_plan_consumes_authority_character_subgraph_only(db_session) -> None:
    scenario = create_timeline_contract_scenario(db_session)

    chunk_repo = ChunkRepository(db_session)
    annotation_repo = AnnotationRepository(db_session)
    stats_repo = StatsRepository(db_session)

    timeline_view = KnowledgeGraphAuthorityService.from_session(db_session).build_timeline_view(scenario.run_id)
    timeline_plan = build_timeline_plan(
        scenario.run_id,
        chunk_repo,
        annotation_repo,
        stats_repo,
        timeline_view,
    )

    assert timeline_plan.total_chunks == 5
    assert timeline_plan.tension_curve == [0.15, 0.3, 0.95, 0.45, 0.1]
    assert len(timeline_plan.phases) == 4

    atomic_node_payloads = [
        {
            "node_id": node.node_id,
            "anchor_chunk_id": node.anchor_chunk_id,
            "node_type": node.node_type,
            "node_subtype": node.node_subtype,
            "relation_events": node.relation_events,
            "lifecycle_events": node.lifecycle_events,
        }
        for node in timeline_plan.atomic_nodes
    ]
    anchor_two_nodes = nodes_for_anchor_chunk(atomic_node_payloads, 2)
    relation_node = next(node for node in anchor_two_nodes if node["node_type"] == "relation")

    assert relation_event_tuples(relation_node["relation_events"]) == {
        (scenario.hero_name, scenario.rival_name, "新建")
    }
    assert scenario.organization_name not in relation_event_names(relation_node["relation_events"])
    assert relation_node["node_id"].startswith("relation:")
    assert any(node["node_type"] == "plot" for node in anchor_two_nodes)
    assert any(
        node["node_type"] == "lifecycle" and node["node_subtype"] == "entry"
        for node in nodes_for_anchor_chunk(atomic_node_payloads, 0)
    )
    assert timeline_plan.composite_nodes


def test_resolve_timeline_authority_contract_rejects_missing_lifecycle_for_character() -> None:
    timeline_view = SimpleNamespace(
        character_entities=[
            SimpleNamespace(entity_id=1, name="顾承渊", entity_type="character"),
            SimpleNamespace(entity_id=2, name="苏映雪", entity_type="character"),
        ],
        entity_lifecycles=[
            SimpleNamespace(
                entity_id=1,
                name="顾承渊",
                entity_type="character",
                first_seen_chunk=0,
                last_seen_chunk=4,
            )
        ],
        relation_events=[],
    )

    with pytest.raises(TimelineAuthorityContractError, match="exactly align with character_entities"):
        _resolve_timeline_authority_contract(timeline_view)


def test_resolve_timeline_authority_contract_rejects_lifecycle_name_drift() -> None:
    timeline_view = SimpleNamespace(
        character_entities=[SimpleNamespace(entity_id=1, name="顾承渊", entity_type="character")],
        entity_lifecycles=[
            SimpleNamespace(
                entity_id=1,
                name="顾承渊旧名",
                entity_type="character",
                first_seen_chunk=0,
                last_seen_chunk=4,
            )
        ],
        relation_events=[],
    )

    with pytest.raises(TimelineAuthorityContractError, match="names must match character_entities"):
        _resolve_timeline_authority_contract(timeline_view)


def test_resolve_timeline_authority_contract_rejects_duplicate_lifecycle_entity_ids() -> None:
    timeline_view = SimpleNamespace(
        character_entities=[SimpleNamespace(entity_id=1, name="顾承渊", entity_type="character")],
        entity_lifecycles=[
            SimpleNamespace(
                entity_id=1,
                name="顾承渊",
                entity_type="character",
                first_seen_chunk=0,
                last_seen_chunk=4,
            ),
            SimpleNamespace(
                entity_id=1,
                name="顾承渊",
                entity_type="character",
                first_seen_chunk=0,
                last_seen_chunk=4,
            ),
        ],
        relation_events=[],
    )

    with pytest.raises(TimelineAuthorityContractError, match="must not duplicate entity_id"):
        _resolve_timeline_authority_contract(timeline_view)


def test_resolve_timeline_authority_contract_accepts_new_relation_event_allowlist() -> None:
    timeline_view = SimpleNamespace(
        character_entities=[
            SimpleNamespace(entity_id=1, name="顾承渊", entity_type="character"),
            SimpleNamespace(entity_id=2, name="苏映雪", entity_type="character"),
        ],
        entity_lifecycles=[
            SimpleNamespace(
                entity_id=1,
                name="顾承渊",
                entity_type="character",
                first_seen_chunk=0,
                last_seen_chunk=4,
            ),
            SimpleNamespace(
                entity_id=2,
                name="苏映雪",
                entity_type="character",
                first_seen_chunk=1,
                last_seen_chunk=4,
            ),
        ],
        relation_events=[
            SimpleNamespace(
                relation_event_id=11,
                chunk_id=2,
                from_entity_id=1,
                to_entity_id=2,
                from_name="顾承渊",
                to_name="苏映雪",
                relation_type="盟友",
                change_type="新建",
                evidence="并肩迎敌",
                confidence=0.91,
                directionality="directed",
            )
        ],
    )

    entity_lifecycles, relation_events, entity_name_map = _resolve_timeline_authority_contract(timeline_view)

    assert TIMELINE_AUTHORITY_DEPENDENCY_FIELDS["relation_events"] == (
        "relation_event_id",
        "chunk_id",
        "from_entity_id",
        "to_entity_id",
        "from_name",
        "to_name",
        "relation_type",
        "change_type",
        "evidence",
        "confidence",
        "directionality",
    )
    assert len(entity_lifecycles) == 2
    assert len(relation_events) == 1
    assert entity_name_map == {1: "顾承渊", 2: "苏映雪"}


def test_resolve_timeline_authority_contract_rejects_missing_required_relation_event_field() -> None:
    timeline_view = SimpleNamespace(
        character_entities=[
            SimpleNamespace(entity_id=1, name="顾承渊", entity_type="character"),
            SimpleNamespace(entity_id=2, name="苏映雪", entity_type="character"),
        ],
        entity_lifecycles=[
            SimpleNamespace(
                entity_id=1,
                name="顾承渊",
                entity_type="character",
                first_seen_chunk=0,
                last_seen_chunk=4,
            ),
            SimpleNamespace(
                entity_id=2,
                name="苏映雪",
                entity_type="character",
                first_seen_chunk=1,
                last_seen_chunk=4,
            ),
        ],
        relation_events=[
            SimpleNamespace(
                relation_event_id=11,
                chunk_id=2,
                from_entity_id=1,
                to_entity_id=2,
                from_name="顾承渊",
                to_name="苏映雪",
                change_type="新建",
                evidence="并肩迎敌",
                confidence=0.91,
                directionality="directed",
            )
        ],
    )

    with pytest.raises(TimelineAuthorityContractError, match="missing required fields: relation_type"):
        _resolve_timeline_authority_contract(timeline_view)


def test_resolve_timeline_authority_contract_rejects_non_meaningful_relation_change() -> None:
    timeline_view = SimpleNamespace(
        character_entities=[
            SimpleNamespace(entity_id=1, name="顾承渊", entity_type="character"),
            SimpleNamespace(entity_id=2, name="苏映雪", entity_type="character"),
        ],
        entity_lifecycles=[
            SimpleNamespace(
                entity_id=1,
                name="顾承渊",
                entity_type="character",
                first_seen_chunk=0,
                last_seen_chunk=4,
            ),
            SimpleNamespace(
                entity_id=2,
                name="苏映雪",
                entity_type="character",
                first_seen_chunk=1,
                last_seen_chunk=4,
            ),
        ],
        relation_events=[
            SimpleNamespace(
                relation_event_id=11,
                chunk_id=2,
                from_entity_id=1,
                to_entity_id=2,
                from_name="顾承渊",
                to_name="苏映雪",
                relation_type="盟友",
                change_type="无变化",
                evidence="没有发生变化",
                confidence=0.91,
                directionality="directed",
            )
        ],
    )

    with pytest.raises(TimelineAuthorityContractError, match="meaningful relation changes"):
        _resolve_timeline_authority_contract(timeline_view)
