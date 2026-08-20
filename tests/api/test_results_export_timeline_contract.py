from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import NAMESPACE_URL, uuid5

import pytest

from src.agents.annotation.schema import BoundForeshadowing
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
    GraphChange,
    GraphPageQualityDetails,
    GraphPageSummary,
    GraphQualitySignals,
    GraphSharedSummary,
    KnowledgeGraphAuthorityService,
    serialize_graph_report_signals,
)
from src.metrics.timeline_metrics import TimelineAuthorityContractError
from src.storage.repositories import (
    AnnotationRepository,
    ChapterRepository,
    ForeshadowingRepository,
    StatsRepository,
)
from tests.support.chapter_annotation_helpers import (
    create_run_with_chunks,
    persist_chapter_annotation,
)
from tests.support.timeline_contract_helpers import (
    create_timeline_contract_scenario,
    graph_change_names,
    graph_change_tuples,
    nodes_for_anchor_chapter,
)


def test_fetch_timeline_data_reuses_authority_backed_contract(db_session) -> None:
    scenario = create_timeline_contract_scenario(db_session)

    chapter_repo = ChapterRepository(db_session)
    annotation_repo = AnnotationRepository(db_session)
    stats_repo = StatsRepository(db_session)
    timeline_view = KnowledgeGraphAuthorityService.from_session(db_session).build_timeline_view(scenario.run_id)

    timeline_data = _fetch_timeline_data(
        run_id=scenario.run_id,
        chapter_repo=chapter_repo,
        annotation_repo=annotation_repo,
        stats_repo=stats_repo,
        timeline_view=timeline_view,
    )

    assert timeline_data is not None
    assert timeline_data["total_chapters"] == 5
    assert timeline_data["tension_curve"] == [0.6, 0.7, 0.9, 0.5, 0.4]
    assert len(timeline_data["phases"]) == 4

    relation_node = next(
        node
        for node in nodes_for_anchor_chapter(timeline_data["atomic_nodes"], 3)
        if node["node_type"] == "relation"
    )
    assert graph_change_tuples(relation_node["graph_changes"]) == {
        (scenario.hero_name, scenario.rival_name, "assert")
    }
    assert scenario.organization_name not in graph_change_names(relation_node["graph_changes"])

    assert "entity_lifecycles" not in timeline_data
    assert set(relation_node.keys()) == {
        "node_id",
        "anchor_chapter_id",
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
        "graph_changes",
        "lifecycle_events",
    }
    assert set(relation_node["graph_changes"][0].keys()) == {
        "change_id",
        "change_kind",
        "chapter_id",
        "fact_id",
        "effective_chapter_id",
        "changes",
        "entity_id",
        "entity_name",
        "relation_id",
        "from_char",
        "to_char",
        "relation_type",
        "relation_change_kind",
        "directionality",
    }
    assert timeline_data["composite_nodes"]
    composite_relation_node = next(
        node
        for node in nodes_for_anchor_chapter(timeline_data["composite_nodes"], 3)
        if node["node_type"] == "relation"
    )
    assert composite_relation_node["representative_node_id"].startswith("relation:")


