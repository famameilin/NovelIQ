from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.knowledge.authority import TIMELINE_AUTHORITY_DEPENDENCY_FIELDS, KnowledgeGraphAuthorityService
from src.metrics.timeline_metrics import (
    TimelineAuthorityContractError,
    _resolve_timeline_authority_contract,
    build_timeline_candidates,
)
from src.storage.repositories import AnnotationRepository, ChunkRepository, StatsRepository
from tests.support.timeline_contract_helpers import (
    create_timeline_contract_scenario,
    index_by_chunk_id,
    relation_change_names,
    relation_change_tuples,
)


def test_build_timeline_candidates_consumes_authority_character_subgraph_only(db_session) -> None:
    scenario = create_timeline_contract_scenario(db_session)

    chunk_repo = ChunkRepository(db_session)
    annotation_repo = AnnotationRepository(db_session)
    stats_repo = StatsRepository(db_session)

    timeline_view = KnowledgeGraphAuthorityService.from_session(db_session).build_timeline_view(scenario.run_id)
    timeline_build = build_timeline_candidates(
        scenario.run_id,
        chunk_repo,
        annotation_repo,
        stats_repo,
        timeline_view,
    )

    candidates = timeline_build.candidates
    tension_scores = timeline_build.selection_inputs.tension_scores
    chunk_ids = timeline_build.selection_inputs.chunk_ids
    total_chunks = timeline_build.total_chunks
    timeline_phases = timeline_build.phases
    major_character_entries = timeline_build.selection_inputs.major_character_entries
    relation_break_events = timeline_build.selection_inputs.relation_break_events

    candidates_by_chunk = index_by_chunk_id(candidates)

    assert chunk_ids == [0, 1, 2, 3, 4]
    assert tension_scores == [0.15, 0.3, 0.95, 0.45, 0.1]
    assert total_chunks == 5
    assert len(timeline_phases) == 4

    # Only character lifecycles should contribute to timeline entry/exit hints.
    assert {name for name, _ in major_character_entries} == {scenario.hero_name, scenario.rival_name}
    assert scenario.organization_name not in {name for name, _ in major_character_entries}

    assert candidates_by_chunk[0].character_entries == [scenario.hero_name]
    assert candidates_by_chunk[1].character_entries == [scenario.rival_name]
    assert candidates_by_chunk[3].character_exits == [scenario.rival_name]
    assert candidates_by_chunk[4].character_exits == [scenario.hero_name]

    # Relation changes should come only from character-character authority events.
    assert relation_change_tuples(candidates_by_chunk[2].relation_changes) == {
        (scenario.hero_name, scenario.rival_name, "新建")
    }
    assert scenario.organization_name not in relation_change_names(candidates_by_chunk[2].relation_changes)

    assert relation_change_tuples(candidates_by_chunk[4].relation_changes) == {
        (scenario.hero_name, scenario.rival_name, "断裂")
    }
    assert len(relation_break_events) == 1
    assert relation_break_events[0][0] == 4
    assert relation_break_events[0][1].from_char == scenario.hero_name
    assert relation_break_events[0][1].to_char == scenario.rival_name


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
        character_entities=[
            SimpleNamespace(entity_id=1, name="顾承渊", entity_type="character"),
        ],
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
        character_entities=[
            SimpleNamespace(entity_id=1, name="顾承渊", entity_type="character"),
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


def test_resolve_timeline_authority_contract_rejects_duplicate_character_entity_ids() -> None:
    timeline_view = SimpleNamespace(
        character_entities=[
            SimpleNamespace(entity_id=1, name="顾承渊", entity_type="character"),
            SimpleNamespace(entity_id=1, name="顾承渊", entity_type="character"),
        ],
        entity_lifecycles=[
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


def test_resolve_timeline_authority_contract_accepts_allowlist_only_shape() -> None:
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
                chunk_id=2,
                from_entity_id=1,
                to_entity_id=2,
                relation_type="盟友",
                change_type="新建",
                evidence="并肩迎敌",
            )
        ],
    )

    entity_lifecycles, relation_events, entity_name_map = _resolve_timeline_authority_contract(timeline_view)

    assert TIMELINE_AUTHORITY_DEPENDENCY_FIELDS["relation_events"] == (
        "chunk_id",
        "from_entity_id",
        "to_entity_id",
        "relation_type",
        "change_type",
        "evidence",
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
                chunk_id=2,
                from_entity_id=1,
                to_entity_id=2,
                change_type="新建",
                evidence="并肩迎敌",
            )
        ],
    )

    with pytest.raises(TimelineAuthorityContractError, match="missing required fields: relation_type"):
        _resolve_timeline_authority_contract(timeline_view)
