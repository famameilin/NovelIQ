from __future__ import annotations

import networkx as nx
from sqlalchemy import select

from src.storage.models import GraphEntity
from src.storage.repositories import GraphRepository


def build_networkx_from_graph_tables(
    run_id: str,
    directed: bool = False,
    active_only: bool = True,
    session=None,
) -> nx.Graph:
    """
    从 graph_* 权威表临时构建 NetworkX 图。

    注意：该图仅用于计算，不做持久化。
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
        )

    for edge in edges:
        graph.add_edge(
            edge["from_entity_id"],
            edge["to_entity_id"],
            relation_type=edge["type"],
            is_active=edge["is_active"],
            support_count=edge["support_count"],
            change_count=edge["change_count"],
            first_seen_chunk=edge["first_seen_chunk"],
            last_seen_chunk=edge["last_seen_chunk"],
            tension_index=edge["tension_index"],
        )

    return graph
