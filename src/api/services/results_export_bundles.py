"""
结果导出 bundle 装载服务

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分（results_export_service.py → results_export_bundles.py）
说明: 自 src/api/services/results_export_service.py 拆出各 bundle 装载函数
（load_core_results/load_character_bundle/load_chapter_bundle/load_graph_signal_bundle/
load_aggregate_metrics_bundle/load_export_relation_bundle/_fetch_timeline_data），
行为保持不变。

其中结果获取依赖（_fetch_paragraph_curves/_fetch_diagnosis/_fetch_characters/
_fetch_global_stats/_fetch_token_usage_stats/_fetch_character_relations/
_fetch_hierarchical_relations/get_metrics_service）按调用期经
src/api/services/results_export_service 模块命名空间解析（函数内延迟导入），
与原同模块全局查找语义完全一致（含测试对上述名称的 monkeypatch），且不产生导入期循环。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.api.services.results_queries import (
    _fetch_chapter_annotations,
    _fetch_topics,
)
from src.api.services.results_queries.diagnosis import _has_diagnosis_result
from src.knowledge.authority import (
    ExportGraphAuthorityView,
    GraphAuthorityReport,
    serialize_graph_report_signals,
)
from src.metrics.event_timeline_metrics import (
    build_event_timeline_plan,
    serialize_event_timeline_node,
    serialize_event_timeline_phases,
)
from src.storage.repositories import (
    AnnotationRepository,
    ChapterRepository,
    ParagraphRepository,
    StatsRepository,
)

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
    stats_repo: StatsRepository,
    annotation_repo: AnnotationRepository,
    chapter_repo: ChapterRepository,
) -> tuple[list, list[str]]:
    """
    加载核心结果数据：paragraph_curves、缺失字段

    2026-08-14 M8a：results export 是复盘/比对用 payload，必须返回段落事实源
    持久化原值（fetch_paragraph_rows + fetch_paragraph_curves 按 paragraph_id
    对齐，max_points 不限制），不经过展示层降采样。

    Returns:
        (paragraph_curves, missing_fields)
    """
    from src.api.services.results_export_service import _fetch_paragraph_curves

    missing_fields: list[str] = []

    paragraph_repo = ParagraphRepository(annotation_repo.session)
    paragraph_curves = _fetch_paragraph_curves(run_id, paragraph_repo, None)
    if not paragraph_curves:
        missing_fields.append("paragraph_curves")

    return paragraph_curves, missing_fields


def load_character_bundle(
    run_id: str,
    novel_id: str,
    stats_repo: StatsRepository,
    annotation_repo: AnnotationRepository,
    export_graph_view: ExportGraphAuthorityView,
    diagnosis: Any | None = None,
) -> tuple[Any, dict[str, float] | None, list[str] | None, set[str], list[str]]:
    """
    加载角色相关数据

    Returns:
        (characters, arc_scores, main_characters, valid_character_names, missing_fields)
    """
    from src.api.services.results_export_service import _fetch_characters, _fetch_diagnosis

    missing_fields: list[str] = []

    if diagnosis is None:
        diagnosis = _fetch_diagnosis(run_id, novel_id, stats_repo)
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
    # GraphRepository 原始查询，导致 dangling 过滤与 export graph payload 分叉
    valid_character_names = valid_character_names | {
        entity.name for entity in export_graph_view.canonical_entities if entity.entity_type == "character"
    }

    return characters, arc_scores, main_characters, valid_character_names, missing_fields


def load_chapter_bundle(
    run_id: str,
    annotation_repo: AnnotationRepository,
    valid_character_names: set[str],
    export_graph_view: ExportGraphAuthorityView,
) -> tuple[list, list, list[str]]:
    """
    加载分块相关数据

    2026-08-14 M8a：chunk_styles 已从 export 移除（前端 M4 已切换段落端点，
    风格消费在 M8b 段落化切换后再处理）。

    Returns:
        (topics, chapter_annotations, missing_fields)
    """
    missing_fields: list[str] = []

    # 2026-08-14 切换段落：主题聚合源改为 paragraph_topics token 加权聚合（§11.1）
    paragraph_repo = ParagraphRepository(annotation_repo.session)
    topics = _fetch_topics(run_id, paragraph_repo)
    # 2026-09-05 A6：artifact 缺失导致聚合被静默清空时，给出显式原因进 missing_fields
    if not topics:
        from src.api.services.results_queries.topics import describe_topics_unavailability

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
    stats_repo: StatsRepository,
    annotation_repo: AnnotationRepository,
    chapter_repo: ChapterRepository,
) -> tuple[Any, Any, dict[str, Any]]:
    """
    加载非 graph 的聚合结论

    aggregate_metrics 与 /metrics/* 现在统一复用 MetricsService 的缓存入口，
    避免 export 和 metrics 各自重复跑一遍 aggregate_all_metrics()
    """
    from src.api.services.results_export_service import (
        _fetch_global_stats,
        _fetch_token_usage_stats,
        get_metrics_service,
    )

    global_stats = _fetch_global_stats(run_id, stats_repo, chapter_repo)
    token_usage_stats = _fetch_token_usage_stats(run_id, novel_id, stats_repo)

    aggregate_metrics = get_metrics_service().get_aggregate_metrics_contract(run_id, stats_repo.session)

    return global_stats, token_usage_stats, aggregate_metrics


def load_export_relation_bundle(
    run_id: str,
    novel_id: str,
    stats_repo: StatsRepository,
    annotation_repo: AnnotationRepository,
    chapter_repo: ChapterRepository,
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
    from src.api.services.results_export_service import (
        _fetch_character_relations,
        _fetch_hierarchical_relations,
    )

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
    chapter_repo: ChapterRepository,
    stats_repo: StatsRepository,
) -> dict[str, Any] | None:
    """获取用于导出的事件森林时间轴数据"""
    from src.storage.repositories.graph import EventForestRepository

    snapshot = EventForestRepository(stats_repo.session).fetch_snapshot(run_id)
    if snapshot is None:
        logger.warning(f"No event forest snapshot for run {run_id}")
        return None
    timeline_plan = build_event_timeline_plan(
        run_id,
        chapter_repo,
        stats_repo,
        snapshot,
    )
    return {
        "phases": serialize_event_timeline_phases(timeline_plan.phases),
        "nodes": [serialize_event_timeline_node(node) for node in timeline_plan.nodes],
        "causal_edges": [
            {
                "edge_id": e.edge_id,
                "edge_type": e.edge_type,
                "source_event_id": e.source_event_id,
                "target_event_id": e.target_event_id,
                "source_chapter_id": e.source_chapter_id,
                "target_chapter_id": e.target_chapter_id,
                "is_active": e.is_active,
                "evidence": list(e.evidence),
                "expired_at": e.expired_at.isoformat() if e.expired_at else None,
            }
            for e in snapshot.causal_edges
        ],
        "foreshadowing_edges": [
            {
                "root_event_id": fe.root_event_id,
                "payoff_event_id": fe.payoff_event_id,
                "first_chapter_id": fe.first_chapter_id,
                "last_chapter_id": fe.last_chapter_id,
                "description": fe.description,
                "status": fe.status,
                "active": fe.active,
            }
            for fe in snapshot.foreshadowing_edges
        ],
        "derived_event_order": timeline_plan.derived_event_order,
        "tension_curve": timeline_plan.tension_curve,
        "total_chapters": timeline_plan.total_chapters,
        "phase_basis": timeline_plan.phase_basis,
    }
