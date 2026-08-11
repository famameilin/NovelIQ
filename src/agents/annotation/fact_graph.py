"""
章节 Agent 常驻事实图状态

说明: run 级事实图在首个章节 Agent 启动时从库加载一次，之后所有章节 Agent 共享，
每个 write 工具调用即时更新，章节完成时作为新图版本落库。中途恢复任务时重新加载。
运行时所有图查询（search_graph、关系/实体校验）只访问本内存图，数据库仅参与持久化。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .schema import RELATION_DEFINITIONS, EntityType, RelationInput


def _norm(value: str) -> str:
    """2026-08-09 用于生成实体名称精确匹配键"""
    return unicodedata.normalize("NFC", value).strip().casefold()


def _stable_relation_key(
    from_name: str,
    to_name: str,
    relation_type: str,
) -> tuple[str, str, str]:
    """2026-08-11 用于生成双向归一化的关系稳定键（历史加载与运行时共用）"""
    key_a = _norm(from_name)
    key_b = _norm(to_name)
    definition = RELATION_DEFINITIONS.get(relation_type)
    if definition is not None and definition["directionality"] == "bidirectional":
        if key_a > key_b:
            key_a, key_b = key_b, key_a
    return key_a, key_b, relation_type


@dataclass(slots=True)
class FactGraph:
    """2026-08-09 用于保存实体与关系的实时事实图状态（历史+当章变更）"""

    history_entity_types: dict[str, EntityType] = field(default_factory=dict)
    history_entity_names: dict[str, str] = field(default_factory=dict)
    history_entity_tags: dict[str, list[str]] = field(default_factory=dict)
    history_entity_attributes: dict[str, dict[str, Any]] = field(default_factory=dict)
    history_entity_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    history_relations: set[tuple[str, str, str]] = field(default_factory=set)
    history_relation_attributes: dict[tuple[str, str, str], dict[str, Any]] = field(
        default_factory=dict
    )
    entity_types: dict[str, EntityType] = field(default_factory=dict, init=False)
    entity_names: dict[str, str] = field(default_factory=dict, init=False)
    entity_tags: dict[str, list[str]] = field(default_factory=dict, init=False)
    entity_attributes: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    entity_state: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    active_relations: set[tuple[str, str, str]] = field(default_factory=set, init=False)
    relation_attributes: dict[tuple[str, str, str], dict[str, Any]] = field(
        default_factory=dict, init=False
    )
    chapter_registered_entities: dict[str, EntityType] = field(default_factory=dict, init=False)
    chapter_added_relations: set[tuple[str, str, str]] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        """2026-08-09 用于以历史快照初始化实时事实图状态"""
        self.entity_types = dict(self.history_entity_types)
        self.entity_names = dict(self.history_entity_names)
        self.entity_tags = {
            key: list(tags) for key, tags in self.history_entity_tags.items()
        }
        self.entity_attributes = {
            key: dict(attributes)
            for key, attributes in self.history_entity_attributes.items()
        }
        self.entity_state = {key: dict(state) for key, state in self.history_entity_state.items()}
        self.active_relations = set(self.history_relations)
        self.relation_attributes = {
            key: dict(attributes)
            for key, attributes in self.history_relation_attributes.items()
        }

    @staticmethod
    def _relation_key(
        from_name: str,
        to_name: str,
        relation_type: str,
    ) -> tuple[str, str, str]:
        """2026-08-09 用于生成双向归一化的关系稳定键"""
        return _stable_relation_key(from_name, to_name, relation_type)

    def register_entities(self, entities: list) -> None:
        """2026-08-09 用于把当前 chunk 实体目录应用到实时事实图（完整替换）"""
        self._reset_chapter_entities()
        for entity in entities:
            key = _norm(entity.name)
            if key in self.history_entity_types:
                if self.history_entity_types[key] != entity.entity_type:
                    raise ValueError(
                        f"已登记实体不允许变更大类: {entity.name} "
                        f"registered={self.history_entity_types[key]} "
                        f"actual={entity.entity_type}（同一词条的不同身份请使用区分性名称，"
                        '如"圣城"是 location、"圣城朝堂"是 organization）'
                    )
            self.entity_types[key] = entity.entity_type
            self.entity_names[key] = entity.name
            tags = list(getattr(entity, "tags", None) or [])
            if tags:
                self.entity_tags[key] = list(dict.fromkeys(tags))
            description = getattr(entity, "description", None)
            if description is not None:
                self.entity_attributes[key] = {
                    **(self.entity_attributes.get(key) or {}),
                    "description": description,
                }
            self.chapter_registered_entities[key] = entity.entity_type

    def _reset_chapter_entities(self) -> None:
        """2026-08-09 用于在完整替换语义下撤销当章登记的实体"""
        for key in list(self.chapter_registered_entities):
            if key not in self.history_entity_types:
                self.entity_types.pop(key, None)
                self.entity_names.pop(key, None)
                self.entity_tags.pop(key, None)
                self.entity_attributes.pop(key, None)
                self.entity_state.pop(key, None)
        self.chapter_registered_entities.clear()

    def apply_relation(self, item: RelationInput) -> None:
        """2026-08-09 用于按闭合变化类型校验并更新实时关系集合"""
        from_name = str(item.from_entity)
        to_name = str(item.to_entity)
        relation_type = str(item.relation_type)
        key = self._relation_key(from_name, to_name, relation_type)
        change_kind = str(item.change_kind)
        if change_kind == "assert":
            self.active_relations.add(key)
            self.chapter_added_relations.add(key)
            self._bump_support_count(key)
            return
        if key not in self.active_relations:
            hints = self._similar_active_relations(from_name, to_name, relation_type)
            hint_text = ""
            if hints:
                hint_text = "；图中现有相近关系: " + "、".join(hints[:3])
            raise ValueError(
                f"关系变化未匹配到已存在活动关系: {from_name} "
                f"{relation_type} {to_name}（{change_kind} 要求边已存在，"
                f"请改为 assert，或核对端点是否使用了图上的登记名称{hint_text}）"
            )
        if change_kind in {"break", "retract"}:
            self.active_relations.discard(key)
            self.relation_attributes.pop(key, None)
            return
        if change_kind == "weaken":
            self._bump_strength(key)
            return
        if change_kind in {"reinforce", "refine", "supersede"}:
            self._bump_support_count(key)
            return

    def _bump_support_count(self, key: tuple[str, str, str]) -> None:
        """2026-08-11 用于按落库语义累加活动关系支持度"""
        attributes = dict(self.relation_attributes.get(key) or {})
        attributes["support_count"] = int(attributes.get("support_count", 0)) + 1
        self.relation_attributes[key] = attributes

    def _bump_strength(self, key: tuple[str, str, str]) -> None:
        """2026-08-11 用于按落库语义削弱活动关系强度"""
        attributes = dict(self.relation_attributes.get(key) or {})
        attributes["strength"] = int(attributes.get("strength", 0)) - 1
        self.relation_attributes[key] = attributes

    def _similar_active_relations(
        self,
        from_name: str,
        to_name: str,
        relation_type: str,
    ) -> list[str]:
        """2026-08-09 用于在 reinforce 失败时列出与目标端点相关的现存关系提示改名"""
        from_key = _norm(from_name)
        to_key = _norm(to_name)
        matches: list[str] = []
        for (a, b, rel_type) in sorted(self.active_relations):
            shares_endpoint = (
                a == from_key or a == to_key or b == from_key or b == to_key
            )
            if shares_endpoint:
                matches.append(f"{a} {rel_type} {b}")
        return matches

    def reset_chapter_relations(self) -> None:
        """2026-08-09 用于在完整替换语义下撤销当章 assert 的关系"""
        self.active_relations -= self.chapter_added_relations
        self.chapter_added_relations.clear()

    def begin_chapter(self) -> None:
        """2026-08-11 用于在章节边界把本章增量并入历史并清空章内追踪状态"""
        self.chapter_added_relations.clear()
        self.chapter_registered_entities.clear()

    def reset_chapter_changes(self) -> None:
        """2026-08-09 用于在章节重试回滚时恢复历史快照"""
        self.entity_types = dict(self.history_entity_types)
        self.entity_names = dict(self.history_entity_names)
        self.entity_tags = dict(self.history_entity_tags)
        self.entity_attributes = dict(self.history_entity_attributes)
        self.entity_state = dict(self.history_entity_state)
        self.active_relations = set(self.history_relations)
        self.relation_attributes = dict(self.history_relation_attributes)
        self.chapter_registered_entities = {}
        self.chapter_added_relations = set()

    def snapshot(self) -> dict:
        """2026-08-09 用于保存章节尝试前的完整事实图快照"""
        return {
            "entity_types": dict(self.entity_types),
            "entity_names": dict(self.entity_names),
            "entity_tags": dict(self.entity_tags),
            "entity_attributes": dict(self.entity_attributes),
            "entity_state": dict(self.entity_state),
            "active_relations": set(self.active_relations),
            "relation_attributes": dict(self.relation_attributes),
            "chapter_registered_entities": dict(self.chapter_registered_entities),
            "chapter_added_relations": set(self.chapter_added_relations),
        }

    def restore(self, snap: dict) -> None:
        """2026-08-09 用于在章节尝试失败时恢复事实图快照"""
        for field_name, value in snap.items():
            setattr(self, field_name, value)

    def entity_type(self, name: str) -> EntityType | None:
        """2026-08-09 用于查询实时事实图实体大类"""
        return self.entity_types.get(_norm(name))

    def relation_exists(self, from_name: str, to_name: str, relation_type: str) -> bool:
        """2026-08-09 用于判断活动关系是否已存在"""
        return self._relation_key(from_name, to_name, relation_type) in self.active_relations


__all__ = ["FactGraph"]
