from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.api.services.results_export_service import (
    _fetch_timeline_data,
    build_export_payload,
    load_aggregate_metrics_bundle,
    load_character_bundle,
    load_export_relation_bundle,
    load_graph_signal_bundle,
)
from src.knowledge.authority import (
    CanonicalEntity,
    ExportGraphAuthorityView,
    ExportRelationSnapshot,
    GraphAuthorityReport,
    GraphQualitySignals,
    GraphSharedSummary,
    RelationEvent,
)
from src.metrics.timeline_metrics import TimelineAuthorityContractError
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
    # 中文说明：export 只保留 shared timeline 语义，不导出 /timeline route-only
    # 的定位与展示字段。
    assert set(nodes_by_chunk[2]["relation_changes"][0].keys()) == {
        "from_char",
        "to_char",
        "relation_type",
        "change_type",
        "evidence",
    }


def test_build_export_payload_keeps_graph_summary_and_quality_report_separate() -> None:
    token_usage_stats = MagicMock()
    token_usage_stats.model_dump.return_value = {}

    payload = build_export_payload(
        task_id="task-1",
        novel_id="novel-1",
        novel_name="Test Novel",
        chunk_curves=[],
        characters=[],
        topics=[],
        diagnosis=None,
        chunk_styles=[],
        chunk_annotations=[],
        character_relations=[],
        hierarchical_relations=[],
        global_stats=None,
        aggregate_metrics={},
        token_usage_stats=token_usage_stats,
        graph_summary={"node_count": 3, "edge_count": 1, "density": 0.5},
        graph_quality_report={"conflict_count": 2},
        timeline_data=None,
    )

    assert payload["graph_summary"] == {"node_count": 3, "edge_count": 1, "density": 0.5}
    assert payload["graph_quality_report"] == {"conflict_count": 2}
    assert "core_characters" not in payload["graph_summary"]


def test_fetch_timeline_data_re_raises_authority_contract_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    chunk_repo = MagicMock()
    annotation_repo = MagicMock()
    stats_repo = MagicMock()

    def _raise_contract_error(*_args, **_kwargs):
        raise TimelineAuthorityContractError("broken authority contract")

    monkeypatch.setattr("src.api.services.results_export_service.build_timeline_candidates", _raise_contract_error)

    with pytest.raises(TimelineAuthorityContractError, match="broken authority contract"):
        _fetch_timeline_data(
            run_id="run-1",
            chunk_repo=chunk_repo,
            annotation_repo=annotation_repo,
            stats_repo=stats_repo,
        )


def test_load_character_bundle_uses_export_authority_entities_for_valid_names(monkeypatch: pytest.MonkeyPatch) -> None:
    diagnosis = SimpleNamespace(arc_scores={"沈砚": 8.0}, main_characters=["沈砚"])
    characters = [SimpleNamespace(name="沈砚")]

    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_diagnosis",
        lambda *_args, **_kwargs: diagnosis,
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_characters",
        lambda *_args, **_kwargs: characters,
    )

    export_graph_view = ExportGraphAuthorityView(
        canonical_entities=[
            CanonicalEntity(name="沈砚"),
            CanonicalEntity(name="陆明"),
        ]
    )

    (
        fetched_characters,
        arc_scores,
        main_characters,
        valid_character_names,
        missing_fields,
    ) = load_character_bundle(
        run_id="run-export-bundle",
        novel_id="novel-1",
        stats_repo=MagicMock(),
        annotation_repo=MagicMock(),
        alias_map={},
        export_graph_view=export_graph_view,
    )

    assert fetched_characters == characters
    assert arc_scores == {"沈砚": 8.0}
    assert main_characters == ["沈砚"]
    assert valid_character_names == {"沈砚", "陆明"}
    assert missing_fields == []


