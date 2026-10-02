"""正式章节独立的实体与关系状态，操作日志随不可变章节结果提交"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any
from uuid import NAMESPACE_DNS, uuid5

from .schema import RELATION_DEFINITIONS, EntityType, RelationInput


def _norm(value: str) -> str:
    """2026-08-09 用于生成实体名称精确匹配键"""
    return unicodedata.normalize("NFC", value).strip().casefold()


def _entity_uuid(run_scope: str, key: str) -> str:
    """2026-09-19 用于按 run+归一化名确定性铸造实体 id（uuid5，重启重放同值）"""
    return str(uuid5(NAMESPACE_DNS, f"novel-annotation-entity:{run_scope}:{key}"))


def mention_uuid(run_id: str, chapter_id: int, name: str) -> str:
    """章内提及身份不跨章合并，实体归属必须由标注 Agent 提交"""
    return _entity_uuid(run_id, f"{chapter_id}:{_norm(name)}")


def _stable_relation_key(
    from_name: str,
    to_name: str,
    relation_type: str,
) -> tuple[str, str, str]:
    """2026-08-11 用于生成双向归一化的关系稳定键"""
    key_a = _norm(from_name)
    key_b = _norm(to_name)
    definition = RELATION_DEFINITIONS.get(relation_type)
    if definition is not None and definition["directionality"] == "bidirectional":
        if key_a > key_b:
            key_a, key_b = key_b, key_a
    return key_a, key_b, relation_type


@dataclass(slots=True)
class FactGraph:
    """本章局部图，稳定身份跨尝试一致，图状态不跨章节共享"""

    run_scope: str = ""
    chapter_id: int = 0
    entity_types: dict[str, EntityType] = field(default_factory=dict, init=False)
    entity_names: dict[str, str] = field(default_factory=dict, init=False)
    entity_tags: dict[str, list[str]] = field(default_factory=dict, init=False)
    entity_attributes: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    entity_state: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    active_relations: set[tuple[str, str, str]] = field(default_factory=set, init=False)
    relation_attributes: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict, init=False)
    chapter_registered_entities: dict[str, EntityType] = field(default_factory=dict, init=False)
    chapter_added_relations: set[tuple[str, str, str]] = field(default_factory=set, init=False)
    # 章内名称定位生成稳定提及 ID，跨章归属由标注 Agent 的身份结论确定
    entity_ids: dict[str, str] = field(default_factory=dict, init=False)
    entity_ops: list[dict[str, Any]] = field(default_factory=list, init=False)
    relation_assert_ops: list[dict[str, Any]] = field(default_factory=list, init=False)

    @staticmethod
    def _relation_key(
        from_name: str,
        to_name: str,
        relation_type: str,
    ) -> tuple[str, str, str]:
        """2026-08-09 用于生成双向归一化的关系稳定键"""
        return _stable_relation_key(from_name, to_name, relation_type)

    def register_entities(self, entities: list) -> list[tuple[str, str]]:
        """2026-08-11 创建；2026-08-23 改为追加与更新语义（新名注册、同名更新）

        返回本批每个实体的 (章内提及 ID, 显示名)，供工具回执把 ID 交给模型。
        """
        assigned: list[tuple[str, str]] = []
        for entity in entities:
            key = _norm(entity.name)
            self.entity_types[key] = entity.entity_type
            self.entity_names[key] = entity.name
            assigned.append((self._id_for(key), entity.name))
            tags = list(getattr(entity, "tags", None) or [])
            if tags:
                self.entity_tags[key] = list(dict.fromkeys(tags))
            description = getattr(entity, "description", None)
            if description is not None:
                self.entity_attributes[key] = {
                    **(self.entity_attributes.get(key) or {}),
                    "description": description,
                }
            patch = dict(getattr(entity, "attributes", None) or {})
            if patch:
                merged = dict(self.entity_attributes.get(key) or {})
                for field_name, value in patch.items():
                    if value is None:
                        merged.pop(field_name, None)
                    else:
                        merged[field_name] = value
                self.entity_attributes[key] = merged
            self.chapter_registered_entities[key] = entity.entity_type
        return assigned

    def _id_for(self, key: str) -> str:
        """2026-09-19 用于为归一化名读取或登记 run 级 uuid id（确定性铸造，重放同值）"""
        existing = self.entity_ids.get(key)
        if existing is not None:
            return existing
        entity_id = mention_uuid(self.run_scope, self.chapter_id, key)
        self.entity_ids[key] = entity_id
        return entity_id

    def entity_id(self, name: str) -> str | None:
        """2026-09-19 用于按实体名读取 run 级 uuid id（未登记返回 None）"""
        key = _norm(name)
        if key not in self.entity_names:
            return None
        return self._id_for(key)

    def resolve_entity_id(self, entity_id: str, *, label: str) -> str:
        """2026-09-19 用于把模型提交的实体 uuid 翻成登记名；未登记 id 直接报错自纠

        只做 id→登记名翻译，**不做别名归并**：别名解析仍留在各调用点原有的
        resolve_name 位置。id 指向的登记若已被章节回滚撤销，视为未登记——
        防止解析到一个不在图上的名字。
        """
        key = next((k for k, v in self.entity_ids.items() if v == entity_id), None)
        if key is None or key not in self.entity_names:
            raise ValueError(
                f"{label} 实体 id 未登记：id 取自本章 write_entity 回执"
            )
        return self.entity_names[key]

    def apply_relation(self, item: RelationInput) -> bool:
        """2026-08-12 用于登记本章确认存在的边（新边 assert，已存在 no-op 不累计支持度）

        返回 True 表示新边（assert），False 表示已存在（skipped_existing）。
        跨章关系订正由 continuity 工作处理，本章只确认局部关系
        """
        from_name = str(item.from_entity)
        to_name = str(item.to_entity)
        relation_type = str(item.relation_type)
        key = self._relation_key(from_name, to_name, relation_type)
        if key in self.active_relations:
            return False
        self.active_relations.add(key)
        self.chapter_added_relations.add(key)
        self._bump_support_count(key)
        return True

    def _bump_support_count(self, key: tuple[str, str, str]) -> None:
        """2026-08-11 用于按落库语义累加活动关系支持度"""
        attributes = dict(self.relation_attributes.get(key) or {})
        attributes["support_count"] = int(attributes.get("support_count", 0)) + 1
        self.relation_attributes[key] = attributes

    def record_entity_ops(self, entities: list, *, chapter_id: int) -> None:
        """2026-09-04 登记本批实体注册操作（追加语义），供持久化派生实体行与属性事实

        与 register_entities 的终态更新并行：终态供 search_graph 即时可见，
        操作日志供持久化按提交顺序重放（同名合并、属性 before/after 由持久化层
        对照数据库现值计算）。
        """
        for entity in entities:
            self.entity_ops.append(
                {
                    "name": str(entity.name),
                    "entity_type": str(entity.entity_type),
                    "tags": list(getattr(entity, "tags", None) or []),
                    "description": getattr(entity, "description", None),
                    "attributes": dict(getattr(entity, "attributes", None) or {}),
                    "chapter_id": chapter_id,
                }
            )

    def record_relation_asserts(self, relations: list, *, chapter_id: int) -> None:
        """2026-09-04 登记本批关系 assert 操作（完整替换语义：先清空再按本批重填）

        端点名取每次重放前已解析（resolve_name 后）的规范名，与 active_relations
        存储键一致，保证持久化重放与运行时终态同源。
        """
        self.relation_assert_ops = [
            {
                "from_entity": str(item.from_entity),
                "to_entity": str(item.to_entity),
                "relation_type": str(item.relation_type),
                "chapter_id": chapter_id,
            }
            for item in relations
        ]

    def drain_ops(self) -> dict[str, list[dict[str, Any]]]:
        """取出本章局部命令，交给正式提交事务"""
        drained = {
            "entity_ops": self.entity_ops,
            "relation_assert_ops": self.relation_assert_ops,
        }
        self.entity_ops = []
        self.relation_assert_ops = []
        return drained

    def reset_chapter_relations(self) -> None:
        """2026-08-09 用于在完整替换语义下撤销当章 assert 的关系

        2026-08-13 P2-9：同步回退本章新增边累加的 support_count——同一章节内
        关系集合每次写入都会先 reset 再重新 apply，若不回退，重新提交
        已 assert 边会重复 +1（每次替换 +1），落库后支持度虚高。
        """
        for key in self.chapter_added_relations:
            attributes = dict(self.relation_attributes.get(key) or {})
            support = int(attributes.get("support_count", 0)) - 1
            if support > 0:
                attributes["support_count"] = support
            else:
                attributes.pop("support_count", None)
            if attributes:
                self.relation_attributes[key] = attributes
            else:
                self.relation_attributes.pop(key, None)
        self.active_relations -= self.chapter_added_relations
        self.chapter_added_relations.clear()

    def reset_chapter_changes(self) -> None:
        """2026-10-02 用于在多代理路径整章失败时撤销本章全部图域变更

        语义 = reset_chapter_relations（含 support_count 回退）＋ 清空本章实体域全部
        状态（名称/类型/标签/属性/状态/ops）——容量位拉起下先完成的子代理也可能已
        写入实体，失败路径必须整图复原。图按章新建、整图即本章，清空即复原；
        实体 id 注册表（entity_ids）刻意不清：id 由 uuid5(run+名) 确定性铸造，
        回收与保留同值。
        """
        self.reset_chapter_relations()
        self.chapter_registered_entities.clear()
        self.entity_names.clear()
        self.entity_types.clear()
        self.entity_tags.clear()
        self.entity_attributes.clear()
        self.entity_state.clear()
        self.entity_ops.clear()
        self.relation_assert_ops.clear()

    def snapshot(self) -> dict:
        """2026-08-09 用于保存章节尝试前的完整事实图快照

        2026-09-19 实体 id 注册表刻意不进快照：id 由 uuid5(run+名) 确定性铸造，
        失败回滚不回收也不改变，回滚撤销的登记由 resolve_entity_id 的
        存活性校验兜底，不会把陈旧 id 解析成别的实体。
        """
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
            "entity_ops": [dict(op) for op in self.entity_ops],
            "relation_assert_ops": [dict(op) for op in self.relation_assert_ops],
        }

    def restore(self, snap: dict) -> None:
        """2026-08-09 用于在章节尝试失败时恢复事实图快照"""
        for field_name, value in snap.items():
            setattr(self, field_name, value)

    def entity_type(self, name: str) -> EntityType | None:
        """2026-08-09 用于查询实时事实图实体大类"""
        return self.entity_types.get(_norm(name))

    def resolve_name(self, name: str) -> str:
        """2026-08-11 用于沿"同一人物"连通分量把别名解析为规范名（标记优先）"""
        key = _norm(name)
        representative_key = self._representative_key(key)
        if representative_key is None:
            return name
        return self.entity_names.get(representative_key, name)

    def alias_group(self, name: str) -> list[str]:
        """2026-09-14 用于取该名字同一人物连通分量内的其余登记名（不含自身，供进度账本别名列）"""
        key = _norm(name)
        return [self.entity_names.get(node, node) for node in self._same_person_component(key) if node != key]

    def _same_person_component(self, key: str) -> list[str]:
        """2026-08-11 用于收集同一人物边连通分量中该名字所在分量的全部成员键（不在分量则空）"""
        parent: dict[str, str] = {}

        def find(node: str) -> str:
            if parent.get(node, node) != node:
                parent[node] = find(parent[node])
            return parent[node]

        for from_key, to_key, relation_type in self.active_relations:
            if relation_type != "同一人物":
                continue
            parent.setdefault(from_key, from_key)
            parent.setdefault(to_key, to_key)
            root_a, root_b = find(from_key), find(to_key)
            if root_a != root_b:
                parent[root_b] = root_a
        if key not in parent:
            return []
        root = find(key)
        return [node for node in parent if find(node) == root]

    def _representative_key(self, key: str) -> str | None:
        """2026-08-11 用于沿同一人物边找分量代表：is_representative 标记优先，无标记兜底"""
        members = self._same_person_component(key)
        if not members:
            return None
        registered_order = {node: index for index, node in enumerate(self.entity_names)}
        members.sort(key=lambda node: registered_order.get(node, len(registered_order)))
        flagged = [node for node in members if bool((self.entity_attributes.get(node) or {}).get("is_representative"))]
        if flagged:
            return flagged[0]
        return members[0]


__all__ = ["FactGraph"]
