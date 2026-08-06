from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import networkx as nx
from sqlalchemy import select

from src.storage.models import (
    GraphEntity,
    GraphFact,
    GraphFactSource,
)
from src.storage.repositories.graph.repository import GraphRepository


@dataclass(frozen=True)
class GraphSearchMatch:
    """2026-08-06 用于承载图遍历命中的目标节点与子图路径"""

    target_node_id: str
    source_kind: str
    evidence: dict[str, Any]
    matched_nodes: list[dict[str, Any]]
    matched_edges: list[dict[str, Any]]
    path: list[str]


def _normalize_graph_text(value: str) -> str:
    """2026-08-06 用于统一图查询文本的 Unicode 和大小写"""
    return unicodedata.normalize("NFC", value).strip().casefold()


def _graph_query_terms(query: str) -> list[str]:
    """2026-08-06 用于把图查询拆成可匹配中英文节点和边的词项"""
    normalized = _normalize_graph_text(query)
    parts = [
        term
        for term in re.split(r"[\s,，。；;：:、!?！？\"'（）()\[\]{}]+", normalized)
        if term
    ]
    return list(dict.fromkeys([normalized, *parts]))


def _matches_graph_query(query_terms: list[str], *values: str) -> bool:
    """2026-08-06 用于判断查询词是否命中图节点或边属性"""
    haystack = "\n".join(_normalize_graph_text(value) for value in values if value)
    return any(term in haystack for term in query_terms)


def _entity_name(value: Any) -> str | None:
    """2026-08-06 用于从图事实对象中提取实体名称"""
    if not isinstance(value, dict):
        return None
    name = str(value.get("name") or "").strip()
    return name or None


def _path_edge_payload(graph: nx.MultiDiGraph, left: str, right: str) -> dict[str, Any]:
    """2026-08-06 用于把路径中的正向或反向多重边及属性转换为稳定结果"""
    edge_data = graph.get_edge_data(left, right)
    from_node_id = left
    to_node_id = right
    if not edge_data:
        edge_data = graph.get_edge_data(right, left)
        from_node_id = right
        to_node_id = left
    first_edge = next(iter(edge_data.values())) if edge_data else {}
    return {
        "from_node_id": from_node_id,
        "to_node_id": to_node_id,
        "edge_kind": str(first_edge.get("edge_kind") or "related"),
        "relation_type": str(first_edge.get("relation_type") or "related"),
        "properties": dict(first_edge),
    }


def build_fact_graph_from_graph_tables(
    run_id: str,
    *,
    session,
    active_only: bool = True,
) -> nx.MultiDiGraph:
    """2026-08-06 用于从数据库图表构建可遍历的临时异构图"""
    if session is None:
        raise ValueError("session is required for build_fact_graph_from_graph_tables")

    graph = nx.MultiDiGraph()
    entities = list(
        session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id).order_by(GraphEntity.entity_id)
        )
        .scalars()
        .all()
    )
    entity_node_by_name: dict[str, str] = {}
    for entity in entities:
        node_id = f"entity:{entity.entity_id}"
        graph.add_node(
            node_id,
            kind="entity",
            label=entity.canonical_name,
            canonical_name=entity.canonical_name,
            entity_type=entity.entity_type,
            is_representative=entity.is_representative,
        )
        entity_node_by_name[_normalize_graph_text(entity.canonical_name)] = node_id

    fact_stmt = (
        select(GraphFact, GraphFactSource)
        .join(
            GraphFactSource,
            (GraphFactSource.graph_fact_id == GraphFact.graph_fact_id)
            & (GraphFactSource.run_id == run_id),
        )
        .where(GraphFact.run_id == run_id)
        .order_by(GraphFact.graph_fact_id)
    )
    if active_only:
        fact_stmt = fact_stmt.where(GraphFact.active.is_(True))
    fact_rows = list(session.execute(fact_stmt).all())
    for fact, source in fact_rows:
        fact_node_id = f"fact:{source.stable_fact_id}"
        graph.add_node(
            fact_node_id,
            kind="fact",
            label=f"{fact.subject_name} {fact.predicate}",
            fact_id=source.stable_fact_id,
            source_kind=source.source_kind,
            subject_name=fact.subject_name,
            predicate=fact.predicate,
            fact_type=fact.fact_type,
            content=dict(fact.content),
            evidence=dict(source.evidence),
            active=fact.active,
            graph_fact_id=fact.graph_fact_id,
        )

        subject_node_id = entity_node_by_name.get(_normalize_graph_text(fact.subject_name))
        if subject_node_id is not None:
            graph.add_edge(
                subject_node_id,
                fact_node_id,
                edge_kind="subject",
                relation_type="subject",
            )

        object_name = _entity_name(fact.object)
        if object_name is not None:
            object_node_id = entity_node_by_name.get(_normalize_graph_text(object_name))
            if object_node_id is not None:
                graph.add_edge(
                    fact_node_id,
                    object_node_id,
                    edge_kind="object",
                    relation_type=fact.predicate,
                )

        for participant in fact.participants:
            if not isinstance(participant, dict):
                continue
            participant_name = _entity_name(participant.get("entity"))
            if participant_name is None:
                continue
            participant_node_id = entity_node_by_name.get(_normalize_graph_text(participant_name))
            if participant_node_id is None:
                continue
            graph.add_edge(
                participant_node_id,
                fact_node_id,
                edge_kind="participant",
                relation_type=str(participant.get("role") or "participant"),
            )

    for relation in GraphRepository(session).fetch_current_relations(run_id, active_only=active_only):
        from_node_id = f"entity:{relation.from_entity_id}"
        to_node_id = f"entity:{relation.to_entity_id}"
        if from_node_id not in graph or to_node_id not in graph:
            continue
        graph.add_edge(
            from_node_id,
            to_node_id,
            edge_kind="relation",
            relation_type=relation.relation_type,
            relation_semantics=relation.relation_semantics,
            representative_entity_id=relation.representative_entity_id,
        )

    return graph