def test_load_export_relation_bundle_uses_graph_report_view_for_export(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.api.services.results_export_service._fetch_global_stats", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_token_usage_stats",
        lambda *_args, **_kwargs: SimpleNamespace(model_dump=lambda **_kw: {}),
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.aggregate_all_metrics",
        lambda *_args, **_kwargs: object(),
    )

    import src.api.routes.results_converters as results_converters

    monkeypatch.setattr(
        results_converters,
        "_convert_aggregate_result",
        lambda *_args, **_kwargs: (None, None, None, None, None),
    )

    export_graph_view = ExportGraphAuthorityView(
        current_relations=[
            ExportRelationSnapshot(
                relation_id=22,
                from_name="苏镜",
                to_name="程霜",
                relation_type="spouse_of",
                first_seen_chunk=2,
                last_seen_chunk=5,
            )
        ],
        relation_events=[
            RelationEvent(
                relation_event_id=22,
                chunk_id=5,
                from_entity_id=1,
                to_entity_id=2,
                from_name="苏镜",
                to_name="程霜",
                relation_type="spouse_of",
                change_type="新建",
            )
        ],
    )
    graph_report = GraphAuthorityReport(
        summary=GraphSharedSummary(node_count=4, edge_count=2, density=0.3333),
        quality=GraphQualitySignals(conflict_count=1, low_confidence_count=0),
    )

    (
        character_relations,
        hierarchical_relations,
        _global_stats,
        _token_usage_stats,
        _aggregate_metrics,
        graph_summary,
        graph_quality_report,
    ) = load_export_relation_bundle(
        run_id="run-graph-report",
        novel_id="novel-1",
        stats_repo=SimpleNamespace(session=object()),
        annotation_repo=MagicMock(),
        chunk_repo=MagicMock(),
        alias_map={},
        valid_character_names={"苏镜", "程霜"},
        export_graph_view=export_graph_view,
        graph_report=graph_report,
    )

    assert len(character_relations) == 1
    assert character_relations[0].from_char == "苏镜"
    assert len(hierarchical_relations) == 1
    assert hierarchical_relations[0].rel_id == 22
    assert graph_summary == {"node_count": 4, "edge_count": 2, "density": 0.3333}
    assert graph_quality_report == {"conflict_count": 1, "low_confidence_count": 0}


def test_load_graph_signal_bundle_serializes_shared_report_only() -> None:
    graph_report = GraphAuthorityReport(
        summary=GraphSharedSummary(node_count=6, edge_count=4, density=0.2667),
        quality=GraphQualitySignals(conflict_count=2, low_confidence_count=3),
    )

    graph_summary, graph_quality_report = load_graph_signal_bundle(graph_report)

    assert graph_summary == {"node_count": 6, "edge_count": 4, "density": 0.2667}
    assert graph_quality_report == {"conflict_count": 2, "low_confidence_count": 3}


def test_load_aggregate_metrics_bundle_keeps_graph_inputs_outside_aggregate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.api.services.results_export_service._fetch_global_stats", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_token_usage_stats",
        lambda *_args, **_kwargs: SimpleNamespace(model_dump=lambda **_kw: {}),
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.aggregate_all_metrics",
        lambda *_args, **_kwargs: object(),
    )

    import src.api.routes.results_converters as results_converters

    monkeypatch.setattr(
        results_converters,
        "_convert_aggregate_result",
        lambda *_args, **_kwargs: (None, None, None, None, None),
    )

    _global_stats, _token_usage_stats, aggregate_metrics = load_aggregate_metrics_bundle(
        run_id="run-aggregate-only",
        novel_id="novel-1",
        stats_repo=SimpleNamespace(session=object()),
        annotation_repo=MagicMock(),
        chunk_repo=MagicMock(),
    )

    assert set(aggregate_metrics) == {
        "narrative_structure",
        "emotion_stats",
        "character_stats",
        "style_stats",
        "culture_stats",
    }
    assert "graph_summary" not in aggregate_metrics
    assert "graph_quality_report" not in aggregate_metrics
