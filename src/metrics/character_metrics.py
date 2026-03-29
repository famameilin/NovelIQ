from __future__ import annotations

from collections import Counter

import networkx as nx

from src.config import settings
from src.config.constants import PROPP_FUNCTIONS

GREIMAS_FUNCTIONS = {
    "主体",
    "客体",
    "发送者",
    "接收者",
    "帮助者",
    "反对者",
}


def build_character_graph(relations: list[tuple[str, str]]) -> nx.Graph:
    G = nx.Graph()
    for from_char, to_char in relations:
        if from_char != to_char:
            G.add_edge(from_char, to_char)
    return G


def compute_character_degree_centrality(
    relations: list[tuple[str, str]],
    graph: nx.Graph | None = None,
) -> dict[str, float]:
    if not relations:
        return {}

    G = graph or build_character_graph(relations)
    centrality = nx.degree_centrality(G)
    return dict(centrality)


def compute_relation_network_density(
    relations: list[tuple[str, str]],
    graph: nx.Graph | None = None,
) -> float:
    if not relations:
        return 0.0

    G = graph or build_character_graph(relations)
    n = G.number_of_nodes()
    if n < 2:
        return 0.0

    return nx.density(G)


def compute_protagonist_betweenness(
    relations: list[tuple[str, str]],
    protagonist_name: str,
    graph: nx.Graph | None = None,
) -> float:
    if not relations or not protagonist_name:
        return 0.0

    G = graph or build_character_graph(relations)

    if protagonist_name not in G:
        return 0.0

    if G.number_of_nodes() < 3:
        return 0.0

    betweenness = nx.betweenness_centrality(G, normalized=True)
    return betweenness.get(protagonist_name, 0.0)


def compute_character_closeness_centrality(
    relations: list[tuple[str, str]],
    graph: nx.Graph | None = None,
) -> dict[str, float]:
    if not relations:
        return {}

    G = graph or build_character_graph(relations)
    centrality = nx.closeness_centrality(G)
    return dict(centrality)


def compute_character_eigenvector_centrality(
    relations: list[tuple[str, str]],
    max_iter: int | None = None,
    graph: nx.Graph | None = None,
) -> dict[str, float]:
    if max_iter is None:
        max_iter = settings.metrics.character_max_iter
    if not relations:
        return {}

    G = graph or build_character_graph(relations)

    if G.number_of_nodes() < 2:
        return dict.fromkeys(G.nodes(), 0.0)

    try:
        centrality = nx.eigenvector_centrality(G, max_iter=max_iter)
        return dict(centrality)
    except nx.NetworkXException:
        return dict.fromkeys(G.nodes(), 0.0)


def compute_clustering_coefficient(
    relations: list[tuple[str, str]],
    graph: nx.Graph | None = None,
) -> dict[str, float]:
    if not relations:
        return {}

    G = graph or build_character_graph(relations)
    clustering = nx.clustering(G)
    return dict(clustering)


def compute_average_clustering(
    relations: list[tuple[str, str]],
    graph: nx.Graph | None = None,
) -> float:
    if not relations:
        return 0.0

    G = graph or build_character_graph(relations)

    if G.number_of_nodes() < 2:
        return 0.0

    return nx.average_clustering(G)


def compute_number_of_connected_components(
    relations: list[tuple[str, str]],
    graph: nx.Graph | None = None,
) -> int:
    if not relations:
        return 0

    G = graph or build_character_graph(relations)
    return nx.number_connected_components(G)


def compute_largest_component_size(
    relations: list[tuple[str, str]],
    graph: nx.Graph | None = None,
) -> int:
    if not relations:
        return 0

    G = graph or build_character_graph(relations)

    if G.number_of_nodes() == 0:
        return 0

    largest_cc = max(nx.connected_components(G), key=len)
    return len(largest_cc)


def compute_character_function_coverage(
    role_functions: list[str],
) -> dict[str, float]:
    if not role_functions:
        return dict.fromkeys(PROPP_FUNCTIONS, 0.0)

    counts = Counter(role_functions)
    total = len(role_functions)

    return {func: counts.get(func, 0) / total for func in PROPP_FUNCTIONS}


def compute_greimas_coverage(
    role_functions: list[str],
) -> float:
    if not role_functions:
        return 0.0

    unique_functions = set(role_functions)
    covered_count = len(unique_functions & GREIMAS_FUNCTIONS)

    return covered_count / len(GREIMAS_FUNCTIONS)


def compute_antagonist_strength_gap(
    characters: list[tuple[str, str, int]],
) -> float:
    if not characters:
        return 0.0

    protagonist_scores = []
    antagonist_scores = []

    for _name, role, score in characters:
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
    relations: list[tuple[str, str, str, str]],
    total_chunks: int,
) -> dict[str, float]:
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
