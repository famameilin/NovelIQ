"""Agent 关系图结构指标查询（《分析能力扩展路线图》赛道 A1/A2）

查询时计算，不落结果表：代表性格据取与 /graph 端点一致的快照视图
（别名归并、去 same_character 与自环），无向 + 边权=关系计数；
PageRank / HITS / Louvain 的输入快照、参数与结果解释边界随响应返回。
结构社区不直接等同于故事阵营。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import networkx as nx
import networkx.algorithms.community as nx_comm
from loguru import logger
from sqlalchemy.orm import Session

from src.storage.repositories import AnnotationRepository

_ALGORITHM_VERSION = "graph-metrics-v1"


def _undirected_edge_key(source: str, target: str) -> tuple[str, str]:
    """2026-08-31 用于把双向端点规范为同一个无向边键并保留并行关系计数"""
    return (source, target) if source <= target else (target, source)


def _require_snapshot(run_id: str, session: Session) -> dict[str, Any]:
    """读取最新图快照（无匹配章节版本时抛 LookupError）"""
    from src.api.services.results_queries.graph import _fetch_graph_snapshot

    annotation_repo = AnnotationRepository(session)
    return _fetch_graph_snapshot(run_id, annotation_repo)


def compute_graph_metrics(run_id: str, session: Session) -> dict[str, Any]:
    """
    PageRank / HITS / Louvain 结构指标（赛道 A1/A2）

    输入为代表性人物子图，边权=两角色关系计数（无向）；算法结果只表示
    结构信号，不解释为故事阵营或正式人物重要性结论。
    """
    try:
        snapshot = _require_snapshot(run_id, session)
    except LookupError as exc:
        return {
            "run_id": run_id,
            "unavailable_reason": f"graph_snapshot_unavailable: {exc}",
            "algorithm": {"version": _ALGORITHM_VERSION},
        }

    character_names = {
        node["name"] for node in snapshot["nodes"] if node["entity_type"] == "character"
    }
    edge_counts: Counter[tuple[str, str]] = Counter(
        _undirected_edge_key(edge["source_name"], edge["target_name"])
        for edge in snapshot["edges"]
        if edge["source_name"] in character_names and edge["target_name"] in character_names
    )
    graph = nx.Graph()
    graph.add_nodes_from(character_names)
    for (source, target), count in edge_counts.items():
        graph.add_edge(source, target, weight=count)
    if graph.number_of_nodes() < 2:
        return {
            "run_id": run_id,
            "unavailable_reason": "insufficient_nodes: 人物节点少于 2 个，无法计算图结构指标",
            "algorithm": {"version": _ALGORITHM_VERSION},
        }

    algorithm: dict[str, Any] = {
        "version": _ALGORITHM_VERSION,
        "graph": {
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "directed": False,
            "edge_weight": "relation_count",
            "alias_merge": "resolve_name",
            "same_character_filter": True,
        },
    }
    metrics: dict[str, Any] = {}

    pagerank_scores = nx.pagerank(graph, weight="weight")
    metrics["pagerank"] = {name: round(score, 6) for name, score in pagerank_scores.items()}

    try:
        hub_scores, authority_scores = nx.hits(graph)
        metrics["hits"] = {
            "authority": {name: round(score, 6) for name, score in authority_scores.items()},
            "hub": {name: round(score, 6) for name, score in hub_scores.items()},
        }
    except (nx.PowerIterationFailedConvergence, ValueError, ZeroDivisionError) as exc:
        logger.warning("HITS 未收敛，authority/hub 返回空: {}", exc)
        metrics["hits"] = {"authority": {}, "hub": {}, "unavailable_reason": f"hits_not_converged: {exc}"}

    try:
        communities = nx_comm.louvain_communities(graph, weight="weight", seed=42)
        modularity = nx_comm.modularity(graph, communities, weight="weight")
        metrics["communities"] = {
            "community_ids": {
                name: community_id for community_id, community in enumerate(communities) for name in community
            },
            "modularity": round(float(modularity), 6),
            # 结构社区不直接等同于故事阵营（§A2 解释边界）
            "interpretation": "structural_community_only",
        }
    except ValueError as exc:
        logger.warning("Louvain 社区发现失败: {}", exc)
        metrics["communities"] = {"community_ids": {}, "modularity": None, "unavailable_reason": str(exc)}

    result: dict[str, Any] = {
        "run_id": run_id,
        "unavailable_reason": None,
        "algorithm": algorithm,
        **metrics,
    }
    return result
