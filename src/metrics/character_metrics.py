from __future__ import annotations

from collections import Counter
from typing import Dict, List, Tuple

import networkx as nx

from src.config import settings


PROPP_FUNCTIONS = {
    "主体",
    "客体",
    "发送者",
    "接收者",
    "帮助者",
    "反对者",
    "其他",
}

GREIMAS_FUNCTIONS = {
    "主体",
    "客体",
    "发送者",
    "接收者",
    "帮助者",
    "反对者",
}


def _build_character_graph(relations: List[Tuple[str, str]]) -> nx.Graph:
    G = nx.Graph()
    for from_char, to_char in relations:
        if from_char != to_char:
            G.add_edge(from_char, to_char)
    return G


def compute_character_degree_centrality(
    relations: List[Tuple[str, str]],
) -> Dict[str, float]:
    if not relations:
        return {}

    G = _build_character_graph(relations)
    centrality = nx.degree_centrality(G)
    return dict(centrality)


def compute_relation_network_density(
    relations: List[Tuple[str, str]],
) -> float:
    if not relations:
        return 0.0

    G = _build_character_graph(relations)
    n = G.number_of_nodes()
    if n < 2:
        return 0.0

    return nx.density(G)


def compute_protagonist_betweenness(
    relations: List[Tuple[str, str]],
    protagonist_name: str,
) -> float:
    if not relations or not protagonist_name:
        return 0.0

    G = _build_character_graph(relations)

    if protagonist_name not in G:
        return 0.0

    if G.number_of_nodes() < 3:
        return 0.0

    betweenness = nx.betweenness_centrality(G, normalized=True)
    return betweenness.get(protagonist_name, 0.0)


def compute_character_closeness_centrality(
    relations: List[Tuple[str, str]],
) -> Dict[str, float]:
    if not relations:
        return {}

    G = _build_character_graph(relations)
    centrality = nx.closeness_centrality(G)
    return dict(centrality)


def compute_character_eigenvector_centrality(
    relations: List[Tuple[str, str]],
    max_iter: int | None = None,
) -> Dict[str, float]:
    if max_iter is None:
        max_iter = settings.metrics.character_max_iter
    if not relations:
        return {}

    G = _build_character_graph(relations)

    if G.number_of_nodes() < 2:
        return {node: 0.0 for node in G.nodes()}

    try:
        centrality = nx.eigenvector_centrality(G, max_iter=max_iter)
        return dict(centrality)
    except nx.NetworkXException:
        return {node: 0.0 for node in G.nodes()}


def compute_clustering_coefficient(
    relations: List[Tuple[str, str]],
) -> Dict[str, float]:
    if not relations:
        return {}

    G = _build_character_graph(relations)
    clustering = nx.clustering(G)
    return dict(clustering)


def compute_average_clustering(
    relations: List[Tuple[str, str]],
) -> float:
    if not relations:
        return 0.0

    G = _build_character_graph(relations)

    if G.number_of_nodes() < 2:
        return 0.0

    return nx.average_clustering(G)


def compute_number_of_connected_components(
    relations: List[Tuple[str, str]],
) -> int:
    if not relations:
        return 0

    G = _build_character_graph(relations)
    return nx.number_connected_components(G)


def compute_largest_component_size(
    relations: List[Tuple[str, str]],
) -> int:
    if not relations:
        return 0

    G = _build_character_graph(relations)

    if G.number_of_nodes() == 0:
        return 0

    largest_cc = max(nx.connected_components(G), key=len)
    return len(largest_cc)


def compute_character_function_coverage(
    role_functions: List[str],
) -> Dict[str, float]:
    if not role_functions:
        return {func: 0.0 for func in PROPP_FUNCTIONS}

    counts = Counter(role_functions)
    total = len(role_functions)

    return {func: counts.get(func, 0) / total for func in PROPP_FUNCTIONS}


def compute_greimas_coverage(
    role_functions: List[str],
) -> float:
    if not role_functions:
        return 0.0

    unique_functions = set(role_functions)
    covered_count = len(unique_functions & GREIMAS_FUNCTIONS)

    return covered_count / len(GREIMAS_FUNCTIONS)


def compute_antagonist_strength_gap(
    characters: List[Tuple[str, str, int]],
) -> float:
    if not characters:
        return 0.0

    protagonist_scores = []
    antagonist_scores = []

    for name, role, score in characters:
        if role == "主体":
            protagonist_scores.append(abs(score))
        elif role == "反对者":
            antagonist_scores.append(abs(score))

    if not protagonist_scores or not antagonist_scores:
        return 0.0

    avg_protagonist = sum(protagonist_scores) / len(protagonist_scores)
    avg_antagonist = sum(antagonist_scores) / len(antagonist_scores)

    return abs(avg_protagonist - avg_antagonist)


def compute_relation_change_frequency(
    relations: List[Tuple[str, str, str, str]],
    total_chunks: int,
) -> Dict[str, float]:
    if not relations or total_chunks == 0:
        return {"total_changes": 0.0, "change_rate": 0.0}

    change_types = Counter(change for _, _, _, change in relations)

    return {
        "total_changes": float(len(relations)),
        "change_rate": len(relations) / total_chunks,
        "强化_rate": change_types.get("强化", 0) / len(relations) if relations else 0.0,
        "弱化_rate": change_types.get("弱化", 0) / len(relations) if relations else 0.0,
        "新建_rate": change_types.get("新建", 0) / len(relations) if relations else 0.0,
        "断裂_rate": change_types.get("断裂", 0) / len(relations) if relations else 0.0,
    }
