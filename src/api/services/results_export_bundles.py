"""结果导出 bundle 装载；查询依赖直接来自所属装配模块"""

from __future__ import annotations

from typing import Any

from src.api.services.metrics_service import get_metrics_service
from src.api.services.results_queries import (
    _fetch_chapter_annotations,
    _fetch_topics,
)
from src.api.services.results_queries.characters import _fetch_characters
from src.api.services.results_queries.diagnosis import _fetch_diagnosis, _has_diagnosis_result
from src.api.services.results_queries.graph import _fetch_character_relations, _fetch_hierarchical_relations
from src.api.services.results_queries.metadata import _fetch_global_stats, _fetch_token_usage_stats
from src.api.services.results_queries.paragraphs import _fetch_paragraph_curves
from src.fact_graph.read import ExportGraphAuthorityView, GraphAuthorityReport, serialize_graph_report_signals
from src.metrics.queries.plotline import PlotlineQuery
from src.storage import Storage
from src.storage.contracts.stores import ChapterStore, StatisticsStore

__all__ = [
    "_fetch_timeline_data",
    "load_aggregate_metrics_bundle",
    "load_chapter_bundle",
    "load_character_bundle",
    "load_core_results",
    "load_export_relation_bundle",
    "load_graph_signal_bundle",
]


def load_core_results(
    run_id: str,
    stats_repo: StatisticsStore,
    annotation_repo: Storage,
    chapter_repo: ChapterStore,
) -> tuple[list, list[str]]:
    """
    加载核心结果数据：paragraph_curves、缺失字段

    export 是复盘/比对用 payload，必须返回段落事实源
    持久化原值（fetch_paragraph_rows + fetch_paragraph_curves 按 paragraph_id
    对齐，max_points 不限制），不经过展示层降采样。

    Returns:
        (paragraph_curves, missing_fields)
    """

    missing_fields: list[str] = []

    paragraph_repo = annotation_repo.paragraphs
    paragraph_curves = _fetch_paragraph_curves(run_id, paragraph_repo, None)
    if not paragraph_curves:
        missing_fields.append("paragraph_curves")

    return paragraph_curves, missing_fields


def load_character_bundle(
    run_id: str,
    novel_id: str,
    stats_repo: StatisticsStore,
    annotation_repo: Storage,
    export_graph_view: ExportGraphAuthorityView,
    diagnosis: Any | None = None,
) -> tuple[Any, dict[str, float] | None, list[str] | None, set[str], list[str]]:
    """
    加载角色相关数据

    Returns:
        (characters, arc_scores, main_characters, valid_character_names, missing_fields)
    """

    missing_fields: list[str] = []

    if diagnosis is None:
        diagnosis = _fetch_diagnosis(run_id, novel_id, annotation_repo)
    diagnosis_is_available = _has_diagnosis_result(diagnosis)
    if not diagnosis_is_available:
        missing_fields.append("diagnosis")

    arc_scores: dict[str, float] | None = None
    focus_characters: list[str] | None = None
    main_characters: list[str] | None = None
    if diagnosis_is_available and diagnosis is not None:
        arc_scores = diagnosis.arc_scores
        focus_characters = diagnosis.focus_characters
        main_characters = diagnosis.main_characters

    characters = _fetch_characters(run_id, annotation_repo, arc_scores, focus_characters, main_characters, limit=None)
    if not characters:
        missing_fields.append("characters")
    valid_character_names = {character.name for character in characters}
    # export 过滤口径必须和同一份 authority view 对齐，避免这里再回退到
    # GraphStore 原始查询，导致 dangling 过滤与 export graph payload 分叉
    valid_character_names = valid_character_names | {
        entity.name for entity in export_graph_view.canonical_entities if entity.entity_type == "character"
    }

    return characters, arc_scores, main_characters, valid_character_names, missing_fields


