"""连续性领域写边界：只接受已存在、同 run 的稳定目标"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.annotation.fact_graph import mention_uuid
from src.agents.annotation.identity import stable_digest, stable_uuid
from src.agents.annotation.schema import RELATION_DEFINITIONS, AgentRunResult, PendingCase, Tone
from src.storage.models import ChapterAnnotationRecord, ContinuityCase, DialogueRecord, EventNode, GraphEntity
from src.storage.repositories.event_order import event_position, formal_event_ordinals
from src.storage.repositories.pipeline_cases import cutoff_assertions


class ResolutionInput(BaseModel):
    """字段组互斥，防止一个案例无意订正多个无关资源"""

    model_config = ConfigDict(extra="forbid")
    conclusion: str | None = Field(default=None, min_length=1, max_length=2000)
    speaker_entity_id: str | None = None
    tone: Tone | None = None
    from_entity_id: str | None = None
    to_entity_id: str | None = None
    relation_type: str | None = None
    change_kind: Literal["assert", "reinforce", "weaken", "refine", "break", "supersede", "retract"] | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    event_id: str | None = None
    root_event_id: str | None = None
    edge_type: Literal["foreshadowing", "causal"] = "foreshadowing"
    entity_id: str | None = None
    canonical_entity_id: str | None = None
    identity_kind: Literal["same", "different", "independent", "type_conflict"] | None = None
    entity_type: Literal["character", "location", "item", "organization"] | None = None
    selected_command_id: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_group(self) -> ResolutionInput:
        groups = [self.speaker_entity_id is not None or self.tone is not None,
                  any(value is not None for value in (self.from_entity_id, self.to_entity_id,
                                                     self.relation_type, self.change_kind)),
                  self.event_id is not None or self.root_event_id is not None,
                  any(value is not None for value in (self.entity_id, self.canonical_entity_id,
                                                     self.identity_kind, self.entity_type, self.selected_command_id))]
        if sum(groups) > 1 or (not any(groups) and self.conclusion is None):
            raise ValueError("resolution 必须是一个明确的领域订正或非空 conclusion")
        if groups[1] and not all((self.from_entity_id, self.to_entity_id, self.relation_type, self.change_kind)):
            raise ValueError("关系订正必须包含两端、relation_type 与 change_kind")
        if groups[2] and not all((self.event_id, self.root_event_id)):
            raise ValueError("事件订正必须包含 event_id 与 root_event_id")
        if self.attributes and not groups[1]:
            raise ValueError("attributes 只能用于关系订正")
        if "edge_type" in self.model_fields_set and not groups[2]:
            raise ValueError("edge_type 只能用于事件订正")
        if groups[3]:
            if self.selected_command_id is not None:
                if not self.entity_id or any((self.identity_kind, self.canonical_entity_id, self.entity_type)):
                    raise ValueError("身份冲突裁决只能填 entity_id 和 selected_command_id")
                return self
            if not self.entity_id or not self.identity_kind:
                raise ValueError("身份订正必须包含 entity_id 与 identity_kind")
            if self.identity_kind == "type_conflict":
                if self.entity_type is None or self.canonical_entity_id is not None:
                    raise ValueError("类型仲裁只允许选择 entity_type，不绑定另一个实体")
            elif not self.canonical_entity_id or self.entity_type is not None:
                raise ValueError("同一/不同身份必须包含 canonical_entity_id，不改实体类型")
        return self


def bind_record_target(record: str, result: AgentRunResult) -> dict[str, Any]:
    """把本章真实写回执转换为稳定对象，不从实体名称猜测另一章的对象"""
    if record.startswith("entity/"):
        name = record.removeprefix("entity/")
        if not any(item["name"] == name for item in result.entity_ops):
            raise ValueError("原文锚点的实体不是本章正式产出")
        return {"domain": "entity", "entity_id": mention_uuid(result.run_id, result.chapter_id, name)}
    if record.startswith("relation/"):
        relation = next((item for item in result.relation_assert_ops if record ==
                         f"relation/{item['from_entity']}-{item['to_entity']}/{item['relation_type']}"), None)
        if relation is None:
            raise ValueError("原文锚点的关系不是本章正式产出")
        return {"domain": "relation", "relation_type": relation["relation_type"],
                "from_entity_id": mention_uuid(result.run_id, result.chapter_id, relation["from_entity"]),
                "to_entity_id": mention_uuid(result.run_id, result.chapter_id, relation["to_entity"])}
    if record.startswith("dialogue/"):
        candidate = record.removeprefix("dialogue/")
        dialogue = next((item for item in result.annotation.dialogues
                         if candidate in {item.candidate_key, str(item.candidate_index)}), None)
        if dialogue is None:
            # 2026-10-03 候选被判 not_dialogue（含收尾兜底）时从正式产出合法消失：
            # 案例保留原锚点但不做对话域绑定，不再整章炸沉
            return {}
        return {"domain": "dialogue", "candidate_key": dialogue.candidate_key}
    tree_key, _, node_key = record.partition("/")
    event_id = stable_uuid(result.run_id, result.chapter_id, "event_node", tree_key, node_key or "root")
    if not any(item.node_id == event_id for item in result.annotation.events):
        raise ValueError("原文锚点的事件不是本章正式产出")
    return {"domain": "event", "event_id": event_id}


def bind_case_target(seed: PendingCase, result: AgentRunResult) -> dict[str, Any]:
    """将章内写回执绑定为服务端目标，模型不能凭检索关键词更换订正对象"""
    target = dict(seed.target_ref)
    record = str(target.get("record_id") or "")
    if record:
        target.update(bind_record_target(record, result))
        return target
    if record.startswith("dialogue/") or target.get("candidate_key"):
        candidate = str(target.get("candidate_key") or record.removeprefix("dialogue/"))
        dialogue = next((item for item in result.annotation.dialogues
                         if candidate in {item.candidate_key, str(item.candidate_index)}), None)
        if dialogue is None:
            raise ValueError("案例对话目标不是本章正式产出")
        target.update(domain="dialogue", candidate_key=dialogue.candidate_key)
    elif record.startswith("relation/"):
        relation = next((item for item in result.relation_assert_ops if record ==
                         f"relation/{item['from_entity']}-{item['to_entity']}/{item['relation_type']}"), None)
        if relation is None:
            raise ValueError("案例关系目标不是本章正式产出")
        target.update(domain="relation", relation_type=relation["relation_type"],
                      from_entity_id=mention_uuid(result.run_id, result.chapter_id, relation["from_entity"]),
                      to_entity_id=mention_uuid(result.run_id, result.chapter_id, relation["to_entity"]))
    elif record.startswith("entity/"):
        name = record.removeprefix("entity/")
        if not any(item["name"] == name for item in result.entity_ops):
            raise ValueError("案例实体目标不是本章正式产出")
        target.update(domain="entity", entity_id=mention_uuid(result.run_id, result.chapter_id, name))
    elif target.get("event_id") or (record and "/" in record):
        tree_key, _, node_key = record.partition("/")
        event_id = str(target.get("event_id") or stable_uuid(
            result.run_id, result.chapter_id, "event_node", tree_key, node_key,
        ))
        if not any(item.node_id == event_id for item in result.annotation.events):
            raise ValueError("案例事件目标不是本章正式产出")
        target.update(domain="event", event_id=event_id)
    return target


def validate_resolution(
    session: Session, case: ContinuityCase, resolution: dict[str, Any],
    *, cutoff_hash: str | None = None,
) -> tuple[dict[str, Any], tuple[str, str, dict[str, Any]] | None]:
    """返回规范化主张与确定性子命令，不修改正式对象"""
    if "items" in resolution:
        if set(resolution) != {"items"} or not isinstance(resolution["items"], list) or not resolution["items"]:
            raise ValueError("批量结论必须是非空 items 列表")
        if len(resolution["items"]) > 100 or any("items" in item for item in resolution["items"]):
            raise ValueError("批量结论不能嵌套且最多 100 条")
        validated = [validate_resolution(session, case, item, cutoff_hash=cutoff_hash) for item in resolution["items"]]
        normalized_items = {stable_digest(value): value for value, _command in validated}
        normalized_batch = {"items": [normalized_items[key] for key in sorted(normalized_items)]}
        commands = [list(command) for _value, command in validated if command is not None]
        return normalized_batch, ("batch", "", {"commands": commands})
    value = ResolutionInput.model_validate(resolution)
    normalized = value.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    if value.entity_id is not None:
        if case.target_ref.get("domain") != "entity" or value.entity_id != case.target_ref.get("entity_id"):
            raise ValueError("身份订正必须绑定案例的确切实体目标")
        if cutoff_hash is None:
            raise ValueError("身份订正必须声明固定 cutoff")
        assertions = cutoff_assertions(session, cutoff_hash, case.run_id)
        mentions: dict[str, list[dict[str, Any]]] = {}
        selected_types: dict[str, set[str]] = {}
        for assertion in assertions:
            if assertion["kind"] == "entity_mention":
                mentions.setdefault(assertion["payload"]["entity_id"], []).append(assertion["payload"])
            elif assertion["kind"] == "entity_type_resolution" and assertion["outcome"] == "accepted":
                selected_types.setdefault(assertion["payload"]["entity_id"], set()).add(
                    assertion["payload"]["entity_type"],
                )
        source_mentions = mentions.get(value.entity_id)
        if not source_mentions:
            raise ValueError("身份目标不属于固定 cutoff")
        if value.selected_command_id is not None:
            partition = f"alias:{value.entity_id}"
            if case.target_ref.get("partition_key") != partition:
                raise ValueError("只有指定别名冲突案例可以裁决已有绑定")
            selected = next((assertion for assertion in assertions
                             if assertion["kind"] == "identity_binding"
                             and value.selected_command_id in assertion["command_ids"]), None)
            if selected is None or selected["payload"]["entity_id"] != value.entity_id:
                raise ValueError("所选身份主张不属于本案例固定 cutoff")
            return normalized, ("identity_arbitration", partition, normalized)
        if value.identity_kind == "type_conflict":
            if value.entity_type not in {item["entity_type"] for item in source_mentions}:
                raise ValueError("类型仲裁只能选择正式 mention 已提出的类型")
            payload = {**normalized, "name": source_mentions[0]["name"]}
            return normalized, ("entity_type_resolution",
                                f"entity:{value.entity_id}",
                                payload)
        destination = mentions.get(str(value.canonical_entity_id))
        if destination is None or (
            value.canonical_entity_id == value.entity_id and value.identity_kind != "independent"
        ):
            raise ValueError("身份端点必须是固定 cutoff 的两个不同实体")
        if value.identity_kind == "independent" and value.canonical_entity_id != value.entity_id:
            raise ValueError("独立身份必须指向自身")
        source_types = selected_types.get(value.entity_id, {item["entity_type"] for item in source_mentions})
        target_types = selected_types.get(str(value.canonical_entity_id), {item["entity_type"] for item in destination})
        if value.identity_kind == "same" and (len(source_types) != 1 or source_types != target_types):
            raise ValueError("类型不同不能直接绑定为同一实体，需先仲裁类型")
        payload = {**normalized, "entity_name": source_mentions[0]["name"], "canonical_name": destination[0]["name"]}
        return normalized, ("identity_binding", f"alias:{value.entity_id}", payload)
    candidate_key = case.target_ref.get("candidate_key")
    if value.speaker_entity_id is not None or value.tone is not None:
        if case.target_ref.get("domain") != "dialogue":
            raise ValueError("说话人订正需要绑定对话目标的案例")
        dialogue = session.execute(select(DialogueRecord).where(
            DialogueRecord.run_id == case.run_id, DialogueRecord.candidate_key == candidate_key,
            DialogueRecord.chapter_id == case.originating_chapter_id,
        )).scalar_one_or_none()
        if dialogue is None:
            raise ValueError("说话人订正只能指向案例绑定的正式对话")
        if value.speaker_entity_id is not None:
            entity = session.get(GraphEntity, value.speaker_entity_id)
            if entity is None or entity.run_id != case.run_id or entity.entity_type != "character":
                raise ValueError("说话人必须是本 run 已知人物")
        payload = {"candidate_key": dialogue.candidate_key, "dialogue_id": dialogue.dialogue_id,
                   **normalized}
        return normalized, ("dialogue_attribution", f"dialogue:{dialogue.candidate_key}", payload)
    if value.from_entity_id is not None:
        if (case.target_ref.get("domain") != "relation"
                or value.from_entity_id != case.target_ref.get("from_entity_id")
                or value.to_entity_id != case.target_ref.get("to_entity_id")
                or value.relation_type != case.target_ref.get("relation_type")):
            raise ValueError("关系订正不能更换案例绑定的端点或类型")
        endpoints = [session.get(GraphEntity, entity_id) for entity_id in
                     (value.from_entity_id, value.to_entity_id)]
        if any(entity is None or entity.run_id != case.run_id for entity in endpoints):
            raise ValueError("关系端点必须属于本 run")
        if value.relation_type not in RELATION_DEFINITIONS:
            raise ValueError("关系类型不属于项目词表")
        names = [str(entity.canonical_name) for entity in endpoints if entity is not None]
        definition = RELATION_DEFINITIONS[value.relation_type]
        entity_types = [str(entity.entity_type) for entity in endpoints if entity is not None]
        allowed_from = definition["from_types"]
        allowed_to = definition["to_types"]
        if ((allowed_from and entity_types[0] not in allowed_from)
                or (allowed_to and entity_types[1] not in allowed_to)):
            raise ValueError("关系端点类型不符合词表")
        payload = {**normalized, "from_entity": names[0], "to_entity": names[1]}
        key = stable_digest(value.from_entity_id, value.to_entity_id, value.relation_type, fold_text=True)
        return normalized, ("relation_change", f"relation:{key}", payload)
    if value.event_id is not None:
        if (case.target_ref.get("domain") != "event"
                or case.target_ref.get("event_id") not in {value.event_id, value.root_event_id}):
            raise ValueError("事件订正必须包含案例绑定的确切正式事件")
        target = session.get(EventNode, value.event_id)
        source = session.get(EventNode, value.root_event_id)
        if (target is None or source is None or target.run_id != case.run_id or source.run_id != case.run_id
                or target.event_id == source.event_id):
            raise ValueError("事件端点必须是本 run 两个不同的正式事件")
        if target.chapter_id != case.originating_chapter_id and source.chapter_id != case.originating_chapter_id:
            raise ValueError("事件订正必须涉及案例来源章节")
        annotations = session.execute(select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.annotation_id.in_({source.annotation_id, target.annotation_id}),
        )).scalars()
        ordinals = formal_event_ordinals(annotations)
        if event_position(source, ordinals) >= event_position(target, ordinals):
            raise ValueError("事件依赖必须遵循文档严格偏序")
        if value.edge_type == "foreshadowing" and not source.is_foreshadowing_root:
            raise ValueError("root_event_id 必须是正式伏笔根")
        return normalized, ("event_link", f"cause:{source.event_id}:{target.event_id}", normalized)
    return normalized, None
