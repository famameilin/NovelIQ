"""
同 run 人物别名消歧解析

说明: 依据"同一人物"关系（relation_semantics=same_character）与实体节点属性
is_representative 标记，把别名实体归一到代表实体。所有读侧消费者（图谱快照、
角色榜、时间轴、聚合、诊断、导出）统一复用本模块，避免各自重复实现合并语义。
代表标记由章节完成事务全量重选（见 storage/repositories/graph/election.py）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from src.storage.repositories.graph.repository import EntitySnapshotRow, RelationSnapshotRow


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
    relations: Sequence[RelationSnapshotRow],
    *,
    entities: Sequence[EntitySnapshotRow],
) -> AliasResolution:
    """
    2026-08-11 用于从 active 的同一人物关系构建别名归并映射

    代表 = 实体 attributes.is_representative=true 的节点；无标记（旧数据/防御）时
    取分量内最小 entity_id，与完成事务选举语义对齐。
    """
    entity_by_id = {int(entity.entity_id): entity for entity in entities}
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        if parent.get(node, node) != node:
            parent[node] = find(parent[node])
        return parent[node]

    for relation in relations:
        if not relation.is_active:
            continue
        if relation.relation_semantics != "same_character":
            continue
        from_id = int(relation.from_entity_id)
        to_id = int(relation.to_entity_id)
        parent.setdefault(from_id, from_id)
        parent.setdefault(to_id, to_id)
        root_a, root_b = find(from_id), find(to_id)
        if root_a != root_b:
            parent[root_b] = root_a

    representative_by_alias: dict[int, int] = {}
    components: dict[int, list[int]] = {}
    for node in parent:
        components.setdefault(find(node), []).append(node)
    for members in components.values():
        flagged: list[int] = []
        for member in members:
            entity = entity_by_id.get(member)
            if entity is not None and bool((entity.attributes or {}).get("is_representative")):
                flagged.append(member)
        representative = flagged[0] if flagged else min(members)
        for member in members:
            if member != representative:
                representative_by_alias[member] = representative

    name_to_representative: dict[str, str] = {}
    aliases_by_representative: dict[int, list[str]] = {}
    entity_names = {int(entity.entity_id): str(entity.name) for entity in entities}
    for alias_id, representative_id in representative_by_alias.items():
        alias_name = entity_names.get(alias_id)
        representative_name = entity_names.get(representative_id)
        if not alias_name or not representative_name:
            continue
        # 别名与代表同名时也必须建映射（恒等映射），保证每个进 representative_by_alias
        # 的别名 id 都有对应的 name 映射条目，避免边端点的 id 已归并而 name 未归并的不一致
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
