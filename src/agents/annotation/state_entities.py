"""实体关系的局部绑定与输入状态；不持有队列、模型会话或保存事务"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import EntityDirectoryInput, EntityInput, RelationInput
from src.fact_graph.outputs import BoundCharacterObservation
from src.fact_graph.vocabulary import RELATION_DEFINITIONS, DialogueVerdict, EntityType, RelationType

from .errors import (
    AnnotationInvariantError,
    AnnotationStageRejection,
)
from .tools import _norm_entity_key, _norm_graph_name
from .validation_errors import _translate_record_validation


class EntityRelationStateContext(Protocol):
    """只开放此工作状态需要的上下文和引用能力"""

    def _require_writable(self, record: str) -> None: ...

    current_chapter_id: int
    graph: FactGraph | None

    def resolve_entity_ref(self, ref: str, *, record: str, field: str) -> str: ...


@dataclass(slots=True)
class EntityRelationState:
    written_entities: dict[str, EntityInput] = field(default_factory=dict)
    written_relations: dict[tuple[str, str], RelationInput] = field(default_factory=dict)
    entity_el_index: dict[str, str] = field(default_factory=dict)
    domain_payloads: dict[str, Any] = field(default_factory=dict)
    bound_payloads: dict[str, Any] = field(default_factory=dict)

    def apply_entity(
        self, ctx: EntityRelationStateContext, entity: EntityInput, *, el: str, present: set[str] | None = None
    ) -> str:
        """用于登记或更新一个实体、绑定 el 局部键并即时返回 run 级 id（同键同内容重放幂等）

        present（本次实际提交的字段集合）给定时按部分更新合并：未提交字段保留现值，
        兑现 write_entity 合同"只提交本次变化的字段"；不传=整条记录语义（直连调用）。
        """
        record = f"entity/{entity.name}"
        ctx._require_writable(record)
        normalized_el = unicodedata.normalize("NFC", el).strip()
        bound_key = self.entity_el_index.get(normalized_el)
        if bound_key is not None and bound_key != _norm_entity_key(entity.name):
            raise AnnotationStageRejection(
                f"el 键已被另一实体占用: {normalized_el}",
                record=record,
                field="el",
                code="duplicate_el",
                expected="换一个 el 键（el 在 章内一对一绑定实体）",
            )
        key = _norm_entity_key(entity.name)
        existing = self.written_entities.get(key)
        if existing is not None and present is not None:
            # 部分更新：先合并成生效记录，再落图（闸门看到的永远是完整记录）
            entity = self._merge_partial_entity(existing, entity, present)
            record = f"entity/{entity.name}"
        if ctx.graph is None:
            raise AnnotationInvariantError("write_entity 需要常驻事实图，graph 缺失")
        registered = ctx.graph.entity_types.get(key)
        if registered is not None and registered != entity.entity_type:
            raise AnnotationStageRejection(
                f"已登记实体不允许变更大类: {entity.name}",
                record=record,
                field="entity_type",
                code="type_conflict",
                expected=f"{registered}（同一词条的不同身份请用区分性名称）",
            )
        if existing is None or existing != entity:
            # 同键不同内容=更新语义；同键同内容直接跳过，避免重复操作日志
            ctx.graph.register_entities([entity])
            ctx.graph.record_entity_ops([entity], chapter_id=ctx.current_chapter_id)
            self.written_entities[key] = entity
            self._rebuild_entity_payload()
        self.entity_el_index[normalized_el] = key
        entity_id = ctx.graph.entity_id(entity.name)
        if entity_id is None:
            raise AnnotationInvariantError(f"实体 id 登记失败: {entity.name}")
        return entity_id

    @staticmethod
    def _merge_partial_entity(existing: EntityInput, incoming: EntityInput, present: set[str]) -> EntityInput:
        """用于已登记实体的部分更新合并（2026-09-14 兑现"只提交本次变化的字段"合同）

        未提交字段保留现值；tags 提交空列表=清空、省略=保留；
        attributes 提交即 JSON Merge Patch（值覆盖、null 删键、省略=整域保留）。
        """
        updates: dict[str, Any] = {}
        if "tags" in present:
            updates["tags"] = incoming.tags
        if "description" in present:
            updates["description"] = incoming.description
        merged = existing.model_copy(update=updates)
        if "attributes" in present:
            patched = dict(existing.attributes or {})
            for attr_key, attr_value in (incoming.attributes or {}).items():
                if attr_value is None:
                    patched.pop(attr_key, None)
                else:
                    patched[attr_key] = attr_value
            merged.attributes = patched
        return merged

    def _rebuild_entity_payload(self) -> None:
        """用于按写入顺序重建当前章 的实体目录载荷"""
        self.domain_payloads["entities"] = EntityDirectoryInput(entities=list(self.written_entities.values()))

    def apply_relation(
        self,
        ctx: EntityRelationStateContext,
        *,
        from_ref: str,
        to_ref: str,
        relation_type: RelationType,
    ) -> tuple[str, str, dict[str, Any]]:
        """用于写入一条本章确认存在的闭合关系边（同一对端点换类型即整体替换）

        返回 (记录键, 本条边的入图结果, 本次写入内容)：assert=新边入图 /
        skipped_existing=已在图上 /
        skipped_self_loop=两端解析到同一实体且非"同一人物"语义（不入图）。
        """
        provisional = f"relation/{from_ref}-{to_ref}/{relation_type}"
        ctx._require_writable(provisional)
        if ctx.graph is None:
            raise AnnotationInvariantError("write_relation 需要常驻事实图，graph 缺失")
        from_name = ctx.resolve_entity_ref(from_ref, record=provisional, field="from_entity")
        to_name = ctx.resolve_entity_ref(to_ref, record=provisional, field="to_entity")
        record = f"relation/{from_name}-{to_name}/{relation_type}"
        definition = RELATION_DEFINITIONS[str(relation_type)]
        entity_types = self._fact_entity_catalog(ctx)
        for field_name, name, expected_types in (
            ("from_entity", from_name, definition["from_types"]),
            ("to_entity", to_name, definition["to_types"]),
        ):
            try:
                self._require_entity(
                    ctx,
                    name,
                    entity_types=entity_types,
                    expected_types=expected_types,
                    label=f"write_relation.{field_name}",
                )
            except ValueError as exc:
                raise AnnotationStageRejection(
                    f"{record}({field_name}={name!r})：{exc}",
                    record=record,
                    field=field_name,
                    code="endpoint_invalid",
                    expected=f"端点类型必须属于 {list(expected_types)}",
                ) from None
        try:
            item = RelationInput(
                from_entity=from_name,
                to_entity=to_name,
                relation_type=relation_type,
            )
        except ValidationError as exc:
            raise _translate_record_validation(record, exc, tool_name="write_relation") from None
        self.written_relations[(item.from_entity, item.to_entity)] = item
        outcomes = self._flush_relations(ctx)
        resolution = (ctx.graph.resolve_name(item.from_entity), ctx.graph.resolve_name(item.to_entity))
        outcome = next(
            (
                entry["outcome"]
                for entry in outcomes
                if (entry["from"], entry["to"]) == resolution and entry["relation_type"] == str(item.relation_type)
            ),
            "assert",
        )
        return record, outcome, item.model_dump(mode="json")

    def _flush_relations(self, ctx: EntityRelationStateContext) -> list[dict[str, Any]]:
        """用于把本章关系完整集合重放到事实图（先清空本章 assert 再按序重放）

        与旧的"领域结算整体替换"语义一致：同一对端点重写换类型即为替换，
        重放保证图终态与本章关系集合同源。
        """
        if ctx.graph is None:
            raise AnnotationInvariantError("write_relation 需要常驻事实图，graph 缺失")
        ctx.graph.reset_chapter_relations()
        outcomes: list[dict[str, Any]] = []
        resolved_items: list[RelationInput] = []
        for item in self.written_relations.values():
            resolved_from = ctx.graph.resolve_name(item.from_entity)
            resolved_to = ctx.graph.resolve_name(item.to_entity)
            if _norm_graph_name(resolved_from) == _norm_graph_name(resolved_to):
                # 两端沿同一人物分量解析到同一实体：
                # "同一人物"边（含同批双向重申、跨章重申、传递归并）= 归并已
                # 成立，按合同接受为 skipped_existing；普通关系类型塌成自环
                # 才是退化输入，标 skipped_self_loop。两者照常入图都会在持久化
                # 插入 from_entity_id=to_entity_id 的自环行，违反
                # graph_relations 端点互异约束炸掉完成事务（run a83fae3d
                # 第9章实锤），一律跳过不入图不入操作日志
                is_same_character = RELATION_DEFINITIONS[str(item.relation_type)]["semantics"] == "same_character"
                outcomes.append(
                    {
                        "from": resolved_from,
                        "to": resolved_to,
                        "relation_type": str(item.relation_type),
                        "outcome": "skipped_existing" if is_same_character else "skipped_self_loop",
                    }
                )
                continue
            dumped = item.model_dump(mode="python")
            dumped["from_entity"] = resolved_from
            dumped["to_entity"] = resolved_to
            resolved_item = RelationInput(**dumped)
            resolved_items.append(resolved_item)
            added = ctx.graph.apply_relation(resolved_item)
            outcomes.append(
                {
                    "from": resolved_from,
                    "to": resolved_to,
                    "relation_type": str(item.relation_type),
                    "outcome": "assert" if added else "skipped_existing",
                }
            )
        ctx.graph.record_relation_asserts(resolved_items, chapter_id=ctx.current_chapter_id)
        self.domain_payloads["relations"] = list(self.written_relations.values())
        return outcomes

    def entity_content(self, ctx: EntityRelationStateContext, entity: EntityInput) -> dict[str, Any]:
        """用于回显 write_entity 登记/更新后该实体生效记录（含 run 级 id）"""
        stored = self.written_entities.get(_norm_entity_key(entity.name), entity)
        content = stored.model_dump(mode="json")
        content["id"] = ctx.graph.entity_id(stored.name) if ctx.graph is not None else None
        return content

    def entity_ledger(self, ctx: EntityRelationStateContext) -> list[dict[str, Any]]:
        """用于列举本章已写入实体的账本（el 绑定序）：{el, name, id, entity_type}，带 tags 与同一人物别名

        别名列（alias）与标签列直接对抗"外号没接上登记名→重复注册实体"（run b7477080
        ch3 把猴子当新人物又建一套登记）。
        2026-09-20 entity_type：大类一经登记不可变更，账本行带上它，省得模型凭记忆重写
        时写错大类（run 54a72932：10 次"实体大类已登记为 X"的拒绝）。
        """
        rows: list[dict[str, Any]] = []
        for el, key in self.entity_el_index.items():
            stored = self.written_entities.get(key)
            if stored is None:
                continue
            row: dict[str, Any] = {
                "el": el,
                "name": stored.name,
                "id": ctx.graph.entity_id(stored.name) if ctx.graph is not None else None,
                "entity_type": str(stored.entity_type),
            }
            if stored.tags:
                row["tags"] = list(stored.tags)
            if ctx.graph is not None:
                aliases = ctx.graph.alias_group(stored.name)
                if aliases:
                    row["aliases"] = aliases
            rows.append(row)
        return rows

    def _entity_catalog(
        self,
        directory: EntityDirectoryInput,
    ) -> tuple[dict[str, EntityType], dict[str, str]]:
        """2026-08-08 用于建立当前章 唯一实体名称和类型目录"""
        types: dict[str, EntityType] = {}
        names: dict[str, str] = {}
        for entity in directory.entities:
            normalized = unicodedata.normalize("NFC", entity.name).strip()
            key = normalized.casefold()
            if key in types:
                raise ValueError(f"本章 实体名称重复: {normalized}")
            types[key] = entity.entity_type
            names[key] = normalized
        return types, names

    def _fact_entity_catalog(self, ctx: EntityRelationStateContext) -> dict[str, EntityType]:
        """2026-08-10 用于合并内存图已登记实体与当前章 已声明实体作为事实端点目录"""
        catalog = dict(ctx.graph.entity_types) if ctx.graph is not None else {}
        entities_payload = self.domain_payloads.get("entities")
        if entities_payload is not None:
            types, _names = self._entity_catalog(entities_payload)
            catalog.update(types)
        return catalog

    def _require_entity(
        self,
        ctx: EntityRelationStateContext,
        name: str,
        *,
        entity_types: dict[str, EntityType],
        expected_types: tuple[EntityType, ...] | None = None,
        label: str,
    ) -> str:
        """2026-08-11 用于校验事实端点已由当前章 实体目录或已登记实体声明（别名解析后）"""
        key = unicodedata.normalize("NFC", name).strip().casefold()
        resolved_key = key
        if ctx.graph is not None:
            resolved_key = _norm_graph_name(ctx.graph.resolve_name(name))
        actual_type = entity_types.get(resolved_key) or entity_types.get(key)
        if actual_type is None:
            raise ValueError(f"{label} 未在当前章 登记: {name}（请先用 write_entity 登记该实体，或改用已登记实体名）")
        if expected_types is not None and actual_type not in expected_types:
            raise ValueError(
                f"{label} 端点类型必须属于 {[str(t) for t in expected_types]}，实际为 {actual_type}"
                f"（该名称在图上的登记类型是 {actual_type}，"
                "请按登记类型使用，或对同一词条的不同身份使用区分性名称）"
            )
        return key

    def _domain_fact_views(self, ctx: EntityRelationStateContext) -> dict[str, Any]:
        """2026-08-10 用于生成当前候选各领域的事实语义键视图"""
        payloads = self.domain_payloads
        views: dict[str, Any] = {}
        if "metrics" in payloads:
            views["metrics"] = {
                "summary": payloads["metrics"].summary,
                "emotional_valence": str(payloads["metrics"].emotional_valence),
                "narrative_function": str(payloads["metrics"].narrative_function),
            }
        if "entities" in payloads:
            views["entities"] = {
                "items": len(payloads["entities"].entities),
                "names": [entity.name for entity in payloads["entities"].entities],
            }
        if "character_observations" in payloads:
            views["character_observations"] = [
                {
                    "character": item.character,
                    "action": item.action,
                }
                for item in payloads["character_observations"]
            ]
        if "dialogues" in payloads:
            views["dialogues"] = [
                {
                    "candidate_index": item.candidate_index,
                    "verdict": str(item.verdict),
                    "speaker": item.speaker,
                }
                for item in payloads["dialogues"]
            ]
        if "events" in payloads:
            views["events"] = [
                {
                    "node_id": item.node_id,
                    "tree_id": item.tree_id,
                    "parent_node_id": item.parent_node_id,
                    "cause_role": item.cause_role,
                    "description": item.description,
                    "participants": [
                        {
                            "id": (ctx.graph.entity_id(participant.entity) if ctx.graph is not None else None),
                            "entity": participant.entity,
                            "role": str(participant.role),
                        }
                        for participant in item.participants
                    ],
                }
                for item in payloads["events"]
            ]
        if "relations" in payloads:
            views["relations"] = [
                {
                    "from": item.from_entity,
                    "to": item.to_entity,
                    "relation_type": str(item.relation_type),
                }
                for item in payloads["relations"]
            ]
        return views

    def validate_work_endpoints(
        self,
        ctx: EntityRelationStateContext,
        payloads: dict[str, Any],
        observation_records: dict[str, BoundCharacterObservation],
    ) -> None:
        """各角色 finish 重查共享图端点，避免依赖其他失败 work 的临时实体"""
        entity_types, _entity_names = self._entity_catalog(payloads["entities"])
        resolved_entity_types = {
            **(ctx.graph.entity_types if ctx.graph is not None else {}),
            **entity_types,
        }

        # 2026-08-20 内联全量端点校验，合并 _validate_fact_endpoints 和 _validate_domain_endpoints
        # 2026-10-04 错误点名生产记录键（原 "[下标] 域.字段" 模型无法映射回具体记录）
        errors: list[str] = []

        def check_entity(
            name: str,
            expected_types: tuple[EntityType, ...] | None,
            label: str,
            record_label: str,
        ) -> None:
            key = unicodedata.normalize("NFC", name).strip().casefold()
            resolved_key = key
            if ctx.graph is not None:
                resolved_key = _norm_graph_name(ctx.graph.resolve_name(name))
            actual_type = resolved_entity_types.get(resolved_key) or resolved_entity_types.get(key)
            if actual_type is None:
                errors.append(
                    f"{record_label} {label} 未在当前章 登记: {name}"
                    "（请先用 write_entity 登记该实体，或改用已登记实体名）"
                )
                return
            if expected_types is not None and actual_type not in expected_types:
                errors.append(
                    f"{record_label} {label}={name!r} 端点类型必须属于 {[str(t) for t in expected_types]}，"
                    f"实际为 {actual_type}（该名称在图上的登记类型是 {actual_type}，"
                    "请按登记类型使用，或对同一词条的不同身份使用区分性名称）"
                )

        # character_observations 端点校验（载荷顺序与 observation_by_record 一致，可反查记录键）
        observation_keys = list(observation_records)
        for index, item in enumerate(payloads["character_observations"]):
            record_label = str(observation_keys[index]) if index < len(observation_keys) else str(index)
            check_entity(item.character, (EntityType.CHARACTER,), "character_observation.character", record_label)

        # dialogues 端点校验
        for item in payloads["dialogues"]:
            if item.verdict != DialogueVerdict.NOT_DIALOGUE and item.speaker is not None:
                check_entity(
                    item.speaker,
                    (EntityType.CHARACTER,),
                    "dialogue.speaker",
                    f"dialogue/{item.candidate_index}",
                )

        for item in payloads.get("events", []):
            for participant in item.participants:
                check_entity(participant.entity, None, "event.participant.entity", f"event/{item.node_id}")

        # relations 端点校验
        for item in payloads["relations"]:
            definition = RELATION_DEFINITIONS[str(item.relation_type)]
            record_label = f"relation/{item.from_entity}-{item.to_entity}/{item.relation_type}"
            check_entity(item.from_entity, definition["from_types"], "relation.from_entity", record_label)
            check_entity(item.to_entity, definition["to_types"], "relation.to_entity", record_label)

        if errors:
            raise ValueError("端点校验失败: " + "；".join(errors))
