"""
结果导出服务

说明: 从 results.py 提取的结果导出逻辑，负责数据获取和组装

本模块保留 build_export_payload/fetch_all_results_data，并 re-export 全部装载函数与
结果获取依赖（tests 会对本模块命名空间中的 _fetch_* 与 get_metrics_service 打补丁，
装载函数亦按调用期经本模块命名空间解析同名依赖，语义保持不变）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from loguru import logger

from src.api.models.responses import ResultsWriteResponse
from src.api.services.metrics_service import get_metrics_service
from src.api.services.results_contracts import validate_aggregate_metrics_contract
from src.api.services.results_export_bundles import (
    _fetch_timeline_data,
    load_aggregate_metrics_bundle,
    load_chapter_bundle,
    load_character_bundle,
    load_core_results,
    load_export_relation_bundle,
    load_graph_signal_bundle,
)
from src.api.services.results_queries import (
    _fetch_character_relations,
    _fetch_characters,
    _fetch_diagnosis,
    _fetch_foreshadowing_trees,
    _fetch_global_stats,
    _fetch_hierarchical_relations,
    _fetch_novel_name,
    _fetch_paragraph_curves,
    _fetch_token_usage_stats,
)
from src.api.services.results_queries.diagnosis import _has_diagnosis_result
from src.config import settings
from src.storage.repositories import (
    AnnotationRepository,
    ChapterRepository,
    StatsRepository,
)
from src.storage.repositories.graph.authority import KnowledgeGraphAuthorityService

__all__ = [
    "_fetch_character_relations",
    "_fetch_characters",
    "_fetch_diagnosis",
    "_fetch_foreshadowing_trees",
    "_fetch_global_stats",
    "_fetch_hierarchical_relations",
    "_fetch_novel_name",
    "_fetch_paragraph_curves",
    "_fetch_timeline_data",
    "_fetch_token_usage_stats",
    "build_export_payload",
    "fetch_all_results_data",
    "get_metrics_service",
    "load_aggregate_metrics_bundle",
    "load_chapter_bundle",
    "load_character_bundle",
    "load_core_results",
    "load_export_relation_bundle",
    "load_graph_signal_bundle",
]


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
    foreshadowing_trees: list | None = None,
    graph_summary: dict[str, Any] | None = None,
    graph_quality_report: dict[str, Any] | None = None,
    timeline_data: dict[str, Any] | None = None,
    event_forest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    构建导出 payload

    2026-08-18：新增 event_forest 段，包含事件、边、锚点和直接引用的 Evidence。
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
        "foreshadowing_trees": [tree.model_dump(exclude_none=True) for tree in (foreshadowing_trees or [])],
        "character_relations": [r.model_dump(exclude_none=True) for r in character_relations],
        "hierarchical_relations": [r.model_dump(exclude_none=True) for r in hierarchical_relations],
        "global_stats": global_stats.model_dump(exclude_none=True) if global_stats else None,
        "aggregate_metrics": aggregate_metrics,
        "token_usage_stats": token_usage_stats.model_dump(exclude_none=True),
        "graph_summary": graph_summary or {},
        "graph_quality_report": graph_quality_report or {},
        "timeline": timeline_data,
        "event_forest": event_forest or {},
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
    graph_authority_service = KnowledgeGraphAuthorityService.from_session(stats_repo.session)
    graph_authority_service.assert_graph_ready(run_id)
    export_graph_view = graph_authority_service.build_export_view(run_id)
    graph_report = graph_authority_service.build_graph_report(run_id)

    paragraph_curves, missing_fields = load_core_results(run_id, stats_repo, annotation_repo, chapter_repo)

    characters, arc_scores, main_characters, valid_character_names, char_missing = load_character_bundle(
        run_id, novel_id, stats_repo, annotation_repo, export_graph_view, diagnosis=diagnosis
    )
    missing_fields.extend(char_missing)

    if not _has_diagnosis_result(diagnosis):
        missing_fields.append("diagnosis")

    topics, chapter_annotations, chapter_missing = load_chapter_bundle(
        run_id,
        annotation_repo,
        valid_character_names,
        export_graph_view,
    )
    missing_fields.extend(chapter_missing)
    foreshadowing_trees = _fetch_foreshadowing_trees(run_id, annotation_repo)

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

    novel_name = _fetch_novel_name(novel_id, stats_repo)

    # 2026-08-19 事件森林/DAG：导出 event_forest 段（ 树视图 + 树间边）
    from src.storage.repositories.graph import EventForestRepository

    event_forest_repo = EventForestRepository(stats_repo.session)
    event_forest_snapshot = event_forest_repo.fetch_snapshot(run_id)
    event_forest_data: dict[str, Any] | None = None
    if event_forest_snapshot is not None:
        event_forest_data = {
            "chapter_id": event_forest_snapshot.chapter_id,
            "chapter_order": event_forest_snapshot.chapter_order,
            "visible_through_chapter_order": event_forest_snapshot.visible_through_chapter_order,
            "derived_event_order": event_forest_snapshot.derived_event_order,
            "event_nodes": [
                {
                    "event_id": node.event_id,
                    "chapter_id": node.chapter_id,
                    "chapter_order": node.chapter_order,
                    "description": node.description,
                    "participants": node.participants,
                    "anchor_paragraph_ids": node.anchor_paragraph_ids,
                    "char_start": node.char_start,
                    "char_end": node.char_end,
                    "evidence": node.evidence,
                    "causal_event_refs": node.causal_event_refs,
                    "tree_id": node.tree_id,
                    "cause_role": node.cause_role,
                }
                for node in event_forest_snapshot.event_nodes
            ],
            "event_trees": [
                {
                    "tree_id": tree.tree_id,
                    "root_event_id": tree.root_event_id,
                    "main_chain": tree.main_chain,
                    "secondary_groups": [
                        {
                            "target_event_id": group.target_event_id,
                            "branch": group.branch,
                        }
                        for group in tree.secondary_groups
                    ],
                    "chapter_ids": tree.chapter_ids,
                    "char_start": tree.char_start,
                    "char_end": tree.char_end,
                }
                for tree in event_forest_snapshot.event_trees
            ],
            "causal_edges": [
                {
                    "edge_id": edge.edge_id,
                    "edge_type": edge.edge_type,
                    "source_event_id": edge.source_event_id,
                    "target_event_id": edge.target_event_id,
                    "source_chapter_id": edge.source_chapter_id,
                    "target_chapter_id": edge.target_chapter_id,
                    "is_active": edge.is_active,
                    "evidence": edge.evidence,
                    "expired_at": edge.expired_at.isoformat() if edge.expired_at else None,
                }
                for edge in event_forest_snapshot.causal_edges
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
                for fe in event_forest_snapshot.foreshadowing_edges
            ],
        }

    # 获取时间轴数据（仅新森林路径）
    timeline_data = _fetch_timeline_data(
        run_id=run_id,
        chapter_repo=chapter_repo,
        stats_repo=stats_repo,
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
        foreshadowing_trees=foreshadowing_trees,
        character_relations=character_relations,
        hierarchical_relations=hierarchical_relations,
        global_stats=global_stats,
        aggregate_metrics=aggregate_metrics,
        token_usage_stats=token_usage_stats,
        graph_summary=graph_summary,
        graph_quality_report=graph_quality_report,
        timeline_data=timeline_data,
        event_forest=event_forest_data,
    )
    from src.storage.repositories.book_state import book_state_view

    results_data["pipeline"] = book_state_view(stats_repo.session, run_id)

    return results_data, missing_fields, novel_name


def build_results_response(
    file_path: str, novel_id: str, novel_name: str | None, missing_fields: list[str]
) -> ResultsWriteResponse:
    """
    构建结果响应对象
    """
    return ResultsWriteResponse(
        success=True,
        message="分析结果已写入文件",
        file_path=file_path,
        novel_id=novel_id,
        novel_name=novel_name,
        missing_fields=missing_fields if missing_fields else None,
    )


def write_results_to_file(task_id: str, data: dict[str, Any]) -> str:
    results_dir = settings.paths.results_dir
    results_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{task_id}.json"
    file_path = results_dir / filename

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"Results written to {file_path}")
    return str(file_path)