def load_chapter_bundle(
    run_id: str,
    annotation_repo: Storage,
    valid_character_names: set[str],
    export_graph_view: ExportGraphAuthorityView,
) -> tuple[list, list, list[str]]:
    """
    加载分块相关数据

    Returns:
        (topics, agent_annotations, missing_fields)
    """
    missing_fields: list[str] = []

    # 切换段落：主题聚合源改为 paragraph_topics token 加权聚合
    paragraph_repo = annotation_repo.paragraphs
    topics = _fetch_topics(run_id, paragraph_repo)
    # A6：artifact 缺失导致聚合被静默清空时，给出显式原因进 missing_fields
    if not topics:
        from src.topic.artifacts import describe_topics_unavailability

        reason = describe_topics_unavailability(run_id)
        missing_fields.append(f"topics（{reason}）" if reason else "topics")

    chapter_annotations = _fetch_chapter_annotations(
        run_id,
        annotation_repo,
        valid_character_names=valid_character_names,
        export_graph_view=export_graph_view,
    )
    if not chapter_annotations:
        missing_fields.append("chapter_annotations")

    return topics, chapter_annotations, missing_fields


def load_graph_signal_bundle(
    graph_report: GraphAuthorityReport,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    加载 graph authority 输入信号

    graph_summary / graph_quality_report 在 export 里只是 graph-owned
    input signals，不承担最终诊断或聚合结论语义
    """
    return serialize_graph_report_signals(graph_report)


def load_aggregate_metrics_bundle(
    run_id: str,
    novel_id: str,
    stats_repo: StatisticsStore,
    annotation_repo: Storage,
    chapter_repo: ChapterStore,
) -> tuple[Any, Any, dict[str, Any]]:
    """
    加载非 graph 的聚合结论

    aggregate_metrics 与 /metrics/* 现在统一复用 MetricsService 的缓存入口，
    避免 export 和 metrics 各自重复跑一遍 aggregate_all_metrics()
    """

    global_stats = _fetch_global_stats(run_id, stats_repo, chapter_repo)
    token_usage_stats = _fetch_token_usage_stats(run_id, annotation_repo)

    aggregate_metrics = get_metrics_service().get_aggregate_metrics_contract(run_id, annotation_repo)

    return global_stats, token_usage_stats, aggregate_metrics


def load_export_relation_bundle(
    run_id: str,
    novel_id: str,
    stats_repo: StatisticsStore,
    annotation_repo: Storage,
    chapter_repo: ChapterStore,
    valid_character_names: set[str],
    export_graph_view: ExportGraphAuthorityView,
    graph_report: GraphAuthorityReport,
) -> tuple[list, list, Any, Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
        加载聚合统计数据

        Returns:
            (
                character_relations,
                hierarchical_relations,
                global_stats,
                token_usage_stats,
                aggregate_metrics,
                graph_summary,
                graph_quality_report,
    )
    """

    character_relations = _fetch_character_relations(
        run_id,
        annotation_repo,
        valid_character_names=valid_character_names,
        export_graph_view=export_graph_view,
    )
    hierarchical_relations = _fetch_hierarchical_relations(
        run_id,
        export_graph_view,
        valid_character_names=valid_character_names,
    )
    global_stats, token_usage_stats, aggregate_metrics = load_aggregate_metrics_bundle(
        run_id=run_id,
        novel_id=novel_id,
        stats_repo=stats_repo,
        annotation_repo=annotation_repo,
        chapter_repo=chapter_repo,
    )
    graph_summary, graph_quality_report = load_graph_signal_bundle(graph_report)

    return (
        character_relations,
        hierarchical_relations,
        global_stats,
        token_usage_stats,
        aggregate_metrics,
        graph_summary,
        graph_quality_report,
    )


def _fetch_timeline_data(
    run_id: str,
    chapter_repo: ChapterStore,
    storage: Storage,
) -> dict[str, Any] | None:
    """导出与正式页面使用同一独立变化查询，包含全部章节与变化"""
    return PlotlineQuery(storage, run_id).export()
