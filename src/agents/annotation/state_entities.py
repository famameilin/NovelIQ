"""实体关系的局部绑定与输入状态；不持有队列、模型会话或保存事务"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import BoundRelationInput, EntityDirectoryInput, EntityInput, EntityNameRef
from src.fact_graph.outputs import BoundCharacterObservation
from src.fact_graph.vocabulary import RELATION_DEFINITIONS, DialogueVerdict, EntityType, RelationType

from .entity_refs import ensure_entity_ref
from .errors import (
    AnnotationInvariantError,
    AnnotationStageRejection,
)
from .tools import _norm_entity_key
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
    written_relations: dict[tuple[str, str], BoundRelationInput] = field(default_factory=dict)
    entity_el_index: dict[str, str] = field(default_factory=dict)
    domain_payloads: dict[str, Any] = field(default_factory=dict)
    bound_payloads: dict[str, Any] = field(default_factory=dict)

    def apply_entity(
        self, ctx: EntityRelationStateContext, entity: EntityInput, *, el: str, present: set[str] | None = None
    ) -> str:
        """用于登记或更新一个实体、绑定 el 局部键并即时返回 run 级 id（同键同内容重放幂等）

        身份=规范名+实体大类：同名不同类各自登记为独立实体、各自 el 与 id。
        present（本次实际提交的字段集合）给定时按部分更新合并：未提交字段保留现值，
        兑现 write_entity 合同"只提交本次变化的字段"；不传=整条记录语义（直连调用）。
        """
        if ctx.graph is None:
            raise AnnotationInvariantError("write_entity 需要常驻事实图，graph 缺失")
        key = ctx.graph.entity_key(entity.name, entity.entity_type)
        record = f"entity/{entity.name}"
        ctx._require_writable(record)
        normalized_el = unicodedata.normalize("NFC", el).strip()
        bound_key = self.entity_el_index.get(normalized_el)
        if bound_key is not None and bound_key != key:
            raise AnnotationStageRejection(
                f"el 键已被另一实体占用: {normalized_el}",
                record=record,
                field="el",
                code="duplicate_el",
                expected="换一个 el 键（el 在 章内一对一绑定实体）",
            )
        incoming = entity
        existing = self.written_entities.get(key)
        if existing is not None and present is not None:
            # 部分更新：先合并成生效记录，再落图（闸门看到的永远是完整记录）
            entity = self._merge_partial_entity(existing, entity, present)
            key = ctx.graph.entity_key(entity.name, entity.entity_type)
            record = f"entity/{entity.name}"
        if existing is None or existing != entity:
            # 同键不同内容=更新语义；同键同内容直接跳过，避免重复操作日志
            ctx.graph.register_entities([incoming], present=present)
            ctx.graph.record_entity_ops([incoming], chapter_id=ctx.current_chapter_id, present=present)
            self.written_entities[key] = entity
            self._rebuild_entity_payload()
        self.entity_el_index[normalized_el] = key
        entity_id = ctx.graph.entity_id_for_key(key)
        if entity_id is None:
            raise AnnotationInvariantError(f"实体 id 登记失败: {entity.name}")
        return entity_id

    @staticmethod
    def _merge_partial_entity(existing: EntityInput, incoming: EntityInput, present: set[str]) -> EntityInput:
        """用于已登记实体的部分更新合并（兑现"只提交本次变化的字段"合同）

        未提交字段保留现值；tags 提交空列表=清空、省略=保留；
        description 与 representative 省略=保留现值。
        """
        updates: dict[str, Any] = {}
        if "tags" in present:
            updates["tags"] = incoming.tags
        if "description" in present:
            updates["description"] = incoming.description
        if "representative" in present:
            updates["representative"] = incoming.representative
        return existing.model_copy(update=updates)

    def _rebuild_entity_payload(self) -> None:
        """用于按写入顺序重建当前章 的实体目录载荷"""
        self.domain_payloads["entities"] = EntityDirectoryInput(entities=list(self.written_entities.values()))

    def apply_relation(
        self,
        ctx: EntityRelationStateContext,
        *,
        from_ref: EntityNameRef | dict[str, Any],
        to_ref: EntityNameRef | dict[str, Any],
        relation_type: RelationType,
    ) -> tuple[str, str, dict[str, Any]]:
        """用于写入一条本章确认存在的闭合关系边（同一对端点换类型即整体替换）

        返回 (记录键, 本条边的入图结果, 本次写入内容)：assert=新边入图 /
        skipped_existing=已在图上 /
        skipped_self_loop=两端解析到同一实体且非"同一人物"语义（不入图）。
        """
        # Agent 工具边界经 JSON 展开模型，仍只按当前名字合同恢复类型
        from_ref = EntityNameRef.model_validate(from_ref)
        to_ref = EntityNameRef.model_validate(to_ref)
        provisional = f"relation/{from_ref.name}-{to_ref.name}/{relation_type}"
        ctx._require_writable(provisional)
        if ctx.graph is None:
            raise AnnotationInvariantError("write_relation 需要常驻事实图，graph 缺失")
        from_key = ensure_entity_ref(ctx.graph, from_ref.name, from_ref.entity_type, chapter_id=ctx.current_chapter_id)
        to_key = ensure_entity_ref(ctx.graph, to_ref.name, to_ref.entity_type, chapter_id=ctx.current_chapter_id)
        from_name = ctx.graph.display_name(from_key)
        to_name = ctx.graph.display_name(to_key)
        record = f"relation/{from_name}-{to_name}/{relation_type}"
        definition = RELATION_DEFINITIONS[str(relation_type)]
        entity_types = self._fact_entity_catalog(ctx)
        for field_name, key, expected_types in (
            ("from_entity", from_key, definition["from_types"]),
            ("to_entity", to_key, definition["to_types"]),
        ):
            try:
                self._require_entity(
                    ctx,
                    key,
                    entity_types=entity_types,
                    expected_types=expected_types,
                    label=f"write_relation.{field_name}",
                )
            except ValueError as exc:
                raise AnnotationStageRejection(
                    f"{record}({field_name}={ctx.graph.display_name(key)!r})：{exc}",
                    record=record,
                    field=field_name,
                    code="endpoint_invalid",
                    expected=f"端点类型必须属于 {list(expected_types)}",
                ) from None
        try:
            item = BoundRelationInput(
                from_entity=from_key,
                to_entity=to_key,
                relation_type=relation_type,
            )
        except ValidationError as exc:
            raise _translate_record_validation(record, exc, tool_name="write_relation") from None
        self.written_relations[(item.from_entity, item.to_entity)] = item
        outcomes = self._flush_relations(ctx)
        resolution = (ctx.graph.resolve_key(item.from_entity), ctx.graph.resolve_key(item.to_entity))
        outcome = next(
            (
                entry["outcome"]
                for entry in outcomes
                if (entry["from"], entry["to"]) == resolution and entry["relation_type"] == str(item.relation_type)
            ),
            "assert",
        )
        return record, outcome, self._relation_content(ctx, item)

    @staticmethod
    def _relation_content(ctx: EntityRelationStateContext, item: BoundRelationInput) -> dict[str, Any]:
        """用于把内部身份键关系翻成模型可读回执（端点显示登记名）"""
        dumped = item.model_dump(mode="json")
        if ctx.graph is not None:
            dumped["from_entity"] = ctx.graph.display_name(str(item.from_entity))
            dumped["to_entity"] = ctx.graph.display_name(str(item.to_entity))
        return dumped

    def _flush_relations(self, ctx: EntityRelationStateContext) -> list[dict[str, Any]]:
        """用于把本章关系完整集合重放到事实图（先清空本章 assert 再按序重放）

        同一对端点重写换类型即为整体替换：重放保证图终态与本章关系集合同源。
        """
        if ctx.graph is None:
            raise AnnotationInvariantError("write_relation 需要常驻事实图，graph 缺失")
        ctx.graph.reset_chapter_relations()
        outcomes: list[dict[str, Any]] = []
        resolved_items: list[BoundRelationInput] = []
        for item in self.written_relations.values():
            resolved_from = ctx.graph.resolve_key(item.from_entity)
            resolved_to = ctx.graph.resolve_key(item.to_entity)
            if resolved_from == resolved_to:
                # 两端解析到同一实体一律跳过不入图（自环违反 graph_relations 端点互异约束）：
                # "同一人物"边记 skipped_existing，普通关系塌成自环记 skipped_self_loop
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
            resolved_item = BoundRelationInput(**dumped)
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
        stored = self.written_entities.get(_norm_entity_key(entity.name, entity.entity_type), entity)
        content = stored.model_dump(mode="json")
        content["id"] = (
            ctx.graph.entity_id_for_key(_norm_entity_key(stored.name, stored.entity_type))
            if ctx.graph is not None
            else None
        )
        return content

    def entity_ledger(self, ctx: EntityRelationStateContext) -> list[dict[str, Any]]:
        """用于列举本章已写入实体的账本（el 绑定序）：{el, name, id, entity_type}，带 tags 与同一人物别名

        别名列（alias）与标签列用于防止"外号没接上登记名→重复注册实体"。
        账本行带 entity_type：大类一经登记不可变更，模型不必凭记忆重写。
        """
        rows: list[dict[str, Any]] = []
        for el, key in self.entity_el_index.items():
            stored = self.written_entities.get(key)
            if stored is None:
                continue
            row: dict[str, Any] = {
                "el": el,
                "name": stored.name,
                "id": ctx.graph.entity_id_for_key(key) if ctx.graph is not None else None,
                "entity_type": str(stored.entity_type),
            }
            if stored.tags:
                row["tags"] = list(stored.tags)
            if ctx.graph is not None:
                aliases = ctx.graph.alias_group(key)
                if aliases:
                    row["aliases"] = aliases
            rows.append(row)
        return rows

    def _entity_catalog(
        self,
        directory: EntityDirectoryInput,
    ) -> tuple[dict[str, EntityType], dict[str, str]]:
        """用于建立当前章唯一实体身份目录（键=规范名+实体大类复合键）"""
        types: dict[str, EntityType] = {}
        names: dict[str, str] = {}
        for entity in directory.entities:
            normalized = unicodedata.normalize("NFC", entity.name).strip()
            key = _norm_entity_key(entity.name, entity.entity_type)
            if key in types:
                raise ValueError(f"本章 实体名称重复: {normalized}")
            types[key] = entity.entity_type
            names[key] = normalized
        return types, names

    def _fact_entity_catalog(self, ctx: EntityRelationStateContext) -> dict[str, EntityType]:
        """用于合并内存图已登记实体与当前章 已声明实体作为事实端点目录"""
        catalog = dict(ctx.graph.entity_types) if ctx.graph is not None else {}
        entities_payload = self.domain_payloads.get("entities")
        if entities_payload is not None:
            types, _names = self._entity_catalog(entities_payload)
            catalog.update(types)
        return catalog

    def _require_entity(
        self,
        ctx: EntityRelationStateContext,
        key: str,
        *,
        entity_types: dict[str, EntityType],
        expected_types: tuple[EntityType, ...] | None = None,
        label: str,
    ) -> str:
        """用于校验事实端点已由当前章 实体目录或已登记实体声明（别名解析后）"""
        resolved_key = ctx.graph.resolve_key(key) if ctx.graph is not None else key
        actual_type = entity_types.get(resolved_key) or entity_types.get(key)
        name = ctx.graph.display_name(key) if ctx.graph is not None else key
        if actual_type is None:
            raise ValueError(f"{label} 未在当前章 登记: {name}（请先用 write_entity 登记该实体，或改用已登记实体名）")
        if expected_types is not None and actual_type not in expected_types:
            raise ValueError(
                f"{label} 端点类型必须属于 {[str(t) for t in expected_types]}，实际为 {actual_type}"
                f"（{name} 在图上的登记类型是 {actual_type}，"
                "请改用端点所需类型的已登记实体）"
            )
        return resolved_key

    def fact_views(self, ctx: EntityRelationStateContext) -> dict[str, Any]:
        """只返回实体与关系事实，供账本组装审计摘要（端点显示登记名）"""
        payloads = self.domain_payloads
        views: dict[str, Any] = {}
        if "entities" in payloads:
            views["entities"] = {
                "items": len(payloads["entities"].entities),
                "names": [entity.name for entity in payloads["entities"].entities],
            }
        if "relations" in payloads:
            graph = ctx.graph
            views["relations"] = [
                {
                    "from": graph.display_name(item.from_entity) if graph is not None else item.from_entity,
                    "to": graph.display_name(item.to_entity) if graph is not None else item.to_entity,
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

        # 错误点名生产记录键（不只报"[下标] 域.字段"，模型要能映射回具体记录）
        errors: list[str] = []

        def check_entity(
            key: str,
            expected_types: tuple[EntityType, ...] | None,
            label: str,
            record_label: str,
        ) -> None:
            resolved_key = ctx.graph.resolve_key(key) if ctx.graph is not None else key
            actual_type = resolved_entity_types.get(resolved_key) or resolved_entity_types.get(key)
            name = ctx.graph.display_name(key) if ctx.graph is not None and key in ctx.graph.entity_names else key
            if actual_type is None:
                errors.append(
                    f"{record_label} {label} 未在当前章 登记: {name}"
                    "（请先用 write_entity 登记该实体，或改用已登记实体名）"
                )
                return
            if expected_types is not None and actual_type not in expected_types:
                errors.append(
                    f"{record_label} {label}={name!r} 端点类型必须属于 {[str(t) for t in expected_types]}，"
                    f"实际为 {actual_type}（{name} 在图上的登记类型是 {actual_type}，"
                    "请改用端点所需类型的已登记实体）"
                )

        # character_observations 端点校验（载荷顺序与 observation_by_record 一致，可反查记录键）
        observation_keys = list(observation_records)
        for index, item in enumerate(payloads["character_observations"]):
            record_label = str(observation_keys[index]) if index < len(observation_keys) else str(index)
            check_entity(
                _norm_entity_key(item.character, EntityType.CHARACTER.value),
                (EntityType.CHARACTER,),
                "character_observation.character",
                record_label,
            )

        # dialogues 端点校验
        for item in payloads["dialogues"]:
            if item.verdict != DialogueVerdict.NOT_DIALOGUE and item.speaker is not None:
                check_entity(
                    _norm_entity_key(item.speaker, EntityType.CHARACTER.value),
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
