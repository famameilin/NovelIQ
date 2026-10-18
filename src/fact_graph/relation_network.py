from __future__ import annotations

from collections import Counter
from collections.abc import Collection


def _normalize_relation_pair(from_name: str, to_name: str) -> tuple[str, str] | None:
    left = from_name.strip()
    right = to_name.strip()
    if not left or not right or left == right:
        return None
    return (left, right) if left <= right else (right, left)


def summarize_relation_network(
    relations: list[tuple[str, str]],
    *,
    node_names: Collection[str] | None = None,
) -> tuple[int, int, float | None]:
    degree_map: Counter[str] = Counter()
    if node_names:
        degree_map.update({name: 0 for name in node_names if name})

    unique_pairs: set[tuple[str, str]] = set()
    for from_name, to_name in relations:
        pair = _normalize_relation_pair(from_name, to_name)
        if pair is None or pair in unique_pairs:
            continue
        unique_pairs.add(pair)
        degree_map[pair[0]] += 1
        degree_map[pair[1]] += 1

    node_count = len(degree_map)
    edge_count = len(unique_pairs)
    # 角色节点 <3 时集中度无定义，契约要求 null（metrics_contracts network_density）
    if node_count < 3:
        return node_count, edge_count, None

    max_degree = max(degree_map.values(), default=0)
    centralization = sum(max_degree - degree for degree in degree_map.values()) / ((node_count - 1) * (node_count - 2))
    return node_count, edge_count, centralization
