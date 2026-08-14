"""
规范名选举纯函数

说明: 每章完成事务对 run 内全部实体全量重选：清空旧标记，仅对每个
"同一人物"连通分量中 entity_id 最小的节点标记 is_representative=true
（entity_id 递增即入库顺序，对齐旧 min(from_id, to_id) 语义）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def elect_representatives(
    entities: Sequence[Any],
    *,
    pairs: Sequence[tuple[int, int]],
) -> dict[int, bool]:
    """2026-08-11 用于按同一人物关系对选举代表并返回全量标记（未参与分量一律 false）"""
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        if parent.get(node, node) != node:
            parent[node] = find(parent[node])
        return parent[node]

    for from_id, to_id in pairs:
        parent.setdefault(from_id, from_id)
        parent.setdefault(to_id, to_id)
        root_a, root_b = find(from_id), find(to_id)
        if root_a != root_b:
            parent[root_b] = root_a

    flags: dict[int, bool] = {}
    for entity in entities:
        flags[int(entity.entity_id)] = False
    if not parent:
        return flags

    components: dict[int, list[int]] = {}
    for node in parent:
        components.setdefault(find(node), []).append(node)
    for members in components.values():
        representative = min(members)
        flags[representative] = True
    return flags


__all__ = ["elect_representatives"]
