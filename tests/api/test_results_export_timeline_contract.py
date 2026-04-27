from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.api.exceptions import DiagnosisRerunRequiredError, GraphReadinessError
from src.api.services.results_export_service import (
    _fetch_timeline_data,
    build_export_payload,
    fetch_all_results_data,
    load_aggregate_metrics_bundle,
    load_character_bundle,
    load_core_results,
    load_export_relation_bundle,
    load_graph_signal_bundle,
)
from src.knowledge.authority import (
    CanonicalEntity,
    ExportGraphAuthorityView,
    ExportRelationSnapshot,
    GraphAuthorityReport,
    GraphAuthorityView,
    GraphPageQualityDetails,
    GraphPageSummary,
    GraphQualitySignals,
    GraphSharedSummary,
    KnowledgeGraphAuthorityService,
    RelationEvent,
    serialize_graph_report_signals,
)
from src.metrics.timeline_metrics import TimelineAuthorityContractError
from src.models.cloud.schema import CloudAnalysis
from src.storage.models import ChunkRelation
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
    timeline_view = KnowledgeGraphAuthorityService.from_session(db_session).build_timeline_view(scenario.run_id)

    timeline_data = _fetch_timeline_data(
        run_id=scenario.run_id,
        chunk_repo=chunk_repo,
        annotation_repo=annotation_repo,
        stats_repo=stats_repo,
        timeline_view=timeline_view,
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
        aggregate_metrics={
            "narrative_structure": None,
            "emotion_stats": None,
            "character_stats": None,
            "style_stats": None,
        },
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
            timeline_view=MagicMock(),
        )


def test_fetch_timeline_data_re_raises_unexpected_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    chunk_repo = MagicMock()
    annotation_repo = MagicMock()
    stats_repo = MagicMock()

    def _raise_runtime_error(*_args, **_kwargs):
        raise RuntimeError("timeline boom")

    monkeypatch.setattr("src.api.services.results_export_service.build_timeline_candidates", _raise_runtime_error)

    with pytest.raises(RuntimeError, match="timeline boom"):
        _fetch_timeline_data(
            run_id="run-1",
            chunk_repo=chunk_repo,
            annotation_repo=annotation_repo,
            stats_repo=stats_repo,
            timeline_view=MagicMock(),
        )


def test_load_character_bundle_uses_export_authority_entities_for_valid_names(monkeypatch: pytest.MonkeyPatch) -> None:
    diagnosis = SimpleNamespace(
        rerun_required=False,
        arc_scores={"沈砚": 8.0},
        focus_structure="single",
        focus_characters=["沈砚"],
        topic_labels=["成长"],
        main_characters=["沈砚"],
        core_cast=["沈砚"],
    )
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


def test_load_character_bundle_rejects_rerun_required_diagnosis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnosis = SimpleNamespace(
        rerun_required=True,
        rerun_reason="diagnosis_missing_focus_contract",
        foreshadow_expectation=0.58,
        arc_scores=None,
        focus_structure=None,
        focus_characters=None,
        main_characters=None,
        core_cast=None,
    )
    characters = [SimpleNamespace(name="沈砚")]
    annotation_repo = MagicMock()

    def _fake_fetch_diagnosis(_run_id, _novel_id, _stats_repo, _annotation_repo, _alias_map):
        return diagnosis

    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_diagnosis",
        _fake_fetch_diagnosis,
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_characters",
        lambda *_args, **_kwargs: characters,
    )

    export_graph_view = ExportGraphAuthorityView(
        canonical_entities=[
            CanonicalEntity(name="沈砚"),
        ]
    )

    with pytest.raises(DiagnosisRerunRequiredError) as exc_info:
        load_character_bundle(
            run_id="run-export-bundle",
            novel_id="novel-1",
            stats_repo=MagicMock(),
            annotation_repo=annotation_repo,
            alias_map={},
            export_graph_view=export_graph_view,
        )

    assert exc_info.value.reason == "diagnosis_missing_focus_contract"


