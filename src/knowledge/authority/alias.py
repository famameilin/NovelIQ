"""
同 run 人物别名消歧解析

说明: 依据"同一人物"关系（relation_semantics=same_character）与持久化时写入的
representative_entity_id，把别名实体归一到代表实体。所有读侧消费者（图谱快照、
角色榜、时间轴、聚合、诊断、导出）统一复用本模块，避免各自重复实现合并语义。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(slots=True)
class AliasResolution:
    """2026-08-09 用于提供别名实体到代表实体的稳定映射"""

    representative_by_alias: dict[int, int] = field(default_factory=dict)
    name_to_representative: dict[str, str] = field(default_factory=dict)
    aliases_by_representative: dict[int, list[str]] = field(default_factory=dict)

    def resolve_entity_id(self, entity_id: int | None) -> int | None:
        """2026-08-09 用于把别名实体 ID 重写为代表实体 ID"""
        if entity_id is None:
            return None
        return self.representative_by_alias.get(int(entity_id), int(entity_id))

    def resolve_name(self, name: str | None) -> str | None:
        """2026-08-09 用于把别名名称重写为代表名称"""
        if not name:
            return name
        return self.name_to_representative.get(name, name)


def build_alias_resolution(
    relations: Sequence[object],
    *,
    entity_names: dict[int, str],
) -> AliasResolution:
    """
    2026-08-09 用于从 active 的同一人物关系构建别名归并映射

    传递闭包处理：别名链 A→B、B→C 会收敛到同一代表（取最小 entity_id）。
    """
    parent: dict[int, int] = {}
    alias_to_rep: dict[int, int] = {}

    def find(node: int) -> int:
        if parent.get(node, node) != node:
            parent[node] = find(parent[node])
        return parent[node]

    for relation in relations:
        if not getattr(relation, "is_active", True):
            continue
        if getattr(relation, "relation_semantics", "ordinary") != "same_character":
            continue
        from_id = int(getattr(relation, "from_entity_id", 0) or 0)
        to_id = int(getattr(relation, "to_entity_id", 0) or 0)
        attributes = dict(getattr(relation, "attributes", {}) or {})
        representative_raw = attributes.get("representative_entity_id")
        representative_id = int(representative_raw) if representative_raw is not None else min(from_id, to_id)
        parent.setdefault(from_id, from_id)
        parent.setdefault(to_id, to_id)
        parent.setdefault(representative_id, representative_id)
        parent[from_id] = find(representative_id)
        parent[to_id] = find(representative_id)
        alias_to_rep[from_id] = representative_id
        alias_to_rep[to_id] = representative_id

    representative_by_alias: dict[int, int] = {}
    for alias_id, representative_id in alias_to_rep.items():
        resolved = find(representative_id)
        if resolved == alias_id:
            continue
        existing = representative_by_alias.get(alias_id)
        if existing is None or resolved < existing:
            representative_by_alias[alias_id] = resolved

    name_to_representative: dict[str, str] = {}
    aliases_by_representative: dict[int, list[str]] = {}
    for alias_id, representative_id in representative_by_alias.items():
        alias_name = entity_names.get(alias_id)
        representative_name = entity_names.get(representative_id)
        if not alias_name or not representative_name:
            continue
        if alias_name == representative_name:
            continue
        name_to_representative[alias_name] = representative_name
        aliases_by_representative.setdefault(representative_id, [])
        if alias_name not in aliases_by_representative[representative_id]:
            aliases_by_representative[representative_id].append(alias_name)

    return AliasResolution(
        representative_by_alias=representative_by_alias,
        name_to_representative=name_to_representative,
        aliases_by_representative=aliases_by_representative,
    )


__all__ = ["AliasResolution", "build_alias_resolution"]