def test_build_export_payload_keeps_graph_summary_and_quality_report_separate() -> None:
    token_usage_stats = MagicMock()
    token_usage_stats.model_dump.return_value = {}

    payload = build_export_payload(
        task_id="task-1",
        novel_id="novel-1",
        novel_name="Test Novel",
        paragraph_curves=[],
        characters=[],
        topics=[],
        diagnosis=None,
        chapter_annotations=[],
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
    chapter_repo = MagicMock()
    annotation_repo = MagicMock()
    stats_repo = MagicMock()

    def _raise_contract_error(*_args, **_kwargs):
        raise TimelineAuthorityContractError("broken authority contract")

    monkeypatch.setattr("src.api.services.results_export_service.build_timeline_plan", _raise_contract_error)

    with pytest.raises(TimelineAuthorityContractError, match="broken authority contract"):
        _fetch_timeline_data(
            run_id="run-1",
            chapter_repo=chapter_repo,
            annotation_repo=annotation_repo,
            stats_repo=stats_repo,
            timeline_view=MagicMock(),
        )


def test_fetch_timeline_data_re_raises_unexpected_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    chapter_repo = MagicMock()
    annotation_repo = MagicMock()
    stats_repo = MagicMock()

    def _raise_runtime_error(*_args, **_kwargs):
        raise RuntimeError("timeline boom")

    monkeypatch.setattr("src.api.services.results_export_service.build_timeline_plan", _raise_runtime_error)

    with pytest.raises(RuntimeError, match="timeline boom"):
        _fetch_timeline_data(
            run_id="run-1",
            chapter_repo=chapter_repo,
            annotation_repo=annotation_repo,
            stats_repo=stats_repo,
            timeline_view=MagicMock(),
        )


def test_load_character_bundle_uses_export_authority_entities_for_valid_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    修改时间: 2026-04-29
    任务: 修复全量测试阻塞
    修改原因: diagnosis 完整合同已经包含 genre_labels/style_labels，测试桩需要同步提供正式字段。
    """

    diagnosis = SimpleNamespace(
        arc_scores={"沈砚": 8.0},
        genre_labels=["通用"],
        style_labels=["严肃"],
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
        export_graph_view=export_graph_view,
    )

    assert fetched_characters == characters
    assert arc_scores == {"沈砚": 8.0}
    assert main_characters == ["沈砚"]
    assert valid_character_names == {"沈砚", "陆明"}
    assert missing_fields == []


def test_load_character_bundle_accepts_partial_diagnosis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnosis = SimpleNamespace(
        foreshadow_expectation=0.58,
        arc_scores=None,
        focus_structure=None,
        focus_characters=None,
        main_characters=None,
        core_cast=None,
    )
    characters = [SimpleNamespace(name="沈砚")]
    annotation_repo = MagicMock()

    def _fake_fetch_diagnosis(_run_id, _novel_id, _stats_repo):
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

    fetched_characters, arc_scores, main_characters, valid_names, missing_fields = load_character_bundle(
        run_id="run-export-bundle",
        novel_id="novel-1",
        stats_repo=MagicMock(),
        annotation_repo=annotation_repo,
        export_graph_view=export_graph_view,
    )

    assert fetched_characters == characters
    assert arc_scores is None
    assert main_characters is None
    assert valid_names == {"沈砚"}
    assert missing_fields == []


def test_fetch_all_results_data_deduplicates_missing_diagnosis_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    创建时间: 2026-04-26
    任务: fix-diagnosis-followup-review-findings
    说明: diagnosis 缺失可能在多个 bundle 链路里被检测到；
    export 返回前必须去重，避免 `missing_fields` 出现重复 diagnosis 条目。
    """

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
        "src.api.services.results_export_service.load_chapter_bundle",
        lambda *_args, **_kwargs: ([], [], []),
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
        lambda *_args, **_kwargs: {
            "atomic_nodes": [],
            "composite_nodes": [],
            "phases": [],
            "tension_curve": [],
            "total_chapters": 0,
        },
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.build_export_payload",
        lambda **kwargs: kwargs,
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: SimpleNamespace(
            assert_graph_ready=lambda _run_id: None,
            build_export_view=lambda _run_id: ExportGraphAuthorityView(),
            build_graph_report=lambda _run_id: GraphAuthorityReport(
                summary=GraphSharedSummary(node_count=0, edge_count=0, density=0.0),
                quality=GraphQualitySignals(conflict_count=0, low_confidence_count=0),
            ),
            build_timeline_view=lambda _run_id: SimpleNamespace(
                character_entities=[],
                entity_lifecycles=[],
                graph_changes=[],
            ),
        ),
    )

    results_data, missing_fields, novel_name = fetch_all_results_data(
        novel_id="novel-1",
        task_id="task-1",
        run_id="run-1",
        stats_repo=MagicMock(session=MagicMock()),
        annotation_repo=MagicMock(),
        chapter_repo=MagicMock(),
    )

    assert results_data["diagnosis"] is None
    assert missing_fields.count("diagnosis") == 1
    assert novel_name == "Test Novel"




