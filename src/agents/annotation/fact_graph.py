"""
章节 Agent 常驻事实图状态

说明: run 级事实图在首个章节 Agent 启动时从库加载一次，之后所有章节 Agent 共享，
每个图域写工具（write_entities / write_relations / resolve_fact_case）即时更新本图，
章节完成时由持久化层从本图的操作日志派生新图版本落库。中途恢复任务时重新加载。
运行时所有图查询（search_graph、关系/实体校验）只访问本内存图，数据库仅参与持久化。

2026-09-04 单一写面收敛：图域（实体+关系）的运行时真相源是本 FactGraph，
不再是 BoundChunkAnnotation 的 entities/relations 副本。本图在终态
（active_relations / entity_* 映射）之外维护一份按子块累积的有序操作日志
（sub_chunk_ops），承载持久化派生逐条 graph_facts 所需的 reason/case_id/
change_kind/ordinal 与 before/after 审计信息——终态装不下这些，故必须显式记录。
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
    history_relation_attributes: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    entity_types: dict[str, EntityType] = field(default_factory=dict, init=False)
    entity_names: dict[str, str] = field(default_factory=dict, init=False)
    entity_tags: dict[str, list[str]] = field(default_factory=dict, init=False)
    entity_attributes: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    entity_state: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    active_relations: set[tuple[str, str, str]] = field(default_factory=set, init=False)
    relation_attributes: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict, init=False)
    chapter_registered_entities: dict[str, EntityType] = field(default_factory=dict, init=False)
    chapter_added_relations: set[tuple[str, str, str]] = field(default_factory=set, init=False)
    # 2026-09-04 单一写面：图域操作日志，按子块累积（begin_chapter 清空、drain_ops 取出），
    # 持久化层从这三份日志派生实体行、关系 assert 事实与案例关系变更事实；
    # BoundChunkAnnotation 不再持有 entities/relations 副本，resolved_cases 不再承载 fact 动作。
    # entity_ops 追加语义，relation_assert_ops 完整替换语义（每次 write_relations 重填），
    # relation_change_ops 记录 resolve_fact_case 的关系生命周期变化（含案例生命周期元数据，
    # 供完成事务锁行/校验/写映射）。三者纳入 snapshot/restore，重放顺序=先 assert 后 change。
    entity_ops: list[dict[str, Any]] = field(default_factory=list, init=False)
    relation_assert_ops: list[dict[str, Any]] = field(default_factory=list, init=False)
    relation_change_ops: list[dict[str, Any]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        """2026-08-09 用于以历史快照初始化实时事实图状态"""
        self.entity_types = dict(self.history_entity_types)
        self.entity_names = dict(self.history_entity_names)
        self.entity_tags = {key: list(tags) for key, tags in self.history_entity_tags.items()}
        self.entity_attributes = {key: dict(attributes) for key, attributes in self.history_entity_attributes.items()}
        self.entity_state = {key: dict(state) for key, state in self.history_entity_state.items()}
        # 2026-08-12 历史关系按稳定键归一化加载，避免双向边端点顺序不一致导致匹配失败
        self.active_relations = {
            _stable_relation_key(from_name, to_name, relation_type)
            for (from_name, to_name, relation_type) in self.history_relations
        }
        self.relation_attributes = {
            key: dict(attributes) for key, attributes in self.history_relation_attributes.items()
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
        """2026-08-11 创建；2026-08-23 改为追加与更新语义（新名注册、同名更新，历史类型冲突仍拒绝）"""
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

    def apply_relation(self, item: RelationInput) -> bool:
        """2026-08-12 用于登记本章确认存在的边（新边 assert，已存在 no-op 不累计支持度）

        返回 True 表示新边（assert），False 表示已存在（skipped_existing）。
        强化/削弱/解除一律走 resolve_fact_case，不通过本条边提交。
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

        端点名取 write_relations 已解析（resolve_name 后）的规范名，与 active_relations
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

    def apply_relation_change(
        self,
        *,
        from_entity: str,
        to_entity: str,
        relation_type: str,
        change_kind: str,
        reason: str,
        case_id: str,
        case_type: str,
        target_key: str,
        target_ref: dict[str, Any],
        chapter_id: int,
    ) -> None:
        """2026-09-04 案例驱动的关系生命周期变化：即时更新终态 + 记录变更操作

        端点键按传入名原样构造、不过 resolve_name：search_graph 回显的 from/to 已是
        入库规范名，与存储键一致；若在此再解析，同一人物分量内的两端会塌成代表节点
        自环，要解除的边键自指导致永远删不掉（第 4 章空转的根因之一）。
        break/retract 要求边当前活动，否则报错——静默 accepted 而终态不变正是上一轮
        Agent 反复"撤销→复查→没变"空转的直接原因。

        case_type/target_key/target_ref 随操作携带：完成事务据此锁定案例行、复核
        稳定目标未变（防竞态），并按 target_ref["chunk_id"] 校验读取授权章节。
        """
        key = self._relation_key(from_entity, to_entity, relation_type)
        if change_kind in {"assert", "reinforce", "refine", "supersede"}:
            self.active_relations.add(key)
            self._bump_support_count(key)
        elif change_kind in {"break", "retract"}:
            if key not in self.active_relations:
                raise ValueError(
                    f"关系变更目标不存在或已解除: {from_entity}—{to_entity}（{relation_type}）；"
                    "请用 search_graph 确认边的规范端点名后再解除"
                )
            self.active_relations.discard(key)
        elif change_kind != "weaken":
            raise ValueError(f"不支持的关系变化类型: {change_kind}")
        self.relation_change_ops.append(
            {
                "from_entity": str(from_entity),
                "to_entity": str(to_entity),
                "relation_type": str(relation_type),
                "change_kind": str(change_kind),
                "reason": reason,
                "case_id": case_id,
                "case_type": str(case_type),
                "target_key": target_key,
                "target_ref": dict(target_ref),
                "chapter_id": chapter_id,
            }
        )

    def drain_ops(self) -> dict[str, list[dict[str, Any]]]:
        """2026-09-04 在子块结束时取出并清空累积的图域操作日志，供合并进完成事务输入"""
        drained = {
            "entity_ops": self.entity_ops,
            "relation_assert_ops": self.relation_assert_ops,
            "relation_change_ops": self.relation_change_ops,
        }
        self.entity_ops = []
        self.relation_assert_ops = []
        self.relation_change_ops = []
        return drained

    def reset_chapter_relations(self) -> None:
        """2026-08-09 用于在完整替换语义下撤销当章 assert 的关系

        2026-08-13 P2-9：同步回退本章新增边累加的 support_count——同一章节内
        write_relations 完整替换会先 reset 再重新 apply，若不回退，重新提交
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

    def begin_chapter(self) -> None:
        """2026-08-11 用于在章节边界把本章增量并入历史并清空章内追踪状态

        2026-08-13 P1-1 防御：把本章实时状态并入 history_* 快照，使章节失败
        回滚（reset_chapter_changes）恢复到上一章结束状态而非 run 启动状态，
        避免重试时丢失已成功章节的内存增量（正常路径 resume 从库重载兜底）。
        """
        self.history_entity_types = dict(self.entity_types)
        self.history_entity_names = dict(self.entity_names)
        self.history_entity_tags = {key: list(tags) for key, tags in self.entity_tags.items()}
        self.history_entity_attributes = {key: dict(attributes) for key, attributes in self.entity_attributes.items()}
        self.history_entity_state = {key: dict(state) for key, state in self.entity_state.items()}
        self.history_relations = set(self.active_relations)
        self.history_relation_attributes = {
            key: dict(attributes) for key, attributes in self.relation_attributes.items()
        }
        self.chapter_added_relations.clear()
        self.chapter_registered_entities.clear()
        self.entity_ops = []
        self.relation_assert_ops = []
        self.relation_change_ops = []

    def reset_chapter_changes(self) -> None:
        """2026-08-09 用于在章节重试回滚时恢复历史快照

        2026-09-04：图域操作日志随本章增量一并清空（失败章不提交，日志无消费方）。
        """
        self.entity_types = dict(self.history_entity_types)
        self.entity_names = dict(self.history_entity_names)
        self.entity_tags = dict(self.history_entity_tags)
        self.entity_attributes = dict(self.history_entity_attributes)
        self.entity_state = dict(self.history_entity_state)
        self.active_relations = set(self.history_relations)
        self.relation_attributes = dict(self.history_relation_attributes)
        self.chapter_registered_entities = {}
        self.chapter_added_relations = set()
        self.entity_ops = []
        self.relation_assert_ops = []
        self.relation_change_ops = []

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
            "entity_ops": [dict(op) for op in self.entity_ops],
            "relation_assert_ops": [dict(op) for op in self.relation_assert_ops],
            "relation_change_ops": [dict(op) for op in self.relation_change_ops],
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

    def resolve_name(self, name: str) -> str:
        """2026-08-11 用于沿"同一人物"连通分量把别名解析为规范名（标记优先）"""
        key = _norm(name)
        representative_key = self._representative_key(key)
        if representative_key is None:
            return name
        return self.entity_names.get(representative_key, name)

    def _representative_key(self, key: str) -> str | None:
        """2026-08-11 用于沿同一人物边找分量代表：is_representative 标记优先，无标记兜底"""
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
            return None
        root = find(key)
        members = [node for node in parent if find(node) == root]
        registered_order = {node: index for index, node in enumerate(self.entity_names)}
        members.sort(key=lambda node: registered_order.get(node, len(registered_order)))
        flagged = [node for node in members if bool((self.entity_attributes.get(node) or {}).get("is_representative"))]
        if flagged:
            return flagged[0]
        history_members = [node for node in members if node in self.history_entity_types]
        if history_members:
            return history_members[0]
        return members[0]


__all__ = ["FactGraph"]
