"""事件节点绑定、暂挂子节点与参与者状态；不持有队列、模型会话或保存事务"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

from pydantic import ValidationError

from src.agents.annotation.event_inputs import ParticipantArg
from src.agents.annotation.output_models import BoundCharacterObservation
from src.event_trees.models import BoundEvent, EventParticipantInput
from src.event_trees.vocabulary import (
    Confidence,
    EventParticipantRole,
)
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import ChapterParagraphInfo
from src.fact_graph.vocabulary import EntityType
from src.storage import new_id

from .entity_refs import ensure_entity_ref
from .errors import (
    AnnotationInvariantError,
    AnnotationStageRejection,
)
from .ir_contract import ROLE_NAMESPACE_SEP
from .validation_errors import _translate_record_validation


def _validate_el(el: str, *, record: str) -> None:
    """用于校验事件引用 id：非空、不含斜杠，整串只作引用不表示层级"""
    expected = "本执行内你自定的引用 id（如 e1、e2）；不写斜杠、不写 root、不表示父子层级"
    if not el:
        raise AnnotationStageRejection(
            "事件 el 不能为空",
            record=record,
            field="el",
            code="bad_el",
            expected=expected,
        )
    if "/" in el:
        raise AnnotationStageRejection(
            f"事件 el 只作引用 id：{el}",
            record=record,
            field="el",
            code="bad_el",
            expected=expected,
        )


class EventBindingStateContext(Protocol):
    """只开放此工作状态需要的上下文和引用能力"""

    def _require_writable(self, record: str) -> None: ...
    def require_domain(self, domain: str) -> None: ...
    def _visible_global_pairs(self) -> list[tuple[int, int]]: ...

    role: str
    current_chapter_id: int
    current_chapter_order: int | None
    graph: FactGraph | None
    paragraph_info: ChapterParagraphInfo | None

    def resolve_entity_ref(self, ref: str, *, record: str, field: str) -> str: ...

    run_scope: str
    work_id: str

    # 事件树重做：work 开始时从本 run 已确认（confirm）状态装载的索引，
    # 跨章引用只接受这里的已确认身份，不接受迟到 invocation 或未确认内容
    text_references: dict[str, Any]
    confirmed_complete_event_index: dict[str, dict[str, Any]]
    confirmed_source_event_ids: set[str]


@dataclass(slots=True)
class EventBindingState:
    identifiers: dict[tuple, str] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def _identifier(self, *key) -> str:
        """同一局部键复用已分配的 UUIDv7，身份不是局部键的编码"""
        if key not in self.identifiers:
            self.identifiers[key] = new_id()
        return self.identifiers[key]

    authorized_event_ids: set[str] = field(default_factory=set)
    event_ids_by_el: dict[str, str] = field(default_factory=dict)
    observation_by_record: dict[str, BoundCharacterObservation] = field(default_factory=dict)
    domain_payloads: dict[str, Any] = field(default_factory=dict)
    bound_payloads: dict[str, Any] = field(default_factory=dict)
    # 完整事件域：EventNode 继续保存过程，下列对象是完整事件及其关联的
    # 本 work 挂起记录（局部键 → 事件；随正式贡献冻结、保存、确认与回滚）
    complete_events: dict[str, dict[str, Any]] = field(default_factory=dict)
    queue_references: dict[str, dict[str, Any]] = field(default_factory=dict)
    queues: dict[str, dict[str, Any]] = field(default_factory=dict)
    ownerships: dict[str, dict[str, Any]] = field(default_factory=dict)
    relations: list[dict[str, Any]] = field(default_factory=list)

    def _node_id(self, ctx: EventBindingStateContext, el: str) -> str:
        """事件身份绑定本执行引用 id，重投递得到同一 id"""
        return self._identifier(ctx.run_scope, ctx.work_id or ctx.current_chapter_id, "event_node", el)

    def _bound_event(self, node_id: str) -> BoundEvent:
        """用于在已落账事件里按节点 id 取节点对象（参与者挂在它上面）"""
        for event in self.bound_payloads.get("events") or []:
            if event.node_id == node_id:
                return event
        raise AnnotationInvariantError(f"事件节点未落账: {node_id}")

    def local_el_of(self, node_id: str) -> str | None:
        """用于按事件 id 反查本账本的引用 id（去掉角色命名空间前缀）"""
        for el, identifier in self.event_ids_by_el.items():
            if identifier == node_id:
                return el.split(ROLE_NAMESPACE_SEP, 1)[-1]
        return None

    def local_els(self) -> list[str]:
        "本执行已写事件的引用 id"
        return sorted(el.split(ROLE_NAMESPACE_SEP, 1)[-1] for el in self.event_ids_by_el)

    def apply_event(
        self,
        ctx: EventBindingStateContext,
        *,
        el: str,
        title: str,
        problem: str,
        summary: str,
        event_type: str,
        status: str,
        evidence: int | None = None,
        progress: str | None = None,
        from_chapter_id: int | None = None,
        to_chapter_id: int | None = None,
        reason: str | None = None,
        isforeshadowing: bool = False,
        confidence: Confidence | None = None,
        characters: list[ParticipantArg] | None = None,
    ) -> str:
        """登记不可变事件及独立章节范围，局部路径不生成包含关系"""
        self.warnings.clear()
        cleaned = unicodedata.normalize("NFC", el).strip()
        record = self._event_record(cleaned)
        ctx._require_writable(record)
        ctx.require_domain("event")
        _validate_el(cleaned, record=record)
        event_id = self._node_id(ctx, cleaned)
        existing = next((item for item in self.bound_payloads.get("events", []) if item.node_id == event_id), None)
        paragraph_id = self._event_evidence_paragraph_id(ctx, evidence, record=record, existing=existing)
        if isforeshadowing and confidence is None:
            raise AnnotationStageRejection(
                "isforeshadowing=true 时必须提供 confidence",
                record=record,
                field="confidence",
                code="missing",
                expected="high / medium / low",
            )
        if not isforeshadowing and confidence is not None:
            raise AnnotationStageRejection(
                "isforeshadowing=false 时不能提供 confidence",
                record=record,
                field="confidence",
                code="invalid_combination",
                expected="非伏笔事件不填 confidence；伏笔根须 isforeshadowing=true 且给 confidence",
            )
        annotation_event = BoundEvent(
            node_id=event_id,
            event_id=event_id,
            from_chapter_id=ctx.current_chapter_id if from_chapter_id is None else from_chapter_id,
            to_chapter_id=ctx.current_chapter_id if to_chapter_id is None else to_chapter_id,
            reason=reason,
            title=title,
            problem=problem,
            summary=summary,
            event_type=event_type,
            status=cast(Literal["ongoing", "resolved"], status),
            progress=progress,
            description=summary,
            tree_id=None,
            parent_node_id=None,
            cause_role="root",
            evidence_paragraph_id=paragraph_id,
            participants=list(existing.participants) if existing is not None else [],
            is_foreshadow_setup=isforeshadowing,
            payoff_likelihood=confidence,
        )
        if existing is not None:
            if existing.model_dump(exclude={"participants"}) != annotation_event.model_dump(exclude={"participants"}):
                raise AnnotationStageRejection(
                    f"event_id={event_id} 事件内容不可改写",
                    record=record,
                    field="summary",
                    code="immutable",
                    expected="复用已接受事件及其原始字段，不覆盖来源",
                )
        else:
            events = list(self.bound_payloads.get("events", []))
            for other in events:
                if other.evidence_paragraph_id == paragraph_id and other.summary == summary:
                    location = self.local_el_of(other.node_id) or other.event_id
                    raise AnnotationStageRejection(
                        f"事件与 {other.event_id} 同源重复",
                        record=record,
                        field="summary",
                        code="duplicate_annotation_event",
                        expected=(
                            f"该事实已写在 {location}；继续追加新节点请沿用该树键，"
                            "要改写先 retract_structure 撤回该队列"
                        ),
                    )
            events.append(annotation_event)
            self.bound_payloads["events"] = events
            self.domain_payloads["events"] = events
        self.event_ids_by_el[cleaned] = event_id
        self.authorized_event_ids.add(event_id)
        if characters is not None:
            self._apply_participants(ctx, node_record=record, node_id=event_id, characters=characters)
        return record

    def _event_record(self, el: str) -> str:
        """事件记录键就是本执行引用 id"""
        return unicodedata.normalize("NFC", el).strip()

    def _event_evidence_paragraph_id(
        self, ctx: EventBindingStateContext, evidence: int | None, *, record: str, existing: BoundEvent | None = None
    ) -> int | None:
        """将段首可见号绑定到本章段落；重写未给证据时保留原锚点。"""
        if evidence is None and existing is not None and existing.evidence_paragraph_id is not None:
            return existing.evidence_paragraph_id
        if ctx.paragraph_info is None:
            return None
        visible_to_global = dict(ctx._visible_global_pairs())
        if evidence is None and len(visible_to_global) == 1:
            return next(iter(visible_to_global.values()))
        if evidence is None:
            raise AnnotationStageRejection(
                "事件缺少所在段证据",
                record=record,
                field="evidence",
                code="missing_evidence",
                expected="填写本章正文段首的可见号（单个整数）",
            )
        if isinstance(evidence, bool) or not isinstance(evidence, int) or evidence not in visible_to_global:
            preview = ", ".join(str(number) for number in sorted(visible_to_global)[:12])
            raise AnnotationStageRejection(
                f"事件 evidence 不属于本章: {evidence}",
                record=record,
                field="evidence",
                code="out_of_range",
                expected=f"本章可用段首号: {preview}{'…' if len(visible_to_global) > 12 else ''}",
            )
        return visible_to_global[evidence]

    def _apply_participants(
        self,
        ctx: EventBindingStateContext,
        *,
        node_record: str,
        node_id: str,
        characters: list[ParticipantArg],
    ) -> None:
        """用于把 characters 数组整体替换到指定节点的参与者列表

        按登记类型分流：character 三态必填并派生人物动态状态
        （人物榜/Greimas/实体状态注入的唯一数据源），role 缺省按登记类型取默认；
        非 character 不接受三态；同一实体在数组内只允许出现一次；
        旧记录键下的动态状态先清后建（替换语义）。
        """
        if ctx.graph is None:
            raise AnnotationInvariantError("参与者解析需要常驻事实图，graph 缺失")
        event = self._bound_event(node_id)
        for stale in [key for key in self.observation_by_record if key.startswith(f"{node_record}/participant/")]:
            del self.observation_by_record[stale]
        seen: set[str] = set()
        participants: list[EventParticipantInput] = []
        for arg in characters:
            participant_record = f"{node_record}/participant/{arg.name}"
            entity_key = ensure_entity_ref(ctx.graph, arg.name, arg.entity_type, chapter_id=ctx.current_chapter_id)
            entity_name = ctx.graph.display_name(entity_key)
            if entity_key in seen:
                raise AnnotationStageRejection(
                    f"同一实体在 characters 数组内重复出现: {entity_name}",
                    record=participant_record,
                    field="name",
                    code="duplicate_participant",
                    expected="每个实体一次提交只出现一次（本数组即该节点参与者的完整集合）",
                )
            seen.add(entity_key)
            actual_type = ctx.graph.entity_type_by_key(entity_key)
            if actual_type is None:
                raise AnnotationStageRejection(
                    f"参与者实体未登记: {entity_name}",
                    record=participant_record,
                    field="name",
                    code="unregistered",
                    expected="先用 write_entity 登记本章实体",
                )
            # 合同放开：role 可省略，按实体登记类型给缺省
            # （character→主体、location→地点、其余→客体）；显式写错仍拒
            effective_role = arg.role or (
                EventParticipantRole.LOCATION
                if actual_type == EntityType.LOCATION.value
                else EventParticipantRole.SUBJECT
                if actual_type == EntityType.CHARACTER.value
                else EventParticipantRole.OBJECT
            )
            # 口径统一：机构兼指场所按 organization 登记（见 ANNOTATION_SCOPE_POLICY），
            # 故"地点"角色接受 location 与 organization 两类端点，不再要求必须是 location
            if effective_role == EventParticipantRole.LOCATION and actual_type not in {
                EntityType.LOCATION.value,
                EntityType.ORGANIZATION.value,
            }:
                raise AnnotationStageRejection(
                    f"地点角色端点须是 location 或 organization: {entity_name}（登记类型 {actual_type}）",
                    record=participant_record,
                    field="role",
                    code="role_type_mismatch",
                    expected="地点角色用于 location 或 organization 型实体（机构兼场所统一登记 organization）",
                )
            if actual_type == EntityType.CHARACTER.value:
                missing = [
                    name
                    for name, value in (
                        ("narrative_role", arg.narrative_role),
                        ("action", arg.action),
                        ("emotion", arg.emotion),
                    )
                    if value is None
                ]
                if missing:
                    raise AnnotationStageRejection(
                        f"character 参与者必须同时提供 narrative_role/action/emotion，缺失: {', '.join(missing)}",
                        record=participant_record,
                        field=missing[0],
                        code="missing",
                        expected="三字段必填、不自动填默认值",
                    )
                observation_action = cast(str, arg.action)
                self._reject_duplicate_observation(participant_record, entity_name, observation_action)
                self.observation_by_record[participant_record] = BoundCharacterObservation(
                    character=entity_name,
                    role_function=arg.narrative_role,
                    action=observation_action,
                    emotion=arg.emotion,
                )
                narrative_role, action, emotion = arg.narrative_role, arg.action, arg.emotion
            else:
                # 三态只服务人物动态状态，item/organization/location 无消费者；模型常给
                # 非角色实体补动作，硬拒会连带丢掉整组参与者（含同组合法 character 条目）并烧尽回合，
                # 故改为忽略三态、保留名字、大类与 role
                ignored = [
                    name
                    for name, value in (
                        ("narrative_role", arg.narrative_role),
                        ("action", arg.action),
                        ("emotion", arg.emotion),
                    )
                    if value is not None
                ]
                if ignored:
                    self.warnings.append(
                        {
                            "record": participant_record,
                            "field": "characters",
                            "ignored": ignored,
                            "message": f"{entity_name} 不是 character，三态字段不落账",
                        }
                    )
                narrative_role, action, emotion = None, None, None
            try:
                participants.append(
                    EventParticipantInput(
                        entity=entity_key,
                        role=effective_role,
                        narrative_role=narrative_role,
                        action=action,
                        emotion=emotion,
                    )
                )
            except ValidationError as exc:
                raise _translate_record_validation(participant_record, exc, tool_name="write_event") from None
        event.participants = participants
        self._rebuild_observation_payload()

    def _rebuild_observation_payload(self) -> None:
        """用于按写入顺序重建人物动态状态载荷"""
        observations = list(self.observation_by_record.values())
        self.domain_payloads["character_observations"] = observations
        self.bound_payloads["character_observations"] = observations

    def _reject_duplicate_observation(
        self,
        record: str,
        entity_name: str,
        action: str,
    ) -> None:
        """用于挡住同一人物的重复动态状态（人物,动作 在本章 内唯一）

        写入点校验：触发时只拒绝这一条，已写入的记录与其他节点不受影响。
        """
        for other_record, observation in self.observation_by_record.items():
            if other_record == record:
                continue
            if (observation.character, observation.action) != (entity_name, action):
                continue
            raise AnnotationStageRejection(
                f"人物动态状态重复：{other_record}(character={observation.character}, action={observation.action})"
                f" 与 {record}(character={entity_name}, action={action}) 相撞",
                record=record,
                field="action",
                code="duplicate_observation",
                expected="本章非空的 (character, action) 组合唯一",
            )

    # ------------------------------------------------------------------
    # 章级事件只记录候选关系，正式事件身份和结构由诊断发布
    # ------------------------------------------------------------------

    def _resolve_annotation_event_ref(self, ctx: EventBindingStateContext, ref: str, *, record: str, field: str) -> str:
        """把本执行引用 id 或已读取、已保存事件引用解析成 event_id"""
        cleaned = unicodedata.normalize("NFC", str(ref)).strip()
        prefix = f"{ctx.role}{ROLE_NAMESPACE_SEP}"
        namespaced = cleaned if cleaned.startswith(prefix) else f"{prefix}{cleaned}"
        for candidate in (namespaced, cleaned):
            identifier = self.event_ids_by_el.get(candidate)
            if identifier is not None:
                return identifier
        if cleaned in self.authorized_event_ids:
            return cleaned
        if cleaned in ctx.confirmed_source_event_ids:
            return cleaned
        raise AnnotationStageRejection(
            f"事件身份不存在: {ref}",
            record=record,
            field=field,
            code="unknown_annotation_event",
            expected="本 work 已落账事件的局部键或 event_id，或本 run 已确认 event_id",
        )

    def apply_annotation_event_relation(
        self,
        ctx: EventBindingStateContext,
        *,
        source_kind: str,
        source_id: str,
        target_kind: str,
        target_id: str,
        relation_type: str,
        reason: str,
        evidence: int | None = None,
        source_operation_id: str,
    ) -> str:
        """write_link 显式建立事件包含或语义关系"""
        record = f"event_relation/{source_operation_id}"
        ctx._require_writable(record)
        if not relation_type.strip() or not source_operation_id.strip():
            raise AnnotationStageRejection(
                "关系类型和来源操作身份不能为空",
                record=record,
                field="relation_type",
                code="missing",
                actual=relation_type,
                expected="明确的真实关系类型及稳定来源操作身份",
            )
        if not reason.strip():
            raise AnnotationStageRejection(
                "关系或冲突须给出非空原文理由",
                record=record,
                field="reason",
                code="missing",
                actual=reason,
                expected="原文支持的非空理由",
            )
        if source_kind != "event" or target_kind != "event":
            raise ValueError("标注只能提交事件间关系建议")
        resolved_source = self._resolve_annotation_event_ref(ctx, source_id, record=record, field="source_id")
        resolved_target = self._resolve_annotation_event_ref(ctx, target_id, record=record, field="target_id")
        evidence_paragraph_id = self._event_evidence_paragraph_id(ctx, evidence, record=record)
        for item in self.relations:
            if item["source_operation_id"] == source_operation_id:
                same = (
                    item["source_kind"] == source_kind
                    and item["source_id"] == resolved_source
                    and item["target_kind"] == target_kind
                    and item["target_id"] == resolved_target
                    and item["relation_type"] == relation_type
                    and item["reason"] == reason
                    and item["evidence_paragraph_id"] == evidence_paragraph_id
                )
                if not same:
                    raise AnnotationStageRejection(
                        f"source_operation_id={source_operation_id} 关系内容冲突",
                        record=record,
                        field="source_id",
                        code="conflict",
                        expected="同一操作身份重试保持相同内容",
                    )
                return record
        evidence_paragraph_id = self._event_evidence_paragraph_id(ctx, evidence, record=record)
        relation_id = self._identifier(
            ctx.run_scope, ctx.work_id or ctx.current_chapter_id, "event_relation", source_operation_id
        )
        self.relations.append(
            {
                "relation_id": relation_id,
                "source_kind": source_kind,
                "source_id": resolved_source,
                "target_kind": target_kind,
                "target_id": resolved_target,
                "relation_type": relation_type,
                "reason": reason,
                "source_operation_id": source_operation_id,
                "record": record,
                "evidence_paragraph_id": evidence_paragraph_id,
            }
        )
        return record

    def drop_queue(self, queue_id: str) -> tuple[list[str], list[str]]:
        """用于撤回本 work 的队列草稿及其成员事件，返回成员节点 id 与被删节点的命名空间 el"""
        content = self.queues.pop(queue_id, None)
        if content is None:
            return [], []
        members = set(content["event_ids"])
        events = [item for item in self.bound_payloads.get("events", []) if item.node_id not in members]
        self.bound_payloads["events"] = events
        self.domain_payloads["events"] = events
        dropped: list[str] = []
        for record, event_id in list(self.event_ids_by_el.items()):
            if event_id not in members:
                continue
            for stale in [key for key in self.observation_by_record if key.startswith(f"{record}/participant/")]:
                del self.observation_by_record[stale]
            del self.event_ids_by_el[record]
            self.authorized_event_ids.discard(event_id)
            dropped.append(record)
        self._rebuild_observation_payload()
        return sorted(members), dropped

    def contribution_payloads(self) -> dict[str, dict[str, Any]]:
        """整理本 work 的候选关系；非标注产物在保存面明确拒绝"""
        return {
            "queues": {key: dict(item) for key, item in self.queues.items()},
            "complete_events": {str(item["event_id"]): dict(item) for item in self.complete_events.values()},
            "queue_references": {key: dict(item) for key, item in self.queue_references.items()},
            "ownerships": {key: dict(item) for key, item in self.ownerships.items()},
            "relations": {str(item["relation_id"]): dict(item) for item in self.relations},
        }

    def event_content(self, ctx: EventBindingStateContext, *, el: str) -> dict[str, Any]:
        """回显事件业务字段和来源身份"""
        cleaned = unicodedata.normalize("NFC", el).strip()
        event_id = self.event_ids_by_el.get(cleaned)
        if event_id is None:
            raise AnnotationInvariantError(f"write_event 回显需要账本内事件: {el}")
        event = self._bound_event(event_id)
        content: dict[str, Any] = {
            "event_id": event.event_id,
            "from": event.from_chapter_id,
            "to": event.to_chapter_id,
            "reason": event.reason,
            "id": event.event_id,
            "title": event.title,
            "problem": event.problem,
            "summary": event.summary,
            "event_type": event.event_type,
            "status": event.status,
            "progress": event.progress,
            "description": event.description,
        }
        content["isforeshadowing"] = event.is_foreshadow_setup
        content["confidence"] = event.payoff_likelihood
        content["characters"] = [
            {**p.model_dump(mode="json"), "entity": ctx.graph.display_name(p.entity)}
            if ctx.graph is not None
            else p.model_dump(mode="json")
            for p in event.participants
        ]
        return content

    def fact_views(self, ctx: EventBindingStateContext) -> dict[str, Any]:
        """只返回事件与人物观察事实，参与者身份由本状态绑定"""
        payloads = self.domain_payloads
        views: dict[str, Any] = {}
        if "character_observations" in payloads:
            views["character_observations"] = [
                {
                    "character": item.character,
                    "action": item.action,
                }
                for item in payloads["character_observations"]
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
                            "id": (ctx.graph.entity_id_for_key(participant.entity) if ctx.graph is not None else None),
                            "entity": (
                                ctx.graph.display_name(participant.entity)
                                if ctx.graph is not None
                                else participant.entity
                            ),
                            "role": str(participant.role),
                        }
                        for participant in item.participants
                    ],
                }
                for item in payloads["events"]
            ]
        return views