def test_load_character_bundle_excludes_non_character_canonical_entities_from_character_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    修改时间: 2026-04-29
    任务: 修复全量测试阻塞
    修改原因: diagnosis 完整合同已经包含 genre_labels/style_labels，测试桩需要同步提供正式字段。
    """

    diagnosis = SimpleNamespace(
        arc_scores={"沈砚": 8.0},
        genre_labels=["通用"],
        style_labels=["严肃"],
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
        export_graph_view=export_graph_view,
    )

    assert valid_character_names == {"沈砚"}


def test_load_core_results_keeps_export_on_raw_paragraph_curves(monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-08-14 M8a：load_core_results 从段落事实源导出原始曲线（不降采样、
    不复用 chunk 展示层融合曲线），缺失字段语义同步为 paragraph_curves。"""
    paragraph_point = SimpleNamespace(
        paragraph_id=7,
        chapter_id=1,
        paragraph_index=0,
        global_start_char=100,
        global_end_char=200,
        position=0.1,
        char_count=100,
        token_count=50,
        pos_density=0.12,
        neg_density=0.03,
        net_density=0.09,
        smoothed_net_density=0.08,
        surface_tension=0.41,
        smoothed_surface_tension=0.39,
    )

    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_paragraph_curves",
        lambda *_args, **_kwargs: [paragraph_point],
    )

    paragraph_curves, missing_fields = load_core_results(
        run_id="run-export-curves",
        stats_repo=MagicMock(),
        annotation_repo=MagicMock(session=MagicMock()),
        chapter_repo=MagicMock(),
    )

    assert missing_fields == []
    assert len(paragraph_curves) == 1
    assert paragraph_curves[0].paragraph_id == 7
    assert paragraph_curves[0].pos_density == pytest.approx(0.12)
    assert paragraph_curves[0].net_density == pytest.approx(0.09)
    assert paragraph_curves[0].smoothed_net_density == pytest.approx(0.08)


