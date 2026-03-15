"""
创建时间: 2025-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 修复 mypy 类型错误
- serialize_graph 函数中 data 字典类型注解
- deserialize_graph 函数中 data 字典类型注解

修改时间: 2026-03-14
修改者: TraeAI
任务: metrics-repository-refactor
修改内容: 重构为使用 Repository 模式
- 移除 sqlite_master 依赖
- build_character_graph 使用 Repository 接口
- save_graph_to_db 使用 StatsRepository
- load_graph_from_db 使用 StatsRepository
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import networkx as nx
from loguru import logger

if TYPE_CHECKING:
    from src.storage.repositories import EntityRepository, StatsRepository


def _init_character_nodes(entity_repo: "EntityRepository", run_id: str, G: nx.Graph) -> None:
    """
    2026-03-13 创建 - TraeAI
    任务: 知识增强层函数重构
    说明: 初始化角色节点

    2026-03-14 修改 - TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 EntityRepository 接口
    """
    character_names = entity_repo.fetch_distinct_characters(run_id)
    logger.debug(f"found {len(character_names)} distinct characters")

    for row in character_names:
        name = row[0]
        G.add_node(
            name,
            canonical_name=name,
            aliases=[],
            role_function=None,
            active_chunks=[],
            first_seen=None,
            last_seen=None,
            last_emotion=None,
            last_emotion_score=None,
        )


def _update_character_metadata(entity_repo: "EntityRepository", run_id: str, G: nx.Graph) -> None:
    """
    2026-03-13 创建 - TraeAI
    任务: 知识增强层函数重构
    说明: 更新角色元数据

    2026-03-14 修改 - TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 EntityRepository 接口
    """
    char_rows = entity_repo.fetch_character_metadata_sequence(run_id)
    logger.debug(f"processing {len(char_rows)} character records")
    for row in char_rows:
        name, chunk_id, role_function, emotion_score = row
        if name in G.nodes:
            node_data = G.nodes[name]
            if node_data["first_seen"] is None:
                node_data["first_seen"] = chunk_id
            node_data["last_seen"] = chunk_id
            if role_function:
                node_data["role_function"] = role_function
            if emotion_score is not None:
                node_data["last_emotion_score"] = emotion_score
            if chunk_id not in node_data["active_chunks"]:
                node_data["active_chunks"].append(chunk_id)


def _build_character_relations(entity_repo: "EntityRepository", run_id: str, G: nx.Graph) -> None:
    """
    2026-03-13 创建 - TraeAI
    任务: 知识增强层函数重构
    说明: 构建角色关系

    2026-03-14 修改 - TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 EntityRepository 接口
    """
    relation_counts: Dict[Tuple[str, str, str], Dict] = {}
    rel_rows = entity_repo.fetch_relation_sequence(run_id)
    logger.debug(f"processing {len(rel_rows)} relation records")
    for row in rel_rows:
        from_char, to_char, rel_type, change, chunk_id = row
        if from_char not in G.nodes:
            G.add_node(
                from_char,
                canonical_name=from_char,
                aliases=[],
                role_function=None,
                active_chunks=[],
                first_seen=chunk_id,
                last_seen=chunk_id,
            )
        if to_char not in G.nodes:
            G.add_node(
                to_char,
                canonical_name=to_char,
                aliases=[],
                role_function=None,
                active_chunks=[],
                first_seen=chunk_id,
                last_seen=chunk_id,
            )

        edge_key = (from_char, to_char, rel_type)
        if edge_key not in relation_counts:
            relation_counts[edge_key] = {
                "first_seen": chunk_id,
                "last_seen": chunk_id,
                "change_count": 0,
                "tension_index": 0.0,
            }
        relation_counts[edge_key]["last_seen"] = chunk_id
        if change and change != "无变化":
            relation_counts[edge_key]["change_count"] += 1

    for (from_char, to_char, rel_type), data in relation_counts.items():
        if G.has_edge(from_char, to_char):
            existing = G[from_char][to_char]
            if "types" in existing:
                existing["types"].append(rel_type)
            else:
                existing["types"] = [existing.get("type", rel_type), rel_type]
                existing["type"] = existing["types"][0]
        else:
            G.add_edge(
                from_char,
                to_char,
                type=rel_type,
                types=[rel_type],
                first_seen=data["first_seen"],
                last_seen=data["last_seen"],
                change_count=data["change_count"],
                tension_index=data["tension_index"],
            )


def _load_character_aliases(
    entity_repo: "EntityRepository",
    run_id: str,
    novel_id: str,
    G: nx.Graph,
) -> None:
    """
    2026-03-13 创建 - TraeAI
    任务: 知识增强层函数重构
    说明: 加载角色别名

    2026-03-14 修改 - TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 EntityRepository 接口
    """
    alias_rows = entity_repo.fetch_all_aliases_with_canonical(novel_id, run_id)

    for row in alias_rows:
        canonical, alias = row
        if canonical in G.nodes:
            if alias not in G.nodes[canonical]["aliases"]:
                G.nodes[canonical]["aliases"].append(alias)


def build_character_graph(
    entity_repo: "EntityRepository",
    run_id: str,
    novel_id: str = "default",
) -> nx.Graph:
    """
    构建角色关系图

    修改时间: 2026-03-13
    修改者: TraeAI
    修改内容: 重构为调用子函数，拆解原有逻辑

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 Repository 接口，添加 run_id 参数
    """
    logger.debug(f"building character graph for novel_id={novel_id}, run_id={run_id}")
    G = nx.Graph()

    _init_character_nodes(entity_repo, run_id, G)
    _update_character_metadata(entity_repo, run_id, G)
    _build_character_relations(entity_repo, run_id, G)
    _load_character_aliases(entity_repo, run_id, novel_id, G)

    logger.info(f"built character graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    return G


def serialize_graph(G: nx.Graph) -> str:
    data: Dict[str, Any] = {
        "nodes": {},
        "edges": [],
    }

    for node, attrs in G.nodes(data=True):
        data["nodes"][node] = {k: v for k, v in attrs.items()}

    for u, v, attrs in G.edges(data=True):
        edge_data: Dict[str, Any] = {"from": u, "to": v}
        edge_data.update(attrs)
        data["edges"].append(edge_data)

    return json.dumps(data, ensure_ascii=False)


def deserialize_graph(json_str: str) -> nx.Graph:
    data: Dict[str, Any] = json.loads(json_str)
    G = nx.Graph()

    for node, attrs in data.get("nodes", {}).items():
        G.add_node(node, **attrs)

    for edge_data in data.get("edges", []):
        u = edge_data.pop("from")
        v = edge_data.pop("to")
        G.add_edge(u, v, **edge_data)

    return G


def save_graph_to_db(
    stats_repo: "StatsRepository",
    run_id: str,
    G: nx.Graph,
    stat_name: str = "character_graph",
) -> None:
    """
    保存图到数据库

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 StatsRepository 接口，移除 sqlite_master 依赖
    """
    json_str = serialize_graph(G)
    stats_repo.save_graph(run_id, stat_name, json_str)
    logger.info(f"saved graph '{stat_name}' to database for run_id={run_id}")


def load_graph_from_db(
    stats_repo: "StatsRepository",
    run_id: str,
    stat_name: str = "character_graph",
) -> Optional[nx.Graph]:
    """
    从数据库加载图

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 StatsRepository 接口，移除 sqlite_master 依赖
    """
    json_str = stats_repo.load_graph(run_id, stat_name)
    if json_str is None:
        logger.debug(f"graph '{stat_name}' not found in database for run_id={run_id}")
        return None
    return deserialize_graph(json_str)


def get_active_nodes_in_range(
    G: nx.Graph,
    start_chunk: int,
    end_chunk: int,
) -> List[str]:
    active_nodes = []
    for node, attrs in G.nodes(data=True):
        active_chunks = attrs.get("active_chunks", [])
        for chunk_id in active_chunks:
            if start_chunk <= chunk_id <= end_chunk:
                active_nodes.append(node)
                break
    return active_nodes


def get_node_aliases(G: nx.Graph, node_name: str) -> List[str]:
    if node_name not in G.nodes:
        return []
    return G.nodes[node_name].get("aliases", [])


def get_all_known_aliases(G: nx.Graph) -> Dict[str, str]:
    alias_to_canonical = {}
    for node, attrs in G.nodes(data=True):
        canonical = attrs.get("canonical_name", node)
        alias_to_canonical[canonical] = canonical
        for alias in attrs.get("aliases", []):
            alias_to_canonical[alias] = canonical

    return alias_to_canonical
