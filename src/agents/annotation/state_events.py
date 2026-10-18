"""事件节点绑定、暂挂子节点与参与者状态；不持有队列、模型会话或保存事务"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

from pydantic import ValidationError

from src.event_trees.models import (
    BoundEvent,
    EventParticipantInput,
    ParticipantArg,
)
from src.event_trees.vocabulary import (
    EventParticipantRole,
)
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import ChapterParagraphInfo
from src.fact_graph.outputs import BoundCharacterObservation
from src.fact_graph.schema import EL_PATH_SEP, RESERVED_ROOT_KEY
from src.fact_graph.vocabulary import Confidence, EntityType
from src.storage import new_id

from .entity_refs import ensure_entity_ref
from .errors import (
    AnnotationInvariantError,
    AnnotationStageRejection,
)
from .validation_errors import _translate_record_validation


class EventBindingStateContext(Protocol):
    """只开放此工作状态需要的上下文和引用能力"""

    def _require_writable(self, record: str) -> None: ...
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
    confirmed_declaration_ids: set[str]
    confirmed_containment_parents: dict[str, str]


@dataclass(slots=True)
class EventBindingState:
    identifiers: dict[tuple, str] = field(default_factory=dict)

    def _identifier(self, *key) -> str:
        """同一局部键复用已分配的 UUIDv7，身份不是局部键的编码"""
        if key not in self.identifiers:
            self.identifiers[key] = new_id()
        return self.identifiers[key]

    authorized_event_ids: set[str] = field(default_factory=set)
    event_trees: dict[str, dict[str, Any]] = field(default_factory=dict)
    tree_key_index: dict[str, str] = field(default_factory=dict)
    pending_child_events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    observation_by_record: dict[str, BoundCharacterObservation] = field(default_factory=dict)
    domain_payloads: dict[str, Any] = field(default_factory=dict)
    bound_payloads: dict[str, Any] = field(default_factory=dict)
    # 完整事件域：EventNode 继续保存过程，下列对象是完整事件及其关联的
    # 本 work 挂起记录（局部键 → 声明；随正式贡献冻结、保存、确认与回滚）
    complete_events: dict[str, dict[str, Any]] = field(default_factory=dict)
    event_revisions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    containments: dict[str, dict[str, Any]] = field(default_factory=dict)
    ownerships: dict[str, dict[str, Any]] = field(default_factory=dict)
    relations: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    def _tree_id(self, ctx: EventBindingStateContext, tree_key: str) -> str:
        """树身份绑定章与局部键，重试和乱序执行都得到同一 id"""
        return self._identifier(ctx.run_scope, ctx.work_id or ctx.current_chapter_id, "event_tree", tree_key)

    def _node_id(self, ctx: EventBindingStateContext, tree_key: str, node_key: str) -> str:
        """节点身份绑定局部键，避免重投递产生另一组事件 id"""
        return self._identifier(ctx.run_scope, ctx.work_id or ctx.current_chapter_id, "event_node", tree_key, node_key)

    def _tree_by_key(self, tree_key: str, record: str) -> dict[str, Any]:
        """用于按章内局部键读取已落账的事件树，未建树时给出可自纠报错"""
        tree = self.event_trees.get(self.tree_key_index.get(tree_key, ""))
        if tree is None:
            raise AnnotationStageRejection(
                f"树键未建: {tree_key}",
                record=record,
                field="el",
                code="unknown_tree",
                expected='先用 write_event(isroot=true, el="t1") 建树，子事件再用 t1/节点键（同轮先根后子即可）',
            )
        return tree

    def _bound_event(self, node_id: str) -> BoundEvent:
        """用于在已落账事件里按节点 id 取节点对象（参与者挂在它上面）"""
        for event in self.bound_payloads.get("events") or []:
            if event.node_id == node_id:
                return event
        raise AnnotationInvariantError(f"事件节点未落账: {node_id}")

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
        isforeshadowing: bool = False,
        confidence: Confidence | None = None,
        characters: list[ParticipantArg] | None = None,
    ) -> str:
        """登记事件级章内声明，局部路径不产生全书包含或阶段关系"""
        isroot = EL_PATH_SEP not in el
        record = self._event_record(el, isroot=isroot)
        ctx._require_writable(record)
        tree_key, _, node_key = el.partition(EL_PATH_SEP)
        node_key = node_key or RESERVED_ROOT_KEY
        tree_id = self._tree_id(ctx, tree_key)
        declaration_id = self._node_id(ctx, tree_key, node_key)
        existing = next(
            (item for item in self.bound_payloads.get("events", []) if item.node_id == declaration_id), None
        )
        paragraph_id = self._event_evidence_paragraph_id(ctx, evidence, record=record, existing=existing)
        if isforeshadowing and confidence is None:
            raise AnnotationStageRejection(
                "isforeshadowing=true 时必须提供 confidence",
                record=record,
                field="confidence",
                code="missing",
                expected="high / medium / low",
            )
        declaration = BoundEvent(
            node_id=declaration_id,
            declaration_id=declaration_id,
            title=title,
            problem=problem,
            summary=summary,
            event_type=event_type,
            status=cast(Literal["ongoing", "resolved"], status),
            progress=progress,
            description=summary,
            tree_id=declaration_id,
            parent_node_id=None,
            cause_role="root",
            evidence_paragraph_id=paragraph_id,
            participants=list(existing.participants) if existing is not None else [],
            is_foreshadow_setup=isforeshadowing,
            payoff_likelihood=confidence,
        )
        if existing is not None:
            if existing.model_dump(exclude={"participants"}) != declaration.model_dump(exclude={"participants"}):
                raise AnnotationStageRejection(
                    f"declaration_id={declaration_id} 声明内容不可改写",
                    record=record,
                    field="summary",
                    code="immutable",
                    expected="复用已接受声明及其原始字段，不覆盖来源",
                )
        else:
            events = list(self.bound_payloads.get("events", []))
            for other in events:
                if other.evidence_paragraph_id == paragraph_id and other.summary == summary:
                    raise AnnotationStageRejection(
                        f"声明与 {other.declaration_id} 同源重复",
                        record=record,
                        field="summary",
                        code="duplicate_declaration",
                        expected=f"引用已有 declaration_id={other.declaration_id}",
                    )
            events.append(declaration)
            self.bound_payloads["events"] = events
            self.domain_payloads["events"] = events
        tree = self.event_trees.setdefault(
            tree_id,
            {
                "tree_id": tree_id,
                "chapter_id": ctx.current_chapter_id,
                "chapter_order": ctx.current_chapter_order,
                "nodes": {},
                "isforeshadowing": False,
            },
        )
        tree["nodes"][node_key] = declaration_id
        tree["isforeshadowing"] = bool(tree["isforeshadowing"] or isforeshadowing)
        # 路径保留为来源地址，不承诺先声明树根或由先后关系形成父级
        tree.setdefault("root_node_id", declaration_id)
        self.tree_key_index[tree_key] = tree_id
        self.authorized_event_ids.add(declaration_id)
        if characters is not None:
            self._apply_participants(ctx, node_record=record, node_id=declaration_id, characters=characters)
        return record

    def _event_record(self, el: str, *, isroot: bool) -> str:
        """用于把模型面 el 归一成记录键（根记录 = 树键/root）"""
        cleaned = unicodedata.normalize("NFC", el).strip()
        if isroot or EL_PATH_SEP not in cleaned:
            return f"{cleaned}/{RESERVED_ROOT_KEY}"
        return cleaned

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

    def _discard_resubmitted_pending(
        self,
        written: set[tuple[str, str]],
        *,
        exclude_tree: str | None = None,
    ) -> None:
        """只核销节点键与描述完全一致的重提项，保留未写入项及其原有到达顺序"""
        for tree_key, items in list(self.pending_child_events.items()):
            if tree_key == exclude_tree:
                continue
            remaining = [item for item in items if (str(item["node_key"]), str(item["description"])) not in written]
            if remaining:
                self.pending_child_events[tree_key] = remaining
            else:
                del self.pending_child_events[tree_key]

    def _reconcile_pending_children(self) -> None:
        """收尾前核对实际已落账的子节点，清理早前错误桶中已被正确重提的挂起项"""
        event_by_id = {str(event.node_id): event for event in self.bound_payloads.get("events") or []}
        written = {
            (str(node_key), event_by_id[str(node_id)].description)
            for tree in self.event_trees.values()
            for node_key, node_id in tree.get("nodes", {}).items()
            if node_key != RESERVED_ROOT_KEY and str(node_id) in event_by_id
        }
        self._discard_resubmitted_pending(written)

    def _flush_pending_children(self, ctx: EventBindingStateContext, tree_key: str) -> None:
        """声明可以独立提交，来源局部键不依赖另一项声明先创建"""
        if self.pending_child_events:
            raise ValueError("新声明契约不接受旧过程挂起记录")

    def is_pending_child(self, record: str) -> bool:
        """用于判断该生产记录键是否仍在暂挂子事件缓冲里（树根未建，调用期未落账）"""
        return any(str(item.get("record")) == record for items in self.pending_child_events.values() for item in items)

    def _apply_participants(
        self,
        ctx: EventBindingStateContext,
        *,
        node_record: str,
        node_id: str,
        characters: list[ParticipantArg],
    ) -> None:
        """用于把 characters 数组整体替换到指定节点的参与者列表

        按登记类型分流：character 三态可空、给了就派生人物动态状态
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
            has_observation = any(value is not None for value in (arg.narrative_role, arg.action, arg.emotion))
            if actual_type == EntityType.CHARACTER.value:
                # 合同放开：三态字段可空落账（不再要求必填），缺省由消费方按空处理
                if arg.action is not None:
                    self._reject_duplicate_observation(participant_record, entity_name, arg.action)
                # 三态全空不产动态状态行：同一人物在多个事件上无动作参与是放开后的
                # 正常形态，全空行既无信息量又会在收尾校验撞 (character, action=None) 重复语义；
                # 参与者本身仍随事件落账，只是不进 character_observations
                if has_observation:
                    self.observation_by_record[participant_record] = BoundCharacterObservation(
                        character=entity_name,
                        role_function=arg.narrative_role,
                        action=arg.action,
                        emotion=arg.emotion,
                    )
                narrative_role, action, emotion = arg.narrative_role, arg.action, arg.emotion
            else:
                # 三态只服务人物动态状态，item/organization/location 无消费者；模型常给
                # 非角色实体补动作，硬拒会连带丢掉整组参与者（含同组合法 character 条目）并烧尽回合，
                # 故改为忽略三态、保留名字、大类与 role
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
    # 章级声明只记录候选关系，正式事件身份和结构由诊断发布
    # ------------------------------------------------------------------

    def _resolve_declaration_ref(self, ctx: EventBindingStateContext, ref: str, *, record: str, field: str) -> str:
        """把本 work 局部键或已读取、已保存声明引用解析成 declaration_id"""
        cleaned = unicodedata.normalize("NFC", str(ref)).strip()
        tree_key, _, node_key = cleaned.partition(EL_PATH_SEP)
        active_tree_key = tree_key.strip()
        if active_tree_key not in self.tree_key_index:
            active_tree_key = f"{ctx.role}:{active_tree_key}"
        tree = self.event_trees.get(self.tree_key_index.get(active_tree_key, ""))
        if tree is not None:
            if node_key.strip():
                node_id = tree["nodes"].get(node_key.strip())
                if node_id is not None:
                    return str(node_id)
            else:
                return str(tree["root_node_id"])
        if cleaned in self.authorized_event_ids:
            return cleaned
        if cleaned in ctx.confirmed_declaration_ids:
            return cleaned
        raise AnnotationStageRejection(
            f"声明身份不存在: {ref}",
            record=record,
            field=field,
            code="unknown_declaration",
            expected="本 work 已落账声明的局部键或 declaration_id，或本 run 已确认 declaration_id",
        )

    def apply_declaration_relation(
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
        """write_link 只登记声明之间的候选关系，正式关系由诊断确认发布"""
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
        if source_kind != "declaration" or target_kind != "declaration":
            raise ValueError("标注只能提交声明间关系建议")
        resolved_source = self._resolve_declaration_ref(ctx, source_id, record=record, field="source_id")
        resolved_target = self._resolve_declaration_ref(ctx, target_id, record=record, field="target_id")
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

    def contribution_payloads(self) -> dict[str, dict[str, Any]]:
        """整理本 work 的候选关系；非标注产物在保存面明确拒绝"""
        return {
            "complete_events": {str(item["event_id"]): dict(item) for item in self.complete_events.values()},
            "revisions": {
                str(item["revision_id"]): dict(item) for chain in self.event_revisions.values() for item in chain
            },
            "containments": {key: dict(item) for key, item in self.containments.items()},
            "ownerships": {key: dict(item) for key, item in self.ownerships.items()},
            "relations": {str(item["relation_id"]): dict(item) for item in self.relations},
            "conflicts": {str(item["conflict_id"]): dict(item) for item in self.conflicts},
        }

    def event_content(self, ctx: EventBindingStateContext, *, el: str, isroot: bool) -> dict[str, Any]:
        """回显声明业务字段和来源身份；内部来源容器不代表正式事件结构"""
        cleaned = unicodedata.normalize("NFC", el).strip()
        tree_key, _, node_key = cleaned.partition(EL_PATH_SEP)
        tree_key_clean = tree_key.strip()
        tree = self.event_trees.get(self.tree_key_index.get(tree_key_clean, ""))
        if tree is None:
            if tree_key_clean in self.pending_child_events:
                # 树键校验下沉：暂挂子事件的回显即挂起状态本身
                return {
                    "deferred": True,
                    "note": f"树 {tree_key_clean} 尚未建根：该子事件已挂起，根建好后自动生效",
                }
            raise AnnotationInvariantError(f"write_event 回显需要账本内事件树: {tree_key}")
        event = self._bound_event(str(tree["nodes"][node_key.strip() or RESERVED_ROOT_KEY]))
        content: dict[str, Any] = {
            "declaration_id": event.declaration_id,
            "id": event.declaration_id,
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

    def _event_tree_records(self) -> list[dict[str, Any]]:
        """用于按建树顺序汇总每棵树的结构（节点键与父子关系，不含真实 id）"""
        trees: list[dict[str, Any]] = []
        for tree_key, tree_id in self.tree_key_index.items():
            tree = self.event_trees.get(tree_id) or {}
            children: list[dict[str, Any]] = []
            for node_key, node_id in tree.get("nodes", {}).items():
                if node_key == RESERVED_ROOT_KEY:
                    continue
                event = self._bound_event(str(node_id))
                children.append(
                    {
                        "node_key": node_key,
                        "type": str(event.cause_role),
                        "parent_node_key": self._node_key_of(tree, str(event.parent_node_id or "")),
                    }
                )
            root_event = self._bound_event(str(tree.get("root_node_id") or ""))
            trees.append(
                {
                    "tree_key": tree_key,
                    "description": root_event.description,
                    "isforeshadowing": bool(tree.get("isforeshadowing")),
                    "children": children,
                }
            )
        return trees

    def _node_key_of(self, tree: dict[str, Any], node_id: str) -> str | None:
        """用于按节点 id 反查章内节点键（审计记录不暴露真实 id）"""
        for node_key, candidate in tree.get("nodes", {}).items():
            if str(candidate) == node_id:
                return str(node_key)
        return None

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