def search_fact_graph(
    run_id: str,
    query: str,
    *,
    session,
    limit: int = 50,
    max_hops: int = 2,
) -> list[GraphSearchMatch]:
    """2026-08-06 用于按节点边和最短路径查询当前 run 的事实图"""
    graph = build_fact_graph_from_graph_tables(run_id, session=session, active_only=True)
    query_terms = _graph_query_terms(query)
    seed_nodes: set[str] = set()
    for node_id, attributes in graph.nodes(data=True):
        values = [
            str(attributes.get("label") or ""),
            str(attributes.get("canonical_name") or ""),
            str(attributes.get("entity_type") or ""),
            str(attributes.get("subject_name") or ""),
            str(attributes.get("predicate") or ""),
            str(attributes.get("fact_type") or ""),
            json.dumps(attributes.get("content") or {}, ensure_ascii=False, sort_keys=True),
        ]
        if _matches_graph_query(query_terms, *values):
            seed_nodes.add(str(node_id))
    for from_node_id, to_node_id, attributes in graph.edges(data=True):
        if _matches_graph_query(
            query_terms,
            str(attributes.get("edge_kind") or ""),
            str(attributes.get("relation_type") or ""),
        ):
            seed_nodes.update((str(from_node_id), str(to_node_id)))
    if not seed_nodes:
        return []

    undirected_graph = graph.to_undirected(as_view=True)
    distance_by_node: dict[str, int] = {}
    path_by_fact: dict[str, list[str]] = {}
    for seed_node in sorted(seed_nodes):
        lengths = nx.single_source_shortest_path_length(
            undirected_graph,
            seed_node,
            cutoff=max_hops,
        )
        for node_id, distance in lengths.items():
            node_key = str(node_id)
            previous = distance_by_node.get(node_key)
            if previous is None or distance < previous:
                distance_by_node[node_key] = distance
            if graph.nodes[node_id].get("kind") != "fact":
                continue
            path = [str(item) for item in nx.shortest_path(undirected_graph, seed_node, node_id)]
            previous_path = path_by_fact.get(node_key)
            if previous_path is None or len(path) < len(previous_path):
                path_by_fact[node_key] = path

    fact_node_ids = [
        node_id
        for node_id in distance_by_node
        if graph.nodes[node_id].get("kind") == "fact"
    ]
    fact_node_ids.sort(
        key=lambda node_id: (
            distance_by_node[node_id],
            int(graph.nodes[node_id].get("graph_fact_id") or 0),
            node_id,
        )
    )

    matches: list[GraphSearchMatch] = []
    for fact_node_id in fact_node_ids[:limit]:
        attributes = graph.nodes[fact_node_id]
        path = path_by_fact.get(fact_node_id, [fact_node_id])
        matched_nodes = [
            {
                "node_id": node_id,
                "node_kind": str(graph.nodes[node_id].get("kind") or "fact"),
                "label": str(graph.nodes[node_id].get("label") or node_id),
                "properties": dict(graph.nodes[node_id]),
            }
            for node_id in path
        ]
        matched_edges = [
            _path_edge_payload(graph, path[index], path[index + 1])
            for index in range(len(path) - 1)
        ]
        matches.append(
            GraphSearchMatch(
                target_node_id=fact_node_id,
                source_kind=str(attributes["source_kind"]),
                evidence=dict(attributes["evidence"]),
                matched_nodes=matched_nodes,
                matched_edges=matched_edges,
                path=path,
            )
        )
    return matches


def build_networkx_from_graph_tables(
    run_id: str,
    directed: bool = False,
    active_only: bool = True,
    session=None,
) -> nx.Graph:
    """
    从 graph_* 权威表临时构建 NetworkX 图

    注意：该图仅用于计算，不做持久化
    """
    if session is None:
        raise ValueError("session is required for build_networkx_from_graph_tables")

    graph_repo = GraphRepository(session)
    edges = graph_repo.fetch_current_relations(run_id, active_only=active_only)
    entities = session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars().all()

    graph: nx.Graph = nx.DiGraph() if directed else nx.Graph()

    for entity in entities:
        graph.add_node(
            entity.entity_id,
            name=entity.canonical_name,
            entity_type=entity.entity_type,
            first_seen_chunk=entity.first_seen_chunk,
            last_seen_chunk=entity.last_seen_chunk,
            role=entity.primary_role_function,
            emotion_score=entity.last_emotion_score,
            status=entity.status,
            is_representative=entity.is_representative,
        )

    for edge in edges:
        graph.add_edge(
            edge.from_entity_id,
            edge.to_entity_id,
            relation_type=edge.relation_type,
            is_active=edge.is_active,
            support_count=edge.support_count,
            change_count=edge.change_count,
            first_seen_chunk=edge.first_seen_chunk,
            last_seen_chunk=edge.last_seen_chunk,
            tension_index=edge.tension_index,
            relation_semantics=edge.relation_semantics,
            representative_entity_id=edge.representative_entity_id,
        )

    return graph