def test_fetch_all_results_data_deduplicates_missing_diagnosis_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    创建时间: 2026-04-26
    创建者: Codex
    任务: fix-diagnosis-followup-review-findings
    说明: diagnosis 缺失可能在多个 bundle 链路里被检测到；
    export 返回前必须去重，避免 `missing_fields` 出现重复 diagnosis 条目。
    """

    from src.api.services.results_export_service import fetch_all_results_data

    monkeypatch.setattr(
        "src.api.services.results_export_service.load_core_results",
        lambda *_args, **_kwargs: ([], []),
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.load_character_bundle",
        lambda *_args, **_kwargs: ([], None, None, set(), ["diagnosis"]),
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_diagnosis",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.load_chunk_bundle",
        lambda *_args, **_kwargs: ([], [], [], []),
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_foreshadowing_threads",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.load_export_relation_bundle",
        lambda *_args, **_kwargs: ([], [], None, SimpleNamespace(model_dump=lambda **_kw: {}), {}, {}, {}),
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_novel_name",
        lambda *_args, **_kwargs: "Test Novel",
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_timeline_data",
        lambda *_args, **_kwargs: {"nodes": [], "phases": [], "tension_curve": [], "total_chunks": 0},
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.build_export_payload",
        lambda **kwargs: kwargs,
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: SimpleNamespace(
            assert_graph_projection_ready=lambda _run_id: None,
            build_export_view=lambda _run_id: ExportGraphAuthorityView(),
            build_graph_report=lambda _run_id: GraphAuthorityReport(
                summary=GraphSharedSummary(node_count=0, edge_count=0, density=0.0),
                quality=GraphQualitySignals(conflict_count=0, low_confidence_count=0),
            ),
            build_timeline_view=lambda _run_id: SimpleNamespace(
                character_entities=[],
                entity_lifecycles=[],
                relation_events=[],
            ),
        ),
    )

    results_data, missing_fields, novel_name = fetch_all_results_data(
        novel_id="novel-1",
        task_id="task-1",
        run_id="run-1",
        stats_repo=MagicMock(session=MagicMock()),
        annotation_repo=MagicMock(fetch_alias_map=lambda _run_id: {}),
        chunk_repo=MagicMock(),
    )

    assert results_data["diagnosis"] is None
    assert missing_fields.count("diagnosis") == 1
    assert novel_name == "Test Novel"


def test_fetch_all_results_data_raises_for_rerun_required_diagnosis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.api.services.results_export_service.load_core_results",
        lambda *_args, **_kwargs: ([], []),
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.load_character_bundle",
        lambda *_args, **_kwargs: ([], None, None, set(), []),
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_diagnosis",
        lambda *_args, **_kwargs: SimpleNamespace(
            rerun_required=True,
            rerun_reason="focus_contract_incomplete",
        ),
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: SimpleNamespace(
            assert_graph_projection_ready=lambda _run_id: None,
            build_export_view=lambda _run_id: ExportGraphAuthorityView(),
            build_graph_report=lambda _run_id: GraphAuthorityReport(
                summary=GraphSharedSummary(node_count=0, edge_count=0, density=0.0),
                quality=GraphQualitySignals(conflict_count=0, low_confidence_count=0),
            ),
            build_timeline_view=lambda _run_id: SimpleNamespace(
                character_entities=[],
                entity_lifecycles=[],
                relation_events=[],
            ),
        ),
    )

    with pytest.raises(DiagnosisRerunRequiredError) as exc_info:
        fetch_all_results_data(
            novel_id="novel-1",
            task_id="task-1",
            run_id="run-1",
            stats_repo=MagicMock(session=MagicMock()),
            annotation_repo=MagicMock(fetch_alias_map=lambda _run_id: {}),
            chunk_repo=MagicMock(),
        )

    assert exc_info.value.reason == "focus_contract_incomplete"


def test_fetch_all_results_data_rejects_partial_pending_graph_projection(db_session) -> None:
    scenario = create_timeline_contract_scenario(db_session)
    StatsRepository(db_session).insert_cloud_analysis(
        scenario.run_id,
        CloudAnalysis(
            novel_id=scenario.novel_id,
            foreshadow_expectation=0.42,
            arc_scores={
                scenario.hero_name: 8.6,
                scenario.rival_name: 7.8,
            },
            narrative_type="双线推进",
            topic_labels=["冲突升级"],
            diagnosis="有效 diagnosis",
            narrative_arc_type="落坑爬出",
            focus_structure="dual",
            focus_characters=[scenario.hero_name, scenario.rival_name],
            main_characters=[scenario.hero_name, scenario.rival_name],
            core_cast=[scenario.hero_name, scenario.rival_name],
        ),
    )
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

    stats_repo = StatsRepository(db_session)
    annotation_repo = AnnotationRepository(db_session)
    chunk_repo = ChunkRepository(db_session)

    with pytest.raises(GraphReadinessError, match="graph projection is still pending"):
        fetch_all_results_data(
            novel_id=scenario.novel_id,
            task_id=scenario.task_id,
            run_id=scenario.run_id,
            stats_repo=stats_repo,
            annotation_repo=annotation_repo,
            chunk_repo=chunk_repo,
        )


def test_load_character_bundle_excludes_non_character_canonical_entities_from_character_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnosis = SimpleNamespace(
        rerun_required=False,
        arc_scores={"沈砚": 8.0},
        focus_structure="single",
        focus_characters=["沈砚"],
        topic_labels=["成长"],
        main_characters=["沈砚"],
        core_cast=["沈砚"],
    )
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
            CanonicalEntity(name="沈砚", entity_type="character"),
            CanonicalEntity(name="青云门", entity_type="organization"),
        ]
    )

    (
        _fetched_characters,
        _arc_scores,
        _main_characters,
        valid_character_names,
        _missing_fields,
    ) = load_character_bundle(
        run_id="run-export-bundle",
        novel_id="novel-1",
        stats_repo=MagicMock(),
        annotation_repo=MagicMock(),
        alias_map={},
        export_graph_view=export_graph_view,
    )

    assert valid_character_names == {"沈砚"}


def test_load_core_results_keeps_export_on_raw_chunk_curves(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_curve = SimpleNamespace(
        chunk_id=7,
        pos_density=0.12,
        neg_density=0.03,
        net_density=0.09,
        smoothed_density=0.08,
        tension_proxy=0.41,
        tension_composite=0.39,
    )

    def _raise_if_display_curve_is_used(*_args, **_kwargs):
        raise AssertionError("load_core_results should not reuse display-layer fused chunk curves")

    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_raw_chunk_curves",
        lambda *_args, **_kwargs: [raw_curve],
    )
    monkeypatch.setattr(
        "src.api.routes.results_fetchers.fetchers._fetch_chunk_curves",
        _raise_if_display_curve_is_used,
    )

    chunk_curves, missing_fields = load_core_results(
        run_id="run-export-curves",
        stats_repo=MagicMock(),
        annotation_repo=MagicMock(),
        chunk_repo=MagicMock(),
    )

    assert missing_fields == []
    assert len(chunk_curves) == 1
    assert chunk_curves[0].chunk_id == 7
    assert chunk_curves[0].pos_density == pytest.approx(0.12)
    assert chunk_curves[0].net_density == pytest.approx(0.09)
    assert chunk_curves[0].smoothed_density == pytest.approx(0.08)


def test_load_export_relation_bundle_uses_graph_report_view_for_export(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.api.services.results_export_service._fetch_global_stats", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_token_usage_stats",
        lambda *_args, **_kwargs: SimpleNamespace(model_dump=lambda **_kw: {}),
    )
    metrics_service = MagicMock()
    metrics_service.get_aggregate_metrics_contract.return_value = {
        "narrative_structure": None,
        "emotion_stats": None,
        "character_stats": None,
        "style_stats": None,
    }
    monkeypatch.setattr("src.api.services.results_export_service.get_metrics_service", lambda: metrics_service)

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
            ,
            ExportRelationSnapshot(
                relation_id=23,
                from_name="苏镜",
                to_name="旧友",
                relation_type="spouse_of",
                first_seen_chunk=1,
                last_seen_chunk=4,
                is_active=False,
            ),
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


def test_shared_graph_signal_serializer_rejects_non_report_consumers() -> None:
    with pytest.raises(TypeError, match="shared graph signal consumers require GraphAuthorityReport"):
        serialize_graph_report_signals(
            GraphAuthorityView(
                canonical_entities=[],
                confirmed_relations=[],
                relation_events=[],
                participant_states=[],
            )
        )

    with pytest.raises(TypeError, match="shared graph signal consumers require GraphAuthorityReport"):
        serialize_graph_report_signals(GraphPageSummary(node_count=2, edge_count=1, density=0.5))

    with pytest.raises(TypeError, match="shared graph signal consumers require GraphAuthorityReport"):
        serialize_graph_report_signals(GraphPageQualityDetails(conflict_count=1, low_confidence_count=2))


def test_load_aggregate_metrics_bundle_keeps_graph_inputs_outside_aggregate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.api.services.results_export_service._fetch_global_stats", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_token_usage_stats",
        lambda *_args, **_kwargs: SimpleNamespace(model_dump=lambda **_kw: {}),
    )
    metrics_service = MagicMock()
    metrics_service.get_aggregate_metrics_contract.return_value = {
        "narrative_structure": None,
        "emotion_stats": None,
        "character_stats": None,
        "style_stats": None,
    }
    monkeypatch.setattr("src.api.services.results_export_service.get_metrics_service", lambda: metrics_service)

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
    }
    assert "graph_summary" not in aggregate_metrics
    assert "graph_quality_report" not in aggregate_metrics


def test_build_export_payload_rejects_graph_fields_inside_aggregate_metrics() -> None:
    token_usage_stats = MagicMock()
    token_usage_stats.model_dump.return_value = {}

    with pytest.raises(ValueError, match="aggregate_metrics must not include graph-owned fields: graph_summary"):
        build_export_payload(
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
            aggregate_metrics={
                "narrative_structure": None,
                "emotion_stats": None,
                "character_stats": None,
                "style_stats": None,
                "graph_summary": {},
            },
            token_usage_stats=token_usage_stats,
            graph_summary={"node_count": 3, "edge_count": 1, "density": 0.5},
            graph_quality_report={"conflict_count": 2},
            timeline_data=None,
        )
