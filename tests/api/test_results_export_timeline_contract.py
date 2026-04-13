from __future__ import annotations

from src.api.services.results_export_service import _fetch_timeline_data
from src.storage.repositories import AnnotationRepository, ChunkRepository, StatsRepository
from tests.support.timeline_contract_helpers import (
    create_timeline_contract_scenario,
    index_by_chunk_id,
    relation_change_names,
    relation_change_tuples,
)


def test_fetch_timeline_data_reuses_authority_backed_contract(db_session) -> None:
    scenario = create_timeline_contract_scenario(db_session)

    chunk_repo = ChunkRepository(db_session)
    annotation_repo = AnnotationRepository(db_session)
    stats_repo = StatsRepository(db_session)

    timeline_data = _fetch_timeline_data(
        run_id=scenario.run_id,
        chunk_repo=chunk_repo,
        annotation_repo=annotation_repo,
        stats_repo=stats_repo,
    )

    assert timeline_data is not None
    assert timeline_data["total_chunks"] == 5
    assert timeline_data["tension_curve"] == [0.15, 0.3, 0.95, 0.45, 0.1]
    assert len(timeline_data["phases"]) == 4

    nodes_by_chunk = index_by_chunk_id(timeline_data["nodes"])
    assert relation_change_tuples(nodes_by_chunk[2]["relation_changes"]) == {
        (scenario.hero_name, scenario.rival_name, "新建")
    }
    assert scenario.organization_name not in relation_change_names(nodes_by_chunk[2]["relation_changes"])
    assert relation_change_tuples(nodes_by_chunk[4]["relation_changes"]) == {
        (scenario.hero_name, scenario.rival_name, "断裂")
    }

    # Export keeps the current public shape and must not leak authority internals.
    assert "entity_lifecycles" not in timeline_data
    assert set(nodes_by_chunk[2].keys()) == {
        "chunk_id",
        "progress",
        "importance_score",
        "level",
        "event",
        "characters",
        "is_pivot",
        "is_cliffhanger",
        "tension_percentile",
        "node_type",
        "relation_changes",
        "character_entries",
        "character_exits",
    }
    assert set(nodes_by_chunk[2]["relation_changes"][0].keys()) == {
        "from_char",
        "to_char",
        "relation_type",
        "change_type",
        "evidence",
    }
