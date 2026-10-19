from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

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
from src.fact_graph.read import (
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
    serialize_graph_report_signals,
)
from tests.support.chapter_annotation_helpers import (
    commit_test_event_link,
    confirm_test_work,
    create_run_with_chunks,
    persist_chapter_annotation,
)
from tests.support.storage_fixtures import fixture_id, storage_for, task_for_run


def test_fetch_timeline_data_reuses_independent_plotline_contract(db_session) -> None:
    """验证新森林路径（含 nodes/causal_edges/foreshadowing_edges）"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门。\n顾霜拔剑。", "宫主现身。"],
        chapter_ids=[1, 2],
        title="事件森林时间轴导出",
    )
    eid1 = fixture_id(__name__, "evt-tl-gate-root")
    eid2 = fixture_id(__name__, "evt-tl-gate-main")
    palace_root = fixture_id(__name__, "evt-tl-palace-root")
    strike_root = fixture_id(__name__, "evt-tl-strike-root")
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜进入山门",
                "participants": ["顾霜"],
                "evidence_paragraph_id": 0,
                "node_id": eid1,
                "tree_id": "gate",
                "cause_role": "root",
                "isforeshadowing": True,
                "payoff_likelihood": "high",
            },
            {
                "description": "顾霜拔剑",
                "participants": ["顾霜"],
                "evidence_paragraph_id": 1,
                "node_id": eid2,
                "parent_node_id": eid1,
                "tree_id": "gate",
                "cause_role": "main",
            },
        ],
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        events=[
            {
                "description": "宫主现身",
                "participants": ["宫主"],
                "evidence_paragraph_id": 2,
                "node_id": palace_root,
                "tree_id": "palace",
                "cause_role": "root",
            },
            {
                "description": "宫主出手",
                "participants": ["宫主"],
                "evidence_paragraph_id": 2,
                "node_id": strike_root,
                "tree_id": "strike",
                "cause_role": "root",
            },
        ],
    )
    from datetime import UTC, datetime

    from sqlalchemy import select

    from src.storage.models import NarrativeLink

    commit_test_event_link(
        db_session,
        run_id=run_id,
        chapter_id=2,
        source_event_id=eid2,
        target_event_id=palace_root,
    )
    commit_test_event_link(
        db_session,
        run_id=run_id,
        chapter_id=2,
        source_event_id=palace_root,
        target_event_id=strike_root,
    )
    # 跨树链路的活动观察沿用正式列：这里显式置一条为非活动/已过期
    inactive_link = db_session.execute(
        select(NarrativeLink).where(
            NarrativeLink.semantic_source_declaration_id == eid2,
            NarrativeLink.semantic_target_declaration_id == palace_root,
        )
    ).scalar_one()
    inactive_link.is_active = False
    inactive_link.expired_at = datetime.now(UTC)
    db_session.commit()

    from tests.support.diagnosis_helpers import declaration_event_draft, persist_event_draft

    persist_event_draft(db_session, declaration_event_draft(db_session, run_id))
    chapter_repo = storage_for(db_session)
    stats_repo = storage_for(db_session)

    timeline_data = _fetch_timeline_data(
        run_id=run_id,
        chapter_repo=chapter_repo,
        storage=stats_repo,
    )

    assert timeline_data is not None
    from src.metrics.queries.plotline import PlotlineQuery

    expected = PlotlineQuery(storage_for(db_session), run_id).fetch(through_chapter_id=2, limit=500)
    assert timeline_data == expected
    assert timeline_data["through_chapter_id"] == 2
    assert len(timeline_data["chapters"]) == 2
    assert timeline_data["total"] == 1
    assert timeline_data["changes"][0]["action"] == "setup"
    from sqlalchemy import distinct

    from src.storage.models import CompleteEvent, EventDeclarationBinding

    bound_events = list(
        db_session.scalars(
            select(distinct(CompleteEvent.event_id))
            .join(EventDeclarationBinding, EventDeclarationBinding.event_id == CompleteEvent.event_id)
            .where(EventDeclarationBinding.declaration_id == eid1)
        )
    )
    assert timeline_data["changes"][0]["source_event_ids"] == bound_events
    assert "causal_edges" not in timeline_data


def test_build_export_payload_keeps_graph_summary_and_quality_report_separate() -> None:
    token_usage_stats = MagicMock()
    token_usage_stats.model_dump.return_value = {}

    payload = build_export_payload(
        task_id="task-1",
        novel_id=fixture_id(__name__, "novel-1"),
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


def test_load_character_bundle_uses_export_authority_entities_for_valid_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """diagnosis 完整合同已经包含 genre_labels/style_labels，测试桩需要同步提供正式字段。"""

    diagnosis = SimpleNamespace(
        arc_scores={"沈砚": 8.0},
        genre_labels=["通用"],
        style_labels=["严肃"],
        focus_structure="single",
        focus_characters=["沈砚"],
        topic_labels={"0": "成长"},
        main_characters=["沈砚"],
        core_cast=["沈砚"],
    )
    characters = [SimpleNamespace(name="沈砚")]

    patch_export_dependency(monkeypatch, "_fetch_diagnosis", lambda *_args, **_kwargs: diagnosis)
    patch_export_dependency(monkeypatch, "_fetch_characters", lambda *_args, **_kwargs: characters)

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
        run_id=fixture_id(__name__, "run-export-bundle"),
        novel_id=fixture_id(__name__, "novel-1"),
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

    patch_export_dependency(monkeypatch, "_fetch_diagnosis", _fake_fetch_diagnosis)
    patch_export_dependency(monkeypatch, "_fetch_characters", lambda *_args, **_kwargs: characters)

    export_graph_view = ExportGraphAuthorityView(
        canonical_entities=[
            CanonicalEntity(name="沈砚"),
        ]
    )

    fetched_characters, arc_scores, main_characters, valid_names, missing_fields = load_character_bundle(
        run_id=fixture_id(__name__, "run-export-bundle"),
        novel_id=fixture_id(__name__, "novel-1"),
        stats_repo=MagicMock(),
        annotation_repo=annotation_repo,
        export_graph_view=export_graph_view,
    )

    assert fetched_characters == characters
    assert arc_scores is None
    assert main_characters is None
    assert valid_names == {"沈砚"}
    assert missing_fields == []


def test_fetch_all_results_data_deduplicates_missing_diagnosis_marker(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    """export 返回前必须去重，避免 `missing_fields` 出现重复 diagnosis 条目。"""

    monkeypatch.setattr(
        "src.api.services.results_export_service.load_core_results",
        lambda *_args, **_kwargs: ([], []),
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service.load_character_bundle",
        lambda *_args, **_kwargs: ([], None, None, set(), ["diagnosis"]),
    )
    patch_export_dependency(monkeypatch, "_fetch_diagnosis", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "src.api.services.results_export_service.load_chapter_bundle",
        lambda *_args, **_kwargs: ([], [], []),
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_foreshadowing_trees",
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
            "nodes": [],
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

    novel_id, run_id = create_run_with_chunks(db_session, texts=["导出测试。"])
    confirm_test_work(db_session, run_id)
    from tests.support.diagnosis_helpers import declaration_event_draft, persist_event_draft

    persist_event_draft(db_session, declaration_event_draft(db_session, run_id))
    db_session.commit()
    results_data, missing_fields, novel_name = fetch_all_results_data(
        novel_id=novel_id,
        task_id=task_for_run(run_id, db_session),
        run_id=run_id,
        stats_repo=MagicMock(session=db_session),
        annotation_repo=storage_for(db_session),
        chapter_repo=storage_for(db_session),
    )

    assert results_data["diagnosis"] is None
    assert missing_fields.count("diagnosis") == 1
    assert novel_name == "Test Novel"


def test_load_character_bundle_excludes_non_character_canonical_entities_from_character_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """diagnosis 完整合同已经包含 genre_labels/style_labels，测试桩需要同步提供正式字段。"""

    diagnosis = SimpleNamespace(
        arc_scores={"沈砚": 8.0},
        genre_labels=["通用"],
        style_labels=["严肃"],
        focus_structure="single",
        focus_characters=["沈砚"],
        topic_labels={"0": "成长"},
        main_characters=["沈砚"],
        core_cast=["沈砚"],
    )
    characters = [SimpleNamespace(name="沈砚")]

    patch_export_dependency(monkeypatch, "_fetch_diagnosis", lambda *_args, **_kwargs: diagnosis)
    patch_export_dependency(monkeypatch, "_fetch_characters", lambda *_args, **_kwargs: characters)

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
        run_id=fixture_id(__name__, "run-export-bundle"),
        novel_id=fixture_id(__name__, "novel-1"),
        stats_repo=MagicMock(),
        annotation_repo=MagicMock(),
        export_graph_view=export_graph_view,
    )

    assert valid_character_names == {"沈砚"}


def test_load_core_results_keeps_export_on_raw_paragraph_curves(monkeypatch: pytest.MonkeyPatch) -> None:
    """load_core_results 从段落事实源导出原始曲线（不降采样、
    不复用 chunk 展示层融合曲线），缺失字段语义同步为 paragraph_curves。
    """
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

    patch_export_dependency(monkeypatch, "_fetch_paragraph_curves", lambda *_args, **_kwargs: [paragraph_point])

    paragraph_curves, missing_fields = load_core_results(
        run_id=fixture_id(__name__, "run-export-curves"),
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
    patch_export_dependency(
        monkeypatch,
        "_fetch_character_relations",
        lambda *_args, **_kwargs: [SimpleNamespace(from_char="苏镜", to_char="程霜", type="隶属")],
    )
    patch_export_dependency(
        monkeypatch, "_fetch_hierarchical_relations", lambda *_args, **_kwargs: [SimpleNamespace(rel_id="relation-22")]
    )
    patch_export_dependency(monkeypatch, "_fetch_global_stats", lambda *_args, **_kwargs: None)
    patch_export_dependency(
        monkeypatch, "_fetch_token_usage_stats", lambda *_args, **_kwargs: SimpleNamespace(model_dump=lambda **_kw: {})
    )
    metrics_service = MagicMock()
    metrics_service.get_aggregate_metrics_contract.return_value = {
        "narrative_structure": None,
        "emotion_stats": None,
        "character_stats": None,
        "style_stats": None,
    }
    patch_export_dependency(monkeypatch, "get_metrics_service", lambda: metrics_service)

    export_graph_view = ExportGraphAuthorityView(
        current_relations=[
            ExportRelationSnapshot(
                relation_id=fixture_id(__name__, "relation-22"),
                from_name="苏镜",
                to_name="程霜",
                relation_type="隶属",
                first_seen_chapter=2,
                last_seen_chapter=5,
            ),
            ExportRelationSnapshot(
                relation_id=fixture_id(__name__, "relation-23"),
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
                from_entity_id=fixture_id(__name__, "1"),
                to_entity_id=fixture_id(__name__, "2"),
                from_name="苏镜",
                to_name="程霜",
                relation_type="家族",
                relation_id=fixture_id(__name__, "relation-22"),
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
        run_id=fixture_id(__name__, "run-graph-report"),
        novel_id=fixture_id(__name__, "novel-1"),
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
    patch_export_dependency(monkeypatch, "_fetch_global_stats", lambda *_args, **_kwargs: None)
    patch_export_dependency(
        monkeypatch, "_fetch_token_usage_stats", lambda *_args, **_kwargs: SimpleNamespace(model_dump=lambda **_kw: {})
    )
    metrics_service = MagicMock()
    metrics_service.get_aggregate_metrics_contract.return_value = {
        "narrative_structure": None,
        "emotion_stats": None,
        "character_stats": None,
        "style_stats": None,
    }
    patch_export_dependency(monkeypatch, "get_metrics_service", lambda: metrics_service)

    _global_stats, _token_usage_stats, aggregate_metrics = load_aggregate_metrics_bundle(
        run_id=fixture_id(__name__, "run-aggregate-only"),
        novel_id=fixture_id(__name__, "novel-1"),
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
            novel_id=fixture_id(__name__, "novel-1"),
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
    """拦截与 event_forest 无关的兄弟 loader，保留真实 EventForestQuery 读取

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
    patch_export_dependency(monkeypatch, "_fetch_diagnosis", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "src.api.services.results_export_service.load_chapter_bundle",
        lambda *_args, **_kwargs: ([], [], []),
    )
    monkeypatch.setattr(
        "src.api.services.results_export_service._fetch_foreshadowing_trees",
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
            "nodes": [],
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


def test_fetch_all_results_data_emits_full_book_organization(db_session, monkeypatch) -> None:
    """验证导出 payload 包含事件森林段（树视图/因果边/伏笔边）"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门。\n顾霜立誓。"],
        title="导出事件森林",
    )
    eid1 = fixture_id(__name__, "evt-export-gate-root")
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        events=[
            {
                "description": "顾霜进入山门",
                "participants": ["顾霜"],
                "evidence_paragraph_id": 0,
                "node_id": eid1,
                "tree_id": "gate",
                "cause_role": "root",
                "isforeshadowing": True,
                "payoff_likelihood": "high",
            },
            {
                "description": "顾霜立誓",
                "participants": ["顾霜"],
                "evidence_paragraph_id": 1,
                "node_id": fixture_id(__name__, "evt-export-gate-main"),
                "parent_node_id": eid1,
                "tree_id": "gate",
                "cause_role": "main",
            },
        ],
    )
    db_session.commit()

    from sqlalchemy import select

    from src.event_trees import storage_map as smap
    from src.storage.models import CompleteEvent
    from tests.support.diagnosis_helpers import declaration_event_draft, persist_event_draft

    persist_event_draft(db_session, declaration_event_draft(db_session, run_id))
    event = db_session.scalar(
        select(CompleteEvent).where(
            CompleteEvent.producer_agent_id.in_(smap.run_execution_ids(storage_for(db_session), run_id))
        )
    )
    event_id = event.event_id

    _stub_export_sibling_loaders(monkeypatch)

    results_data, _missing_fields, _novel_name = fetch_all_results_data(
        novel_id=_novel_id,
        task_id=task_for_run(run_id, db_session),
        run_id=run_id,
        stats_repo=storage_for(db_session),
        annotation_repo=storage_for(db_session),
        chapter_repo=storage_for(db_session),
    )

    from src.event_trees.read.organization import EventTreeQuery

    tree = results_data["event_trees"]
    assert tree == EventTreeQuery(storage_for(db_session), run_id).export()
    assert tree["counts"]["all_events"] == 2
    assert tree["counts"]["declarations"] == 2
    assert event_id in [entry["event_id"] for entry in tree["details"]]
    assert "event_forest" not in results_data


def test_fetch_all_results_data_emits_empty_organization_for_no_events(db_session, monkeypatch) -> None:
    """无事件时导出空组织与导航根"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["未标注原文。"],
        title="空事件森林",
    )
    db_session.commit()
    confirm_test_work(db_session, run_id)

    _stub_export_sibling_loaders(monkeypatch)

    results_data, _missing_fields, _novel_name = fetch_all_results_data(
        novel_id=_novel_id,
        task_id=task_for_run(run_id, db_session),
        run_id=run_id,
        stats_repo=storage_for(db_session),
        annotation_repo=storage_for(db_session),
        chapter_repo=storage_for(db_session),
    )

    assert results_data["event_trees"]["counts"]["all_events"] == 0
    assert results_data["event_trees"]["arcs"] == []
    assert results_data["event_trees"]["events"] == []


def patch_export_dependency(monkeypatch, name, value):
    """同一读取依赖在两个装配点分别注入，不靠反向导入共享测试替身"""
    monkeypatch.setattr("src.api.services.results_export_service." + name, value)
    monkeypatch.setattr("src.api.services.results_export_bundles." + name, value)
