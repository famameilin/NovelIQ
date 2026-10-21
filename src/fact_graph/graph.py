"""正式章节独立的实体与关系状态，操作日志随不可变章节结果提交"""

from __future__ import annotations

import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from src.fact_graph.contributions import FactContribution
from src.fact_graph.entity_operations import ENTITY_UPDATE_FIELDS, apply_entity_information, operation_fields
from src.fact_graph.identity_resolution import IdentityResolution, resolve_identities
from src.fact_graph.inputs import BoundRelationInput
from src.fact_graph.vocabulary import RELATION_DEFINITIONS, EntityType
from src.storage import new_id
from src.storage.records.evidence import EvidenceParagraph as StoredParagraph


def _norm(value: str) -> str:
    """生成实体名称精确匹配键"""
    return unicodedata.normalize("NFC", value).strip().casefold()


_ENTITY_KEY_SEP = "\x1f"


def _entity_key(name: str, entity_type: object) -> str:
    """生成实体身份复合键（规范名 + 实体大类）"""
    return f"{_norm(name)}{_ENTITY_KEY_SEP}{entity_type}"


def entity_key(name: str, entity_type: object) -> str:
    """在标注侧复用实体身份复合键（与 FactGraph 同一编码）"""
    return _entity_key(name, entity_type)


def _stable_relation_key(from_key: str, to_key: str, relation_type: str) -> tuple[str, str, str]:
    """生成双向归一化的关系稳定键（端点为实体身份复合键）"""
    key_a = from_key
    key_b = to_key
    definition = RELATION_DEFINITIONS.get(relation_type)
    if definition is not None and definition["directionality"] == "bidirectional":
        if key_a > key_b:
            key_a, key_b = (key_b, key_a)
    return (key_a, key_b, relation_type)