def test_load_export_relation_bundle_uses_graph_report_view_for_export(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_character_relations",
        lambda *_args, **_kwargs: [
            SimpleNamespace(from_char="苏镜", to_char="程霜", type="隶属")
        ],
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_hierarchical_relations",
        lambda *_args, **_kwargs: [SimpleNamespace(rel_id="relation-22")],
    )
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
                relation_id="relation-22",
                from_name="苏镜",
                to_name="程霜",
                relation_type="隶属",
                first_seen_chapter=2,
                last_seen_chapter=5,
            ),
            ExportRelationSnapshot(
                relation_id="relation-23",
                from_name="苏镜",
                to_name="旧友",
                relation_type="家族",
                first_seen_chapter=1,
                last_seen_chapter=4,
                is_active=False,
            ),
        ],
        graph_changes=[
            GraphChange(
                change_id="relation:22",
                change_kind="relation",
                chapter_id=5,
                chapter_order=5,
                fact_id="fact-22",
                effective_chapter_id=5,
                confidence="high",
                changes=[{"change_kind": "assert"}],
                from_entity_id=1,
                to_entity_id=2,
                from_name="苏镜",
                to_name="程霜",
                relation_type="家族",
                relation_id="relation-22",
                directionality="directed",
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
        chapter_repo=MagicMock(),
        valid_character_names={"苏镜", "程霜"},
        export_graph_view=export_graph_view,
        graph_report=graph_report,
    )

    assert len(character_relations) == 1
    assert character_relations[0].from_char == "苏镜"
    assert len(hierarchical_relations) == 1
    assert hierarchical_relations[0].rel_id == "relation-22"
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
                graph_changes=[],
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
        chapter_repo=MagicMock(),
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
            paragraph_curves=[],
            characters=[],
            topics=[],
            diagnosis=None,
            chapter_annotations=[],
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


def _stub_export_sibling_loaders(monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-08-18 用于拦截与 event_forest 无关的兄弟 loader，保留真实 EventForestRepository 读取

    对照组：test_fetch_all_results_data_deduplicates_missing_diagnosis_marker。
    """
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
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.load_chapter_bundle",
        lambda *_args, **_kwargs: ([], [], []),
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_foreshadowing_threads",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.load_export_relation_bundle",
        lambda *_args, **_kwargs: (
            [],
            [],
            None,
            SimpleNamespace(model_dump=lambda **_kw: {}),
            {
                "narrative_structure": None,
                "emotion_stats": None,
                "character_stats": None,
                "style_stats": None,
            },
            {},
            {},
        ),
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_novel_name",
        lambda *_args, **_kwargs: "Test Novel",
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_timeline_data",
        lambda *_args, **_kwargs: {
            "atomic_nodes": [],
            "composite_nodes": [],
            "phases": [],
            "tension_curve": [],
            "total_chapters": 0,
        },
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: SimpleNamespace(
            assert_graph_ready=lambda _run_id: None,
            build_export_view=lambda _run_id: ExportGraphAuthorityView(),
            build_graph_report=lambda _run_id: GraphAuthorityReport(
                summary=GraphSharedSummary(node_count=0, edge_count=0, density=0.0),
                quality=GraphQualitySignals(conflict_count=0, low_confidence_count=0),
            ),
            build_timeline_view=lambda _run_id: SimpleNamespace(
                character_entities=[],
                entity_lifecycles=[],
                graph_changes=[],
            ),
        ),
    )


def test_fetch_all_results_data_emits_event_forest_section(db_session, monkeypatch) -> None:
    """2026-08-19 用于验证导出 payload 包含事件森林段（树视图/因果边/伏笔边契约 v3）"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门。\n顾霜立誓。"],
        title="导出事件森林",
    )
    eid1 = str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:1"))
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜进入山门",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "tree_id": "gate",
                "cause_role": "root",
            },
            {
                "description": "顾霜立誓",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [1],
                "causal_event_refs": [eid1],
                "tree_id": "gate",
                "cause_role": "main",
            },
        ],
    )
    ForeshadowingRepository(db_session).sync(
        run_id=run_id,
        chapter_id=1,
        foreshadowing=BoundForeshadowing(
            description="顾霜承诺护佑山门",
            confidence="high",
            setup_event_index=1,
        ),
        setup_event_id=eid1,
    )
    db_session.commit()

    _stub_export_sibling_loaders(monkeypatch)

    results_data, _missing_fields, _novel_name = fetch_all_results_data(
        novel_id=_novel_id,
        task_id=run_id[:8],
        run_id=run_id,
        stats_repo=StatsRepository(db_session),
        annotation_repo=AnnotationRepository(db_session),
        chapter_repo=ChapterRepository(db_session),
    )

    forest = results_data["event_forest"]
    assert forest != {}
    assert forest["chapter_order"] == 1
    nodes = {node["event_id"]: node for node in forest["event_nodes"]}
    assert set(nodes) == {
        eid1,
        str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:2")),
    }
    assert nodes[eid1]["description"] == "顾霜进入山门"
    assert nodes[eid1]["tree_id"] == "gate"
    assert nodes[eid1]["cause_role"] == "root"

    # 树视图 + 因果边（contains 派生化：event_edges 键移除）
    assert "event_edges" not in forest
    trees = {tree["tree_id"]: tree for tree in forest["event_trees"]}
    assert trees["gate"]["main_chain"] == [
        eid1,
        str(uuid5(NAMESPACE_URL, f"noveliq:event:{run_id}:1:2")),
    ]
    causal_edges = forest["causal_edges"]
    assert len(causal_edges) == 1
    assert causal_edges[0]["source_event_id"] == eid1

    assert len(forest["foreshadowing_edges"]) == 1
    assert forest["foreshadowing_edges"][0]["setup_event_id"] == eid1
    assert forest["foreshadowing_edges"][0]["payoff_event_id"] is None


def test_fetch_all_results_data_emits_empty_event_forest_for_unannotated_run(db_session, monkeypatch) -> None:
    """2026-08-18 用于验证无事件标注的 run 导出 event_forest 为空对象"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["未标注原文。"],
        title="空事件森林",
    )
    db_session.commit()

    _stub_export_sibling_loaders(monkeypatch)

    results_data, _missing_fields, _novel_name = fetch_all_results_data(
        novel_id=_novel_id,
        task_id=run_id[:8],
        run_id=run_id,
        stats_repo=StatsRepository(db_session),
        annotation_repo=AnnotationRepository(db_session),
        chapter_repo=ChapterRepository(db_session),
    )

    assert results_data["event_forest"] == {}
