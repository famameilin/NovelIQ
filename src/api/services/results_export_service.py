"""
结果导出服务

说明: 从 results.py 提取的结果导出逻辑，负责数据获取和组装
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from src.api.dependencies import get_metrics_service
from src.api.exceptions import DiagnosisRerunRequiredError
from src.api.services.results_contracts import validate_aggregate_metrics_contract
from src.api.services.results_queries import (
    _fetch_chapter_annotations,
    _fetch_character_relations,
    _fetch_characters,
    _fetch_diagnosis,
    _fetch_foreshadowing_threads,
    _fetch_global_stats,
    _fetch_hierarchical_relations,
    _fetch_novel_name,
    _fetch_paragraph_curves,
    _fetch_token_usage_stats,
    _fetch_topics,
)
from src.api.services.results_queries.diagnosis import _is_complete_diagnosis_result
from src.knowledge.authority import (
    ExportGraphAuthorityView,
    GraphAuthorityReport,
    KnowledgeGraphAuthorityService,
    TimelineAuthorityView,
    serialize_graph_report_signals,
)
from src.metrics.timeline_metrics import (
    TimelineAuthorityContractError,
    TimelineDataUnavailableError,
    build_timeline_plan,
    serialize_timeline_composite_node,
    serialize_timeline_node,
    serialize_timeline_phases,
)
from src.storage.repositories import (
    AnnotationRepository,
    ChapterRepository,
    ParagraphRepository,
    StatsRepository,
)


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
    missing_fields: list[str] = []

    if diagnosis is None:
        diagnosis = _fetch_diagnosis(run_id, novel_id, stats_repo)
    if diagnosis is not None and diagnosis.rerun_required:
        raise DiagnosisRerunRequiredError(reason=diagnosis.rerun_reason)
    diagnosis_is_complete = _is_complete_diagnosis_result(diagnosis)
    if not diagnosis_is_complete:
        missing_fields.append("diagnosis")

    arc_scores: dict[str, float] | None = None
    focus_characters: list[str] | None = None
    main_characters: list[str] | None = None
    if diagnosis_is_complete and diagnosis is not None:
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
    annotation_repo: AnnotationRepository,
    stats_repo: StatsRepository,
    timeline_view: TimelineAuthorityView,
) -> dict[str, Any] | None:
    """
    获取时间轴数据用于导出

    Returns:
        时间轴数据字典，包含 phases, composite_nodes, atomic_nodes, tension_curve

    Contract note:
        Export intentionally reuses the same authority-backed timeline helper
        as the /timeline route so both surfaces stay aligned on character
        lifecycles and character-character relation history
    """
    try:
        timeline_plan = build_timeline_plan(
            run_id,
            chapter_repo,
            annotation_repo,
            stats_repo,
            timeline_view,
        )
    except TimelineDataUnavailableError as e:
        logger.warning(f"No chunk data for run {run_id}: {e}")
        return None
    except TimelineAuthorityContractError:
        logger.error(f"Timeline authority contract violated for run {run_id}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error building timeline for run {run_id}: {e}")
        raise

    return {
        "phases": serialize_timeline_phases(timeline_plan.phases),
        "composite_nodes": [serialize_timeline_composite_node(node) for node in timeline_plan.composite_nodes],
        "atomic_nodes": [serialize_timeline_node(node) for node in timeline_plan.atomic_nodes],
        "tension_curve": timeline_plan.tension_curve,
        "total_chapters": timeline_plan.total_chapters,
    }


def build_export_payload(
    task_id: str,
    novel_id: str,
    novel_name: str | None,
    paragraph_curves: list,
    characters: list,
    topics: list,
    diagnosis: Any,
    chapter_annotations: list,
    character_relations: list,
    hierarchical_relations: list,
    global_stats: Any,
    aggregate_metrics: dict[str, Any],
    token_usage_stats: Any,
    foreshadowing_threads: list | None = None,
    graph_summary: dict[str, Any] | None = None,
    graph_quality_report: dict[str, Any] | None = None,
    timeline_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    构建导出 payload
    """
    # export payload 中的 aggregate_metrics 只允许保留 aggregate 结论，
    # 这里在最终装配前再次做运行时校验，防止后续改动把 graph signals 混回去
    validate_aggregate_metrics_contract(aggregate_metrics)
    return {
        "task_id": task_id,
        "novel_id": novel_id,
        "novel_name": novel_name,
        "generated_at": datetime.now().isoformat(),
        "total_chapters": global_stats.total_chapters if global_stats else 0,
        "paragraph_curves": [c.model_dump(exclude_none=True) for c in paragraph_curves],
        "characters": [c.model_dump(exclude_none=True) for c in characters],
        "topics": [t.model_dump(exclude_none=True) for t in topics],
        "diagnosis": diagnosis.model_dump(exclude_none=True) if diagnosis else None,
        "chapter_annotations": [a.model_dump(exclude_none=True) for a in chapter_annotations],
        "foreshadowing_threads": [
            thread.model_dump(exclude_none=True) for thread in (foreshadowing_threads or [])
        ],
        "character_relations": [r.model_dump(exclude_none=True) for r in character_relations],
        "hierarchical_relations": [r.model_dump(exclude_none=True) for r in hierarchical_relations],
        "global_stats": global_stats.model_dump(exclude_none=True) if global_stats else None,
        "aggregate_metrics": aggregate_metrics,
        "token_usage_stats": token_usage_stats.model_dump(exclude_none=True),
        "graph_summary": graph_summary or {},
        "graph_quality_report": graph_quality_report or {},
        "timeline": timeline_data,
    }