@dataclass(slots=True)
class FactGraph:
    """全书实体与关系；每次执行只撤销自身未保存贡献"""

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
    entity_ids: dict[str, str] = field(default_factory=dict, init=False)
    relation_ids: dict[tuple[str, str, str], str] = field(default_factory=dict, init=False)
    entity_ops: list[dict[str, Any]] = field(default_factory=list, init=False)
    relation_assert_ops: list[dict[str, Any]] = field(default_factory=list, init=False)
    contributions: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    saved: set[str] = field(default_factory=set, init=False)
    _author: ContextVar[str | None] = field(default_factory=lambda: ContextVar("fact_author", default=None), init=False)

    def begin(self, agent_id: str, chapter_sequence: int, role: str) -> None:
        if agent_id in self.saved:
            raise ValueError(f"已保存执行不可重新打开: {agent_id}")
        self.contributions.setdefault(
            agent_id,
            {
                "sequence": chapter_sequence,
                "role": role,
                "entity_ops": [],
                "relation_assert_ops": [],
                "plotline_ops": [],
            },
        )

    @contextmanager
    def author(self, agent_id: str):
        key = agent_id
        if key not in self.contributions or key in self.saved:
            raise ValueError(f"事实图执行已停止: {agent_id}")
        token = self._author.set(key)
        try:
            yield
        finally:
            self._author.reset(token)

    def rollback(self, agent_id: str) -> None:
        key = agent_id
        if key not in self.saved:
            self.contributions.pop(key, None)
            self._fold()

    def confirm(self, agent_id: str) -> None:
        self.saved.add(agent_id)

    def reference_entities(self, author: str, references: list[dict[str, Any]]) -> None:
        """Agent 持锁冻结实际引用，其他作者撤销后仍保留本次有效端点支持"""
        if author not in self.contributions or author in self.saved:
            raise ValueError(f"事实图引用执行已停止: {author}")
        self.contributions[author]["entity_references"] = deepcopy(references)
        self._fold()

    def prepare_save(self, frozen: FactContribution):
        """冻结实体身份、字段提交语义和关系方向，Storage 只保存明确记录"""
        import json

        from src.fact_graph.identity import canonical_relation_key
        from src.storage.records.facts import FactSave

        facts = frozen.snapshot()
        for op in facts["entity_ops"]:
            op["entity_id"] = self.entity_id_for_key(self.entity_key(op["name"], op["entity_type"]))
            op["submitted_fields"] = sorted(operation_fields(op))
        for op in facts["relation_assert_ops"]:
            left = self.entity_id_for_key(str(op["from_entity"]))
            right = self.entity_id_for_key(str(op["to_entity"]))
            left, right, kind = canonical_relation_key(left, right, str(op["relation_type"]))
            key = (str(left), str(right), kind)
            if key not in self.relation_ids:
                self.relation_ids[key] = new_id()
            op.update(from_entity_id=left, to_entity_id=right, relation_id=self.relation_ids[key])
        return FactSave(
            frozen.run_id,
            frozen.agent_id,
            frozen.chapter_id,
            tuple(
                StoredParagraph(row.chapter_id, row.paragraph_id, row.text, row.local_start_char, row.local_end_char)
                for row in frozen.paragraphs
            ),
            json.dumps(facts, ensure_ascii=False),
            frozen.observations_json,
        )

    def restore_storage(self, session: Any, records: list[Any]) -> None:
        self.contributions.clear()
        self.saved.clear()
        for record in records:
            facts = self._read_execution_facts(session, agent_id=str(record.agent_id), chapter_id=record.chapter_id)
            self.restore_work(
                str(record.agent_id),
                int(record.sequence),
                str(record.role),
                facts["entity_ops"],
                facts["relation_assert_ops"],
                facts["entity_references"],
                facts["plotline_ops"],
            )
        self._fold()

    def load_saved_work(self, session: Any, agent_id: str, annotation_id: str) -> dict[str, Any]:
        """锁外读取当前执行的真实保存贡献，不读取或撤销其他执行"""
        record = session.reads.fact_graph_graph_load_saved_work_1(annotation_id)
        if record is None or record.agent_id != agent_id:
            raise ValueError(f"事实图保存身份不一致: {agent_id}")
        execution = session.reads.fact_graph_graph_load_saved_work_2(agent_id)
        if execution is None or execution.run_id != self.run_scope or record.chapter_id is None:
            raise ValueError(f"事实图保存身份不一致: {agent_id}")
        chapter = session.reads.fact_graph_graph_load_saved_work_3(record.chapter_id, self.run_scope)
        detail = self._read_execution_facts(session, agent_id=agent_id, chapter_id=record.chapter_id)
        return {
            "author": agent_id,
            "sequence": int(chapter.sequence) if chapter is not None else 0,
            "role": str(execution.type),
            **detail,
        }

    def _read_execution_facts(
        self, session: Any, *, agent_id: str, chapter_id: int | None
    ) -> dict[str, list[dict[str, Any]]]:
        """按真实列形状把一次保存的事实读回内存贡献形态，供恢复与重折使用"""
        rows = list(session.reads.fact_graph_graph_read_execution_facts_3(agent_id))
        entity_names: dict[str, tuple[str, str]] = {
            str(item.entity_id): (str(item.canonical_name), str(item.entity_type))
            for item in session.reads.fact_graph_graph_read_execution_facts_4(self.run_scope)
        }
        for identifier, (name, kind) in entity_names.items():
            self.entity_ids[entity_key(name, kind)] = identifier
        relations = {str(item.relation_id): item for item in session.reads.fact_graph_graph_read_execution_facts_5()}
        from src.fact_graph.identity import canonical_relation_key

        for relation in relations.values():
            left, right, kind = canonical_relation_key(
                relation.from_entity_id, relation.to_entity_id, str(relation.relation_type)
            )
            self.relation_ids[(str(left), str(right), kind)] = str(relation.relation_id)
        tags_by_fact: dict[str, list[str]] = {}
        for tag in session.reads.fact_graph_graph_read_execution_facts_1(rows):
            tags_by_fact.setdefault(str(tag.graph_fact_id), []).append(str(tag.tag))
        evidence_by_fact: dict[str, list[dict[str, Any]]] = {}
        for evidence in session.reads.fact_graph_graph_read_execution_facts_2(rows):
            evidence_by_fact.setdefault(str(evidence.graph_fact_id), []).append(
                {
                    "chapter_id": chapter_id,
                    "paragraph_id": int(evidence.paragraph_id),
                    "char_start": int(evidence.start_char),
                    "char_end": int(evidence.end_char),
                }
            )
        entity_ops: list[dict[str, Any]] = []
        references: list[dict[str, Any]] = []
        relation_ops: list[dict[str, Any]] = []
        plotline_ops: list[dict[str, Any]] = []
        for row in rows:
            if row.business_call_id is not None:
                plotline_ops.append(
                    {
                        "source_operation_id": str(row.business_call_id),
                        "event_id": row.event_id,
                        "operation": {
                            "subject_id": str(row.plotline_subject_id),
                            "subject_title": str(row.plotline_subject_title),
                            "description": str(row.plotline_description),
                            "before": row.plotline_before,
                            "after": str(row.plotline_after),
                        },
                        "evidence": evidence_by_fact.get(str(row.graph_fact_id), []),
                    }
                )
                continue
            if row.relation_id is not None:
                relation = relations.get(str(row.relation_id))
                if relation is None:
                    continue
                op: dict[str, Any] = {
                    "from_entity": entity_names.get(str(relation.from_entity_id), ("", ""))[0],
                    "to_entity": entity_names.get(str(relation.to_entity_id), ("", ""))[0],
                    "relation_type": str(relation.relation_type),
                    "chapter_id": chapter_id,
                }
                if row.relation_change_kind and row.relation_change_kind != "assert":
                    op["change_kind"] = str(row.relation_change_kind)
                if row.identity_kind is not None:
                    op["identity_kind"] = str(row.identity_kind)
                relation_ops.append(op)
                continue
            if row.entity_id is None:
                continue
            name, entity_type = entity_names.get(str(row.entity_id), ("", ""))
            if row.tags_submitted is False:
                references.append({"entity_id": str(row.entity_id), "name": name, "entity_type": entity_type})
                continue
            op_fields: set[str] = set()
            if row.description_action is not None:
                op_fields.add("description")
            if row.representative_action is not None:
                op_fields.add("representative")
            if row.tags_submitted is True:
                op_fields.add("tags")
            entity_ops.append(
                {
                    "name": name,
                    "entity_type": entity_type,
                    "tags": tags_by_fact.get(str(row.graph_fact_id), []),
                    "fields": sorted(op_fields),
                    "description": row.description_value,
                    "representative": row.representative_value,
                    "attributes": {},
                    "chapter_id": chapter_id,
                }
            )
        return {
            "entity_ops": entity_ops,
            "relation_assert_ops": relation_ops,
            "entity_references": references,
            "plotline_ops": plotline_ops,
        }

    def recover_work(self, snapshot: dict[str, Any]) -> None:
        """同 run 锁内替换一个已保存作者，保护其他在飞贡献"""
        self.restore_work(
            snapshot["author"],
            snapshot["sequence"],
            snapshot["role"],
            snapshot["entity_ops"],
            snapshot["relation_assert_ops"],
            snapshot["entity_references"],
            snapshot.get("plotline_ops", []),
        )

    def restore_work(
        self,
        agent_id: str,
        sequence: int,
        role: str,
        entity_ops: list[dict[str, Any]],
        relation_ops: list[dict[str, Any]],
        entity_references: list[dict[str, Any]] | None = None,
        plotline_ops: list[dict[str, Any]] | None = None,
    ) -> None:
        self.contributions[agent_id] = {
            "sequence": sequence,
            "role": role,
            "entity_ops": deepcopy(entity_ops),
            "relation_assert_ops": deepcopy(relation_ops),
            "entity_references": deepcopy(entity_references or []),
            "plotline_ops": deepcopy(plotline_ops or []),
        }
        self.saved.add(agent_id)
        self._fold()

    def _fold(self) -> None:
        """章序、角色序、操作序折叠，撤销不恢复整本书快照"""
        for name in (
            "entity_types",
            "entity_names",
            "entity_tags",
            "entity_attributes",
            "entity_state",
            "relation_attributes",
            "chapter_registered_entities",
        ):
            getattr(self, name).clear()
        self.active_relations.clear()
        role_order = {"annotation": 0, "entity": 0, "event": 1, "metric": 2, "case": 3, "report": 3}
        ordered = sorted(
            self.contributions.items(), key=lambda item: (item[1]["sequence"], role_order[item[1]["role"]], item[0])
        )
        tag_sources: dict[tuple[int, str], dict[str, list[str]]] = {}
        for author, contribution in ordered:
            for reference in contribution.get("entity_references", []):
                key = _entity_key(reference["name"], reference["entity_type"])
                if self.entity_ids.get(key, reference["entity_id"]) != reference["entity_id"]:
                    raise ValueError(f"实体引用身份不一致: {reference}")
                self.entity_ids[key] = str(reference["entity_id"])
                self.entity_names.setdefault(key, reference["name"])
                self.entity_types.setdefault(key, EntityType(reference["entity_type"]))
                self.entity_tags.setdefault(key, [])
                self.entity_attributes.setdefault(key, {})
            for op in contribution["entity_ops"]:
                key = _entity_key(op["name"], op["entity_type"])
                self.entity_names[key] = op["name"]
                self.entity_types.setdefault(key, EntityType(op["entity_type"]))
                current: dict[str, Any] = {
                    "tags": self.entity_tags.get(key, []),
                    "attributes": self.entity_attributes.get(key, {}),
                }
                apply_entity_information(
                    current, op, tag_sources, chapter_id=op["chapter_id"], identity=key, author=author
                )
                self.entity_tags[key] = current["tags"]
                self.entity_attributes[key] = current["attributes"]
            for op in [*contribution["relation_assert_ops"], *contribution.get("relation_link_ops", [])]:
                relation_key = self._relation_key(op["from_entity"], op["to_entity"], op["relation_type"])
                if op.get("change_kind", "assert") in {"break", "retract"}:
                    self.active_relations.discard(relation_key)
                else:
                    self.active_relations.add(relation_key)
                    self._bump_support_count(relation_key)

    @staticmethod
    def _relation_key(from_name: str, to_name: str, relation_type: str) -> tuple[str, str, str]:
        """生成双向归一化的关系稳定键"""
        return _stable_relation_key(from_name, to_name, relation_type)

    def load_registry(self, session: Any) -> None:
        """诊断期从存储恢复实体登记与活动关系（身份金链不得再造成孪生）"""
        rows = list(session.reads.fact_graph_graph_load_registry_3(self.run_scope))
        id_to_key: dict[str, str] = {}
        for row in rows:
            key = entity_key(row.canonical_name, row.entity_type)
            id_to_key[str(row.entity_id)] = key
            self.entity_types[key] = row.entity_type
            self.entity_names[key] = row.canonical_name
            self.entity_tags[key] = []
            self.entity_attributes[key] = {}
            self.entity_ids[key] = str(row.entity_id)
        facts = list(session.reads.fact_graph_graph_load_registry_4(self.run_scope))
        tags_by_fact: dict[str, list[str]] = {}
        for tag in session.reads.fact_graph_graph_load_registry_1(facts):
            tags_by_fact.setdefault(str(tag.graph_fact_id), []).append(str(tag.tag))
        for fact in facts:
            if fact.relation_id is not None:
                relation = session.reads.fact_graph_graph_load_registry_2(fact)
                if relation is None:
                    continue
                from src.fact_graph.identity import canonical_relation_key

                left, right, kind = canonical_relation_key(
                    relation.from_entity_id, relation.to_entity_id, str(relation.relation_type)
                )
                self.relation_ids[(str(left), str(right), kind)] = str(relation.relation_id)
                from_key = id_to_key.get(str(relation.from_entity_id))
                to_key = id_to_key.get(str(relation.to_entity_id))
                if not from_key or not to_key:
                    continue
                self.active_relations.add(self._relation_key(from_key, to_key, str(relation.relation_type)))
                continue
            if fact.entity_id is None:
                continue
            entity_key_value = id_to_key.get(str(fact.entity_id))
            if entity_key_value is None:
                continue
            if fact.tags_submitted:
                self.entity_tags[entity_key_value] = list(tags_by_fact.get(str(fact.graph_fact_id), []))
            if fact.description_action == "set":
                self.entity_attributes[entity_key_value] = {
                    **self.entity_attributes[entity_key_value],
                    "description": fact.description_value,
                }
            elif fact.description_action == "clear":
                attributes = dict(self.entity_attributes[entity_key_value])
                attributes.pop("description", None)
                self.entity_attributes[entity_key_value] = attributes
            if fact.representative_action == "set":
                self.entity_attributes[entity_key_value] = {
                    **self.entity_attributes[entity_key_value],
                    "is_representative": True,
                }
            elif fact.representative_action == "clear":
                attributes = dict(self.entity_attributes[entity_key_value])
                attributes.pop("is_representative", None)
                self.entity_attributes[entity_key_value] = attributes

    @staticmethod
    def entity_key(name: str, entity_type: object) -> str:
        """在标注侧复用实体身份复合键（规范名+实体大类）"""
        return _entity_key(name, entity_type)

    def register_entities(self, entities: list, *, present: set[str] | None = None) -> list[tuple[str, str]]:
        """登记本批实体注册操作（追加与更新语义：新名注册、同名更新）

        实体身份=规范名+实体大类：同名不同类各自登记为独立实体。
        返回本批每个实体的 (章内提及 ID, 显示名)，供工具回执把 ID 交给模型。
        """
        assigned: list[tuple[str, str]] = []
        for entity in entities:
            key = _entity_key(entity.name, entity.entity_type)
            self.entity_types[key] = entity.entity_type
            self.entity_names[key] = entity.name
            assigned.append((self._id_for(key), entity.name))
            tags = list(getattr(entity, "tags", None) or [])
            if tags or (present is not None and "tags" in present):
                self.entity_tags[key] = list(dict.fromkeys(tags))
            description = getattr(entity, "description", None)
            if description is not None:
                self.entity_attributes[key] = {**(self.entity_attributes.get(key) or {}), "description": description}
            representative = getattr(entity, "representative", None)
            if representative is not None:
                attributes = dict(self.entity_attributes.get(key) or {})
                if representative:
                    attributes["is_representative"] = True
                else:
                    attributes.pop("is_representative", None)
                self.entity_attributes[key] = attributes
            self.chapter_registered_entities[key] = entity.entity_type
        return assigned

    def _id_for(self, key: str) -> str:
        """为实体身份键读取或登记 run 级 uuid id（确定性铸造，重放同值）"""
        existing = self.entity_ids.get(key)
        if existing is not None:
            return existing
        entity_id = new_id()
        self.entity_ids[key] = entity_id
        return entity_id

    def entity_id(self, name: str, entity_type: object) -> str | None:
        """按 (规范名, 实体大类) 读取 run 级 uuid id（未登记返回 None）"""
        key = _entity_key(name, entity_type)
        if key not in self.entity_names:
            return None
        return self._id_for(key)

    def entity_id_for_key(self, key: str) -> str | None:
        """按实体身份键读取 run 级 uuid id（未登记返回 None）"""
        if key not in self.entity_names:
            return None
        return self._id_for(key)

    def display_name(self, key: str) -> str:
        """把实体身份键翻成人类可读登记名（回执/观察/审计展示）"""
        return self.entity_names[key]

    def entity_type_by_key(self, key: str) -> EntityType | None:
        """按实体身份键读取登记大类"""
        return self.entity_types.get(key)

    def resolve_entity_id(self, entity_id: str, *, label: str) -> str:
        """把模型提交的实体 uuid 翻成实体身份键；未登记 id 直接报错自纠

        只做 id→身份键翻译，**不做别名归并**：别名解析仍留在各调用点原有的
        resolve_key 位置。id 指向的登记若已被章节回滚撤销，视为未登记——
        防止解析到一个不在图上的身份。
        """
        key = next((k for k, v in self.entity_ids.items() if v == entity_id), None)
        if key is None or key not in self.entity_names:
            raise ValueError(f"{label} 实体 id 未登记：id 取自本章 write_entity 回执")
        return key

    def apply_relation(self, item: BoundRelationInput) -> bool:
        """登记本章确认存在的边（新边 assert，已存在 no-op 不累计支持度）

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
        """按落库语义累加活动关系支持度"""
        attributes = dict(self.relation_attributes.get(key) or {})
        attributes["support_count"] = int(attributes.get("support_count", 0)) + 1
        self.relation_attributes[key] = attributes

    def record_entity_ops(
        self, entities: list, *, chapter_id: int, identity_only: bool = False, present: set[str] | None = None
    ) -> None:
        """登记本批实体注册操作（追加语义），供持久化派生实体行与属性事实

        与 register_entities 的终态更新并行：终态供 search_graph 即时可见，
        操作日志供持久化按提交顺序重放（同名合并、属性 before/after 由持久化层
        对照数据库现值计算）。
        """
        if identity_only:
            author = self._author.get()
            if author is not None:
                references = self.contributions[author].setdefault("entity_references", [])
                for entity in entities:
                    key = _entity_key(entity.name, entity.entity_type)
                    reference = {
                        "entity_id": self._id_for(key),
                        "name": entity.name,
                        "entity_type": str(entity.entity_type),
                    }
                    if reference not in references:
                        references.append(reference)
                self._fold()
            return
        for entity in entities:
            self.entity_ops.append(
                {
                    "name": str(entity.name),
                    "entity_type": str(entity.entity_type),
                    "tags": list(getattr(entity, "tags", None) or []),
                    "fields": sorted(ENTITY_UPDATE_FIELDS if present is None else ENTITY_UPDATE_FIELDS & present),
                    "description": getattr(entity, "description", None),
                    "representative": getattr(entity, "representative", None),
                    "chapter_id": chapter_id,
                }
            )
        author = self._author.get()
        if author is not None:
            self.contributions[author]["entity_ops"].extend(deepcopy(self.entity_ops[-len(entities) :]))
            self._fold()

    def record_relation_asserts(self, relations: list, *, chapter_id: int) -> None:
        """登记本批关系 assert 操作（完整替换语义：先清空再按本批重填）

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
        author = self._author.get()
        if author is not None:
            self.contributions[author]["relation_assert_ops"] = deepcopy(self.relation_assert_ops)
            self._fold()

    def drain_ops(self, agent_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """取出本章局部命令，交给正式提交事务"""
        if agent_id is not None:
            contribution = self.contributions[agent_id]
            return deepcopy(
                {
                    "entity_ops": contribution["entity_ops"],
                    **({"plotline_ops": contribution["plotline_ops"]} if contribution.get("plotline_ops") else {}),
                    "relation_assert_ops": [
                        *contribution["relation_assert_ops"],
                        *contribution.get("relation_link_ops", []),
                    ],
                }
            )
        if self.contributions:
            raise ValueError("共享事实图 drain 必须指定执行")
        drained = {"entity_ops": self.entity_ops, "relation_assert_ops": self.relation_assert_ops}
        self.entity_ops = []
        self.relation_assert_ops = []
        return drained

    def reset_chapter_relations(self) -> None:
        """在完整替换语义下撤销当章 assert 的关系

        同一章节内关系集合先 reset 再重新 apply，本章新增边累加的 support_count
        需同步回退，否则重新提交已 assert 边会重复 +1。
        """
        author = self._author.get()
        if author is not None:
            self.contributions[author]["relation_assert_ops"] = []
            self._fold()
            return
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

    def snapshot(self) -> dict:
        """用于保存章节尝试前的完整事实图快照"""
        author = self._author.get()
        if author is not None:
            return {"contribution": deepcopy(self.contributions[author]), "author": author}
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
        """在章节尝试失败时恢复事实图快照"""
        if "author" in snap:
            self.contributions[snap["author"]] = snap["contribution"]
            self._fold()
            return
        if self.contributions:
            raise ValueError("共享事实图禁止恢复全书快照")
        for field_name, value in snap.items():
            setattr(self, field_name, value)

    def entity_type_of(self, name: str, entity_type: object) -> EntityType | None:
        """按 (规范名, 实体大类) 查询实时事实图实体大类"""
        return self.entity_types.get(_entity_key(name, entity_type))

    def resolve_key(self, key: str) -> str:
        """沿"同一人物"连通分量把别名身份键解析为代表身份键（标记优先）"""
        representative_key = self._representative_key(key)
        if representative_key is None:
            return key
        return representative_key

    def resolve_name(self, name: str, entity_type: object) -> str:
        """沿"同一人物"连通分量把 (名, 大类) 解析为规范登记名（标记优先）"""
        key = _entity_key(name, entity_type)
        representative_key = self._representative_key(key)
        if representative_key is None:
            return name
        return self.entity_names.get(representative_key, name)

    def alias_group(self, key: str) -> list[str]:
        """取该身份键同一人物连通分量内的其余登记名（不含自身，供进度账本别名列）"""
        return [self.entity_names.get(node, node) for node in self._same_person_component(key) if node != key]

    def _same_person_component(self, key: str) -> list[str]:
        """收集同一人物边连通分量中该名字所在分量的全部成员键（不在分量则空）"""
        identifier = self.entity_id_for_key(key)
        if identifier is None:
            return []
        resolution = self.identity_resolution()
        representative = resolution.representatives[identifier]
        return [
            node
            for node in self.entity_names
            if resolution.representatives.get(self.entity_id_for_key(node) or "") == representative
        ]

    def identity_resolution(self) -> IdentityResolution:
        """正式身份事实唯一解析面，不使用名字子串或登记先后推断身份"""
        identifiers = {self._id_for(key) for key in self.entity_names}
        same = {
            (self._id_for(left), self._id_for(right))
            for left, right, relation in self.active_relations
            if relation == "同一人物"
        }
        differences: dict[tuple[str, str], bool] = {}
        roles = {"annotation": 0, "entity": 0, "event": 1, "metric": 2, "case": 3, "report": 3}
        for _, contribution in sorted(
            self.contributions.items(), key=lambda item: (item[1]["sequence"], roles[item[1]["role"]], item[0])
        ):
            for op in [*contribution["relation_assert_ops"], *contribution.get("relation_link_ops", [])]:
                if op["relation_type"] == "同一人物":
                    left, right = sorted((self._id_for(op["from_entity"]), self._id_for(op["to_entity"])))
                    differences[left, right] = op.get("identity_kind") == "different"
        preferred = {
            self._id_for(key) for key, attrs in self.entity_attributes.items() if attrs.get("is_representative")
        }
        return resolve_identities(
            identifiers, same, {pair for pair, negative in differences.items() if negative}, preferred
        )

    def _representative_key(self, key: str) -> str | None:
        """代表选择与读侧共用稳定 id 规则，冲突身份不自动合并"""
        identifier = self.entity_id_for_key(key)
        if identifier is None:
            return None
        representative = self.identity_resolution().representatives.get(identifier, identifier)
        return next((item for item in self.entity_names if self.entity_id_for_key(item) == representative), None)


__all__ = ["FactGraph"]


def execution_entities(session: Any, run_id: str) -> set[str]:
    return set(session.reads.fact_graph_graph_execution_entities_1(run_id))
