from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.knowledge.authority import TIMELINE_AUTHORITY_DEPENDENCY_FIELDS, KnowledgeGraphAuthorityService
from src.metrics.timeline_metrics import (
    TimelineAuthorityContractError,
    _resolve_timeline_authority_contract,
    build_timeline_plan,
)
from src.storage.repositories import AnnotationRepository, ChapterRepository, StatsRepository
from tests.support.timeline_contract_helpers import (
    create_timeline_contract_scenario,
    graph_change_names,
    graph_change_tuples,
    nodes_for_anchor_chapter,
)


def test_build_timeline_plan_consumes_authority_character_subgraph_only(db_session) -> None:
    scenario = create_timeline_contract_scenario(db_session)

    chapter_repo = ChapterRepository(db_session)
    annotation_repo = AnnotationRepository(db_session)
    stats_repo = StatsRepository(db_session)

    timeline_view = KnowledgeGraphAuthorityService.from_session(db_session).build_timeline_view(scenario.run_id)
    timeline_plan = build_timeline_plan(
        scenario.run_id,
        chapter_repo,
        annotation_repo,
        stats_repo,
        timeline_view,
    )

    assert timeline_plan.total_chapters == 5
    assert timeline_plan.tension_curve == [0.6, 0.7, 0.9, 0.5, 0.4]
    assert len(timeline_plan.phases) == 4

    atomic_node_payloads = [
        {
            "node_id": node.node_id,
            "anchor_chapter_id": node.anchor_chapter_id,
            "node_type": node.node_type,
            "node_subtype": node.node_subtype,
            "graph_changes": node.graph_changes,
            "lifecycle_events": node.lifecycle_events,
        }
        for node in timeline_plan.atomic_nodes
    ]
    anchor_two_nodes = nodes_for_anchor_chapter(atomic_node_payloads, 3)
    relation_node = next(node for node in anchor_two_nodes if node["node_type"] == "relation")

    assert graph_change_tuples(relation_node["graph_changes"]) == {
        (scenario.hero_name, scenario.rival_name, "assert")
    }
    assert scenario.organization_name not in graph_change_names(relation_node["graph_changes"])
    assert relation_node["node_id"].startswith("relation:")
    assert any(node["node_type"] == "plot" for node in anchor_two_nodes)
    assert any(
        node["node_type"] == "lifecycle" and node["node_subtype"] == "entry"
        for node in nodes_for_anchor_chapter(atomic_node_payloads, 1)
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
                first_seen_chapter=0,
                last_seen_chapter=4,
            )
        ],
        graph_changes=[],
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
                first_seen_chapter=0,
                last_seen_chapter=4,
            )
        ],
        graph_changes=[],
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
                first_seen_chapter=0,
                last_seen_chapter=4,
            ),
            SimpleNamespace(
                entity_id=1,
                name="顾承渊",
                entity_type="character",
                first_seen_chapter=0,
                last_seen_chapter=4,
            ),
        ],
        graph_changes=[],
    )

    with pytest.raises(TimelineAuthorityContractError, match="must not duplicate entity_id"):
        _resolve_timeline_authority_contract(timeline_view)


def test_resolve_timeline_authority_contract_accepts_graph_change_allowlist() -> None:
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
                first_seen_chapter=0,
                last_seen_chapter=4,
            ),
            SimpleNamespace(
                entity_id=2,
                name="苏映雪",
                entity_type="character",
                first_seen_chapter=1,
                last_seen_chapter=4,
            ),
        ],
        graph_changes=[
            SimpleNamespace(
                change_id="relation:11",
                change_kind="relation",
                chapter_id=3,
                chapter_order=3,
                fact_id="fact-11",
                effective_chapter_id=2,
                changes=[{"change_kind": "assert"}],
                entity_id=None,
                entity_name=None,
                from_entity_id=1,
                to_entity_id=2,
                from_name="顾承渊",
                to_name="苏映雪",
                relation_type="盟友",
                directionality="directed",
            )
        ],
    )

    entity_lifecycles, graph_changes, entity_name_map = _resolve_timeline_authority_contract(timeline_view)

    assert TIMELINE_AUTHORITY_DEPENDENCY_FIELDS["graph_changes"] == (
        "change_id",
        "change_kind",
        "chapter_id",
        "chapter_order",
        "fact_id",
        "effective_chapter_id",
        "changes",
        "entity_id",
        "entity_name",
        "from_entity_id",
        "to_entity_id",
        "from_name",
        "to_name",
        "relation_type",
        "directionality",
    )
    assert len(entity_lifecycles) == 2
    assert len(graph_changes) == 1
    assert entity_name_map == {1: "顾承渊", 2: "苏映雪"}


def test_resolve_timeline_authority_contract_rejects_missing_required_graph_change_field() -> None:
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
                first_seen_chapter=0,
                last_seen_chapter=4,
            ),
            SimpleNamespace(
                entity_id=2,
                name="苏映雪",
                entity_type="character",
                first_seen_chapter=1,
                last_seen_chapter=4,
            ),
        ],
        graph_changes=[
            SimpleNamespace(
                change_id="relation:11",
                change_kind="relation",
                chapter_id=3,
                chapter_order=3,
                fact_id="fact-11",
                effective_chapter_id=2,
                changes=[{"change_kind": "assert"}],
                entity_id=None,
                entity_name=None,
                from_entity_id=1,
                to_entity_id=2,
                from_name="顾承渊",
                to_name="苏映雪",
                directionality="directed",
            )
        ],
    )

    with pytest.raises(TimelineAuthorityContractError, match="missing required fields: relation_type"):
        _resolve_timeline_authority_contract(timeline_view)


def test_resolve_timeline_authority_contract_rejects_unsupported_relation_graph_change() -> None:
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
                first_seen_chapter=0,
                last_seen_chapter=4,
            ),
            SimpleNamespace(
                entity_id=2,
                name="苏映雪",
                entity_type="character",
                first_seen_chapter=1,
                last_seen_chapter=4,
            ),
        ],
        graph_changes=[
            SimpleNamespace(
                change_id="relation:11",
                change_kind="relation",
                chapter_id=3,
                chapter_order=3,
                fact_id="fact-11",
                effective_chapter_id=2,
                changes=[{"change_kind": "unsupported"}],
                entity_id=None,
                entity_name=None,
                from_entity_id=1,
                to_entity_id=2,
                from_name="顾承渊",
                to_name="苏映雪",
                relation_type="盟友",
                directionality="directed",
            )
        ],
    )

    with pytest.raises(TimelineAuthorityContractError, match="supported relation changes"):
        _resolve_timeline_authority_contract(timeline_view)