def fetch_all_results_data(
    novel_id: str,
    task_id: str,
    run_id: str,
    stats_repo: StatsRepository,
    annotation_repo: AnnotationRepository,
    chapter_repo: ChapterRepository,
) -> tuple[dict[str, Any], list[str], str | None]:
    """
    获取所有分析结果数据
    """
    diagnosis = _fetch_diagnosis(run_id, novel_id, stats_repo)
    if diagnosis is not None and diagnosis.rerun_required:
        raise DiagnosisRerunRequiredError(reason=diagnosis.rerun_reason)

    graph_authority_service = KnowledgeGraphAuthorityService.from_session(stats_repo.session)
    graph_authority_service.assert_graph_ready(run_id)
    export_graph_view = graph_authority_service.build_export_view(run_id)
    graph_report = graph_authority_service.build_graph_report(run_id)
    timeline_view = graph_authority_service.build_timeline_view(run_id)

    paragraph_curves, missing_fields = load_core_results(run_id, stats_repo, annotation_repo, chapter_repo)

    characters, arc_scores, main_characters, valid_character_names, char_missing = load_character_bundle(
        run_id, novel_id, stats_repo, annotation_repo, export_graph_view, diagnosis=diagnosis
    )
    missing_fields.extend(char_missing)

    if not _is_complete_diagnosis_result(diagnosis):
        missing_fields.append("diagnosis")
        diagnosis = None

    topics, chapter_annotations, chapter_missing = load_chapter_bundle(
        run_id,
        annotation_repo,
        valid_character_names,
        export_graph_view,
    )
    missing_fields.extend(chapter_missing)
    foreshadowing_threads = _fetch_foreshadowing_threads(run_id, annotation_repo)

    (
        character_relations,
        hierarchical_relations,
        global_stats,
        token_usage_stats,
        aggregate_metrics,
        graph_summary,
        graph_quality_report,
    ) = load_export_relation_bundle(
        run_id,
        novel_id,
        stats_repo,
        annotation_repo,
        chapter_repo,
        valid_character_names,
        export_graph_view,
        graph_report,
    )

    novel_name = _fetch_novel_name(run_id, novel_id, stats_repo)

    # 获取时间轴数据
    timeline_data = _fetch_timeline_data(
        run_id=run_id,
        chapter_repo=chapter_repo,
        annotation_repo=annotation_repo,
        stats_repo=stats_repo,
        timeline_view=timeline_view,
    )
    if not timeline_data:
        missing_fields.append("timeline")

    # missing_fields 对外语义是“缺哪些字段”，不是“缺了几次”；
    # 这里在最终返回前按插入顺序去重，避免 diagnosis 被重复追加
    missing_fields = list(dict.fromkeys(missing_fields))

    results_data = build_export_payload(
        task_id=task_id,
        novel_id=novel_id,
        novel_name=novel_name,
        paragraph_curves=paragraph_curves,
        characters=characters,
        topics=topics,
        diagnosis=diagnosis,
        chapter_annotations=chapter_annotations,
        foreshadowing_threads=foreshadowing_threads,
        character_relations=character_relations,
        hierarchical_relations=hierarchical_relations,
        global_stats=global_stats,
        aggregate_metrics=aggregate_metrics,
        token_usage_stats=token_usage_stats,
        graph_summary=graph_summary,
        graph_quality_report=graph_quality_report,
        timeline_data=timeline_data,
    )

    return results_data, missing_fields, novel_name
