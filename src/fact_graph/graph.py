"""正式章节独立的实体与关系状态，操作日志随不可变章节结果提交"""

from __future__ import annotations

import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from uuid import NAMESPACE_DNS, uuid5

from sqlalchemy.orm import Session

from src.fact_graph.contributions import FactContribution
from src.fact_graph.inputs import RelationInput
from src.fact_graph.vocabulary import RELATION_DEFINITIONS, EntityType

_CONTRIBUTION_FACT_TYPES = {"entity", "relation", "character_observation", "entity_reference"}


def _norm(value: str) -> str:
    """2026-08-09 用于生成实体名称精确匹配键"""
    return unicodedata.normalize("NFC", value).strip().casefold()


def _entity_uuid(run_scope: str, key: str) -> str:
    """2026-09-19 用于按 run+归一化名确定性铸造实体 id（uuid5，重启重放同值）"""
    return str(uuid5(NAMESPACE_DNS, f"novel-annotation-entity:{run_scope}:{key}"))


def mention_uuid(run_id: str, chapter_id: int, name: str) -> str:
    """所有生产方使用 run 与归一化名称的同一实体身份"""
    return _entity_uuid(run_id, _norm(name))


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
    # 章内名称定位生成稳定提及 ID，跨章归属由标注 Agent 的身份结论确定
    entity_ids: dict[str, str] = field(default_factory=dict, init=False)
    entity_ops: list[dict[str, Any]] = field(default_factory=list, init=False)
    relation_assert_ops: list[dict[str, Any]] = field(default_factory=list, init=False)
    contributions: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict, init=False)
    saved: set[tuple[str, str]] = field(default_factory=set, init=False)
    _author: ContextVar[tuple[str, str] | None] = field(
        default_factory=lambda: ContextVar("fact_author", default=None), init=False
    )

    def begin(self, work_id: str, invocation_id: str, chapter_sequence: int, role: str) -> None:
        key = (work_id, invocation_id)
        if any(author[0] == work_id and author in self.saved for author in self.contributions):
            raise ValueError(f"已保存 work 不可重新打开: {work_id}")
        self.contributions.setdefault(
            key,
            {
                "sequence": chapter_sequence,
                "role": role,
                "entity_ops": [],
                "relation_assert_ops": [],
            },
        )

    @contextmanager
    def author(self, work_id: str, invocation_id: str):
        key = (work_id, invocation_id)
        if key not in self.contributions or key in self.saved:
            raise ValueError(f"事实图执行已停止: {work_id}/{invocation_id}")
        token = self._author.set(key)
        try:
            yield
        finally:
            self._author.reset(token)

    def rollback(self, work_id: str, invocation_id: str) -> None:
        key = (work_id, invocation_id)
        if key not in self.saved:
            self.contributions.pop(key, None)
            self._fold()

    def confirm(self, work_id: str, invocation_id: str) -> None:
        self.saved.add((work_id, invocation_id))

    def reference_entities(self, author: tuple[str, str], references: list[dict[str, Any]]) -> None:
        """Agent 持锁冻结实际引用，其他作者撤销后仍保留本次有效端点支持"""
        if author not in self.contributions or author in self.saved:
            raise ValueError(f"事实图引用执行已停止: {author}")
        self.contributions[author]["entity_references"] = deepcopy(references)
        self._fold()

    def save_work(self, session: Session, frozen: FactContribution, annotation_id: str) -> None:
        """保存自己的不可变操作，再按实际章序和角色序重折数据库状态"""
        from sqlalchemy import select, text

        from src.fact_graph.evidence import evidence_for
        from src.fact_graph.identity import relation_id
        from src.storage.models import GraphEntity, GraphFact, GraphRelation
        from src.utils.identity import stable_digest

        # 数据库锁只串行化图的折叠写入，不占 run 内存锁、不等待角色 finish
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"fact_graph:{self.run_scope}"}
        )
        contribution = frozen.snapshot()
        chapter_id = frozen.chapter_id
        entities = contribution["entities"]
        for identifier, value in entities.items():
            if session.get(GraphEntity, identifier) is None:
                session.add(
                    GraphEntity(
                        entity_id=identifier,
                        run_id=self.run_scope,
                        canonical_name=value["name"],
                        entity_type=value["entity_type"],
                        tags=[],
                        attributes={},
                        first_seen_chapter=chapter_id,
                        last_seen_chapter=chapter_id,
                    )
                )
        session.flush()
        operations = [("entity", op) for op in contribution["entity_ops"]]
        operations += [("relation", op) for op in contribution["relation_assert_ops"]]
        operations += [("character_observation", op) for op in frozen.observations()]
        # 引用是当前 work 的实际有效支持，不把读取到的实体伪造成一次实体写入
        operations += [("entity_reference", value) for _, value in sorted(entities.items())]
        for index, (kind, op) in enumerate(operations):
            path = f"work/{frozen.work_id}/{kind}/{index}"
            entity_name = op.get("name") or op.get("character") or op.get("from_entity")
            entity_id = mention_uuid(self.run_scope, chapter_id, entity_name)
            content = {"kind": kind, "operation": op, "operation_order": index}
            if kind == "character_observation":
                content.update(op, entity=entities[entity_id], chapter_id=chapter_id)
            if kind == "relation":
                target_id = mention_uuid(self.run_scope, chapter_id, op["to_entity"])
                direction = RELATION_DEFINITIONS[op["relation_type"]]["directionality"]
                identifier = relation_id(self.run_scope, entity_id, target_id, op["relation_type"], direction)
                content["relation_id"] = identifier
                if session.get(GraphRelation, identifier) is None:
                    session.add(
                        GraphRelation(
                            relation_id=identifier,
                            run_id=self.run_scope,
                            from_entity_id=entity_id,
                            to_entity_id=target_id,
                            directionality=direction,
                            relation_semantics="same_character" if op["relation_type"] == "同一人物" else "ordinary",
                        )
                    )
                    session.flush()
            if (
                session.execute(
                    select(GraphFact).where(GraphFact.run_id == self.run_scope, GraphFact.payload_path == path)
                ).scalar_one_or_none()
                is None
            ):
                session.add(
                    GraphFact(
                        run_id=self.run_scope,
                        chapter_id=chapter_id,
                        fact_id=stable_digest(path),
                        fact_type=kind,
                        subject_entity_id=entity_id,
                        predicate=kind,
                        object=None,
                        value=op,
                        participants=[],
                        scope="book",
                        assertion="asserted",
                        confidence="high",
                        content=content,
                        effective_chapter_id=chapter_id,
                        source_kind="annotation",
                        annotation_id=annotation_id,
                        payload_path=path,
                        author_work_id=frozen.work_id,
                        evidence=evidence_for(frozen.paragraphs),
                    )
                )
        session.flush()
        self.rebuild_storage(session, preserve=set(contribution["entities"]))

    def rebuild_storage(self, session: Any, *, preserve: set[str] | None = None) -> None:
        """恢复和乱序保存共用重折，所有状态只来自实际保存的贡献"""
        from sqlalchemy import delete, select

        from src.storage.models import (
            AnalysisOutput,
            EntityState,
            GraphEntity,
            GraphFact,
            GraphRelation,
            RelationState,
        )

        records = {
            row.output_id: row
            for row in session.execute(
                select(AnalysisOutput).where(
                    AnalysisOutput.run_id == self.run_scope, AnalysisOutput.kind == "chapter_annotation"
                )
            ).scalars()
        }
        roles = {"solo": 0, "structure": 0, "event": 1, "evidence": 2}
        all_facts = list(session.execute(select(GraphFact).where(GraphFact.run_id == self.run_scope)).scalars())
        # 历史事件、身份事实保留给原消费者，不参与当前 work 操作序列
        facts = [fact for fact in all_facts if fact.fact_type in _CONTRIBUTION_FACT_TYPES]
        facts.sort(
            key=lambda fact: (
                records[fact.annotation_id].actual_input["chapter_sequence"],
                roles[records[fact.annotation_id].role],
                fact.author_work_id or "",
                fact.content["operation_order"],
            )
        )
        session.execute(delete(EntityState).where(EntityState.run_id == self.run_scope))
        session.execute(delete(RelationState).where(RelationState.run_id == self.run_scope))
        states: dict[tuple[int, str], Any] = {}
        entity_values: dict[str, dict[str, Any]] = {}
        relation_values: dict[str, int] = {}
        relations: dict[tuple[int, str], Any] = {}
        for fact in facts:
            op = fact.value
            if fact.fact_type == "entity_reference":
                entity = session.get(GraphEntity, fact.subject_entity_id)
                current = entity_values.setdefault(entity.entity_id, {"attributes": {}, "tags": []})
                current.setdefault("entity_type", op["entity_type"])
                current.setdefault("name", op["name"])
                continue
            if fact.fact_type in {"entity", "character_observation"}:
                entity = session.get(GraphEntity, fact.subject_entity_id)
                current = entity_values.setdefault(entity.entity_id, {"attributes": {}, "tags": []})
                before = deepcopy(current)
                if fact.fact_type == "entity":
                    current["entity_type"] = op["entity_type"]
                    current["name"] = op["name"]
                    entity.canonical_name = op["name"]
                    entity.entity_type = op["entity_type"]
                    if op.get("description") is not None:
                        current["attributes"]["description"] = op["description"]
                    for name, value in op["attributes"].items():
                        if value is None:
                            current["attributes"].pop(name, None)
                        else:
                            current["attributes"][name] = value
                    current["tags"] = op["tags"]
                else:
                    for name in ("role_function", "action", "emotion"):
                        if op.get(name) is not None:
                            current[name] = op[name]
                key = (fact.chapter_id, entity.entity_id)
                state = states.get(key)
                if state is None:
                    state = EntityState(
                        run_id=self.run_scope,
                        chapter_id=fact.chapter_id,
                        entity_id=entity.entity_id,
                        state={},
                        changes=[],
                        author_work_id=fact.author_work_id,
                    )
                    states[key] = state
                    session.add(state)
                state.state = deepcopy(current)
                fields = (
                    {"entity_type": op["entity_type"], **op["attributes"]}
                    if fact.fact_type == "entity"
                    else {name: op[name] for name in ("role_function", "action", "emotion") if op.get(name) is not None}
                )
                if fact.fact_type == "entity" and op.get("description") is not None:
                    fields["description"] = op["description"]
                state.changes = [
                    *state.changes,
                    *[
                        {
                            "fact_id": fact.fact_id,
                            "chapter_id": fact.chapter_id,
                            "author_work_id": fact.author_work_id,
                            "operation": op,
                            "field": name,
                            "before": before.get(name, before["attributes"].get(name)),
                            "after": value,
                        }
                        for name, value in fields.items()
                    ],
                ]
                entity.tags, entity.attributes = deepcopy(current["tags"]), deepcopy(current["attributes"])
                touched = [item.chapter_id for item in facts if item.subject_entity_id == entity.entity_id]
                chapter_order = {row.chapter_id: row.actual_input["chapter_sequence"] for row in records.values()}
                entity.first_seen_chapter = min(touched, key=lambda value: chapter_order[value])
                entity.last_seen_chapter = max(touched, key=lambda value: chapter_order[value])
            elif fact.fact_type == "relation":
                identifier = fact.content["relation_id"]
                relation_values[identifier] = relation_values.get(identifier, 0) + 1
                key = (fact.chapter_id, identifier)
                state = relations.get(key)
                if state is None:
                    state = RelationState(
                        run_id=self.run_scope,
                        chapter_id=fact.chapter_id,
                        relation_id=identifier,
                        relation_type=op["relation_type"],
                        attributes={},
                        is_active=True,
                        changes=[],
                        author_work_id=fact.author_work_id,
                    )
                    relations[key] = state
                    session.add(state)
                state.is_active = op.get("change_kind", "assert") not in {"break", "retract"}
                state.attributes = {"support_count": relation_values[identifier]}
                state.changes = [
                    *state.changes,
                    {
                        "fact_id": fact.fact_id,
                        "chapter_id": fact.chapter_id,
                        "author_work_id": fact.author_work_id,
                        "operation": op,
                        "change_kind": op.get("change_kind", "assert"),
                        "reason": op.get("reason"),
                    },
                ]
        # 仅剩有效引用时保留真实身份，已丢弃写入留下的属性不继续冒充有效贡献
        chapter_order = {row.chapter_id: row.actual_input["chapter_sequence"] for row in records.values()}
        for identifier, current in entity_values.items():
            entity = session.get(GraphEntity, identifier)
            if "name" in current:
                entity.canonical_name = current["name"]
                entity.entity_type = current["entity_type"]
            entity.tags, entity.attributes = deepcopy(current["tags"]), deepcopy(current["attributes"])
            touched = [item.chapter_id for item in facts if item.subject_entity_id == identifier]
            entity.first_seen_chapter = min(touched, key=lambda value: chapter_order[value])
            entity.last_seen_chapter = max(touched, key=lambda value: chapter_order[value])
        from src.storage.models import DialogueRecord

        live_entities = {fact.subject_entity_id for fact in all_facts}
        live_entities.update(preserve or set())
        for relation in session.execute(
            select(GraphRelation).where(GraphRelation.relation_id.in_(relation_values))
        ).scalars():
            live_entities.update((relation.from_entity_id, relation.to_entity_id))
        live_entities.update(
            session.execute(select(DialogueRecord.speaker).where(DialogueRecord.run_id == self.run_scope)).scalars()
        )
        for value in execution_entities(session, self.run_scope):
            live_entities.add(value)
        live_relations = set(relation_values)
        session.execute(
            delete(GraphRelation).where(
                GraphRelation.run_id == self.run_scope, GraphRelation.relation_id.not_in(live_relations)
            )
        )
        session.execute(
            delete(GraphEntity).where(GraphEntity.run_id == self.run_scope, GraphEntity.entity_id.not_in(live_entities))
        )
        session.flush()

    def save_main_characters(self, session: Any, main_characters: list[str]) -> None:
        """2026-08-09 用于把诊断主角名单固化为图节点属性"""
        from sqlalchemy import select

        run_id = self.run_scope

        from src.fact_graph.errors import GraphReadinessError
        from src.fact_graph.read import KnowledgeGraphAuthorityService
        from src.storage.models import GraphEntity

        if not main_characters:
            return
        try:
            view = KnowledgeGraphAuthorityService.from_session(session).build_export_view(run_id)
        except (ValueError, GraphReadinessError):
            # 图未就绪或数据异常时静默跳过主角属性固化（后续图版本补写）
            return
        preferred = set(main_characters)
        representative_ids: set[str] = set()
        for item in view.canonical_entities:
            if item.entity_id is None:
                continue
            aliases = set(item.aliases)
            if item.name in preferred or (aliases & preferred):
                representative_ids.add(str(item.entity_id))
        if not representative_ids:
            return
        graph_entities = list(
            session.execute(
                select(GraphEntity).where(
                    GraphEntity.run_id == run_id,
                )
            ).scalars()
        )
        # 2026-08-13 P2-2 重跑诊断先清除该 run 全部实体的 is_main_character 标记，
        # 避免旧名单残留（只置位不清理会让已下榜角色仍显示为主角）。
        # attributes 是 JSON 列，这里读改写后整体写回，与下文置位共用同一批实体。
        for graph_entity in graph_entities:
            attributes = dict(graph_entity.attributes or {})
            if attributes.pop("is_main_character", None) is not None:
                graph_entity.attributes = attributes
        for graph_entity in graph_entities:
            if graph_entity.entity_id not in representative_ids:
                continue
            attributes = dict(graph_entity.attributes or {})
            attributes["is_main_character"] = True
            graph_entity.attributes = attributes
        session.flush()

    def discard_storage(self, session: Any, work_ids: set[str]) -> None:
        from sqlalchemy import delete

        from src.storage.models import GraphFact

        session.execute(
            delete(GraphFact).where(GraphFact.run_id == self.run_scope, GraphFact.author_work_id.in_(work_ids))
        )

    def restore_storage(self, session: Any, records: list[Any]) -> None:
        from sqlalchemy import select

        from src.storage.models import GraphFact

        # 整书启动恢复重建当前保留集；运行中单 work 确认使用 recover_work
        self.contributions.clear()
        self.saved.clear()
        for record in records:
            facts = list(
                session.execute(select(GraphFact).where(GraphFact.annotation_id == record.output_id)).scalars()
            )
            facts = [fact for fact in facts if fact.fact_type in _CONTRIBUTION_FACT_TYPES]
            facts.sort(key=lambda fact: fact.content["operation_order"])
            self.restore_work(
                record.work_id,
                record.invocation_id,
                record.actual_input["chapter_sequence"],
                record.role,
                [fact.value for fact in facts if fact.fact_type == "entity"],
                [fact.value for fact in facts if fact.fact_type == "relation"],
                [fact.value for fact in facts if fact.fact_type == "entity_reference"],
            )
        self._fold()

    def load_saved_work(self, session: Any, work_id: str, invocation_id: str, annotation_id: str) -> dict[str, Any]:
        """锁外读取当前 work 的真实保存贡献，不读取或撤销其他执行"""
        from sqlalchemy import select

        from src.storage.models import AnalysisOutput, GraphFact

        record = session.get(AnalysisOutput, annotation_id)
        if record is None or record.work_id != work_id or record.invocation_id != invocation_id:
            raise ValueError(f"事实图保存身份不一致: {work_id}/{invocation_id}")
        facts = list(
            session.execute(
                select(GraphFact).where(GraphFact.run_id == self.run_scope, GraphFact.author_work_id == work_id)
            ).scalars()
        )
        facts = [fact for fact in facts if fact.fact_type in _CONTRIBUTION_FACT_TYPES]
        facts.sort(key=lambda fact: fact.content["operation_order"])
        return {
            "author": (work_id, invocation_id),
            "sequence": record.actual_input["chapter_sequence"],
            "role": record.role,
            "entity_ops": deepcopy([fact.value for fact in facts if fact.fact_type == "entity"]),
            "relation_assert_ops": deepcopy([fact.value for fact in facts if fact.fact_type == "relation"]),
            "entity_references": deepcopy([fact.value for fact in facts if fact.fact_type == "entity_reference"]),
        }

    def recover_work(self, snapshot: dict[str, Any]) -> None:
        """同 run 锁内替换一个已保存作者，保护其他在飞贡献"""
        self.restore_work(
            snapshot["author"][0],
            snapshot["author"][1],
            snapshot["sequence"],
            snapshot["role"],
            snapshot["entity_ops"],
            snapshot["relation_assert_ops"],
            snapshot["entity_references"],
        )

    def restore_work(
        self,
        work_id: str,
        invocation_id: str,
        sequence: int,
        role: str,
        entity_ops: list[dict[str, Any]],
        relation_ops: list[dict[str, Any]],
        entity_references: list[dict[str, Any]] | None = None,
    ) -> None:
        self.contributions[(work_id, invocation_id)] = {
            "sequence": sequence,
            "role": role,
            "entity_ops": deepcopy(entity_ops),
            "relation_assert_ops": deepcopy(relation_ops),
            "entity_references": deepcopy(entity_references or []),
        }
        self.saved.add((work_id, invocation_id))
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
        role_order = {"solo": 0, "structure": 0, "event": 1, "evidence": 2}
        ordered = sorted(
            self.contributions.items(),
            key=lambda item: (
                item[1]["sequence"],
                role_order[item[1]["role"]],
                item[0][0],
            ),
        )
        for _, contribution in ordered:
            for reference in contribution.get("entity_references", []):
                key = _norm(reference["name"])
                if reference["entity_id"] != _entity_uuid(self.run_scope, key):
                    raise ValueError(f"实体引用身份不一致: {reference}")
                self._id_for(key)
                self.entity_names.setdefault(key, reference["name"])
                self.entity_types.setdefault(key, EntityType(reference["entity_type"]))
                self.entity_tags.setdefault(key, [])
                self.entity_attributes.setdefault(key, {})
            for op in contribution["entity_ops"]:
                key = _norm(op["name"])
                self.entity_names[key] = op["name"]
                self.entity_types.setdefault(key, EntityType(op["entity_type"]))
                self.entity_tags[key] = op["tags"]
                attrs = dict(self.entity_attributes.get(key, {}))
                if op["description"] is not None:
                    attrs["description"] = op["description"]
                for name, value in op["attributes"].items():
                    if value is None:
                        attrs.pop(name, None)
                    else:
                        attrs[name] = value
                self.entity_attributes[key] = attrs
            for op in [*contribution["relation_assert_ops"], *contribution.get("relation_link_ops", [])]:
                relation_key = self._relation_key(op["from_entity"], op["to_entity"], op["relation_type"])
                if op.get("change_kind", "assert") in {"break", "retract"}:
                    self.active_relations.discard(relation_key)
                else:
                    self.active_relations.add(relation_key)
                    self._bump_support_count(relation_key)

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
            raise ValueError(f"{label} 实体 id 未登记：id 取自本章 write_entity 回执")
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
        author = self._author.get()
        if author is not None:
            self.contributions[author]["entity_ops"].extend(deepcopy(self.entity_ops[-len(entities) :]))
            self._fold()

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
        author = self._author.get()
        if author is not None:
            self.contributions[author]["relation_assert_ops"] = deepcopy(self.relation_assert_ops)
            self._fold()

    def drain_ops(
        self, work_id: str | None = None, invocation_id: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """取出本章局部命令，交给正式提交事务"""
        if work_id is not None and invocation_id is not None:
            contribution = self.contributions[(work_id, invocation_id)]
            return deepcopy(
                {
                    "entity_ops": contribution["entity_ops"],
                    "relation_assert_ops": [
                        *contribution["relation_assert_ops"],
                        *contribution.get("relation_link_ops", []),
                    ],
                }
            )
        if self.contributions:
            raise ValueError("共享事实图 drain 必须指定 work 与 invocation")
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
        """2026-08-09 用于保存章节尝试前的完整事实图快照

        2026-09-19 实体 id 注册表刻意不进快照：id 由 uuid5(run+名) 确定性铸造，
        失败回滚不回收也不改变，回滚撤销的登记由 resolve_entity_id 的
        存活性校验兜底，不会把陈旧 id 解析成别的实体。
        """
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
        """2026-08-09 用于在章节尝试失败时恢复事实图快照"""
        if "author" in snap:
            self.contributions[snap["author"]] = snap["contribution"]
            self._fold()
            return
        if self.contributions:
            raise ValueError("共享事实图禁止恢复全书快照")
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


def execution_entities(session: Any, run_id: str) -> set[str]:
    from sqlalchemy import select

    from src.storage.models import EventNode

    return {
        participant["entity"]["entity_id"]
        for node in session.execute(select(EventNode).where(EventNode.run_id == run_id)).scalars()
        for participant in node.participants
    }
