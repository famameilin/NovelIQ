"""事件节点绑定、暂挂子节点与参与者状态；不持有队列、模型会话或保存事务"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from pydantic import ValidationError

from src.event_trees.models import (
    BoundEvent,
    EventParticipantInput,
    ParticipantArg,
)
from src.event_trees.vocabulary import (
    EventCauseRole,
    EventChildType,
    EventParticipantRole,
)
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import ChapterParagraphInfo
from src.fact_graph.outputs import BoundCharacterObservation
from src.fact_graph.schema import EL_PATH_SEP, RESERVED_ROOT_KEY
from src.fact_graph.vocabulary import Confidence, EntityType
from src.utils.identity import stable_uuid

from .errors import (
    AnnotationInvariantError,
    AnnotationStageRejection,
)
from .tools import _norm_entity_key
from .validation_errors import _translate_record_validation


class EventBindingStateContext(Protocol):
    """只开放此工作状态需要的上下文和引用能力"""

    def _require_writable(self, record: str) -> None: ...
    def _visible_global_pairs(self) -> list[tuple[int, int]]: ...

    current_chapter_id: int
    current_chapter_order: int | None
    graph: FactGraph | None
    paragraph_info: ChapterParagraphInfo | None

    def resolve_entity_ref(self, ref: str, *, record: str, field: str) -> str: ...

    run_scope: str
    work_id: str


@dataclass(slots=True)
class EventBindingState:
    authorized_event_ids: set[str] = field(default_factory=set)
    event_trees: dict[str, dict[str, Any]] = field(default_factory=dict)
    tree_key_index: dict[str, str] = field(default_factory=dict)
    pending_child_events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    observation_by_record: dict[str, BoundCharacterObservation] = field(default_factory=dict)
    domain_payloads: dict[str, Any] = field(default_factory=dict)
    bound_payloads: dict[str, Any] = field(default_factory=dict)

    def _tree_id(self, ctx: EventBindingStateContext, tree_key: str) -> str:
        """树身份绑定章与局部键，重试和乱序执行都得到同一 id"""
        return stable_uuid(ctx.run_scope, ctx.work_id or ctx.current_chapter_id, "event_tree", tree_key)

    def _node_id(self, ctx: EventBindingStateContext, tree_key: str, node_key: str) -> str:
        """节点身份绑定局部键，避免重投递产生另一组事件 id"""
        return stable_uuid(ctx.run_scope, ctx.work_id or ctx.current_chapter_id, "event_node", tree_key, node_key)

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
        isroot: bool,
        description: str,
        evidence: int | None = None,
        isforeshadowing: bool = False,
        confidence: Confidence | None = None,
        node_type: EventChildType | None = None,
        characters: list[ParticipantArg] | None = None,
    ) -> str:
        """用于写入一个事件节点：isroot 建根（el=树键），子事件 el=树键/节点键

        根节点键固定 root；子节点父=当时主链尾，main 推进链尾；树内先后=调用顺序。
        伏笔属性（isforeshadowing/confidence）只属于根，isforeshadowing=true 时
        confidence 必填；characters=None 保留该节点已有参与者，给出列表即整体替换。
        """
        record = self._event_record(el, isroot=isroot)
        ctx._require_writable(record)
        tree_key, _, node_key = el.partition(EL_PATH_SEP)
        tree_key = tree_key.strip()
        node_key = node_key.strip()
        if isroot:
            if not tree_key or node_key:
                raise AnnotationStageRejection(
                    f"根事件的 el 必须是树键（不带路径）: {el}",
                    record=record,
                    field="el",
                    code="bad_el",
                    expected="根事件 el=树键（如 t1）；子事件才是 树键/节点键（如 t1/e2）",
                )
            if node_type is not None:
                raise AnnotationStageRejection(
                    "type 只属于子事件（根事件由 isroot=true 表达）",
                    record=record,
                    field="type",
                    code="not_on_root",
                    expected="根事件不填 type",
                )
            if isforeshadowing and confidence is None:
                raise AnnotationStageRejection(
                    "isforeshadowing=true 时必须提供 confidence",
                    record=record,
                    field="confidence",
                    code="missing",
                    expected="confidence=high / medium / low（伏笔回收可能性三档）",
                )
            node_id = self._apply_event_root(
                ctx,
                record=record,
                tree_key=tree_key,
                description=description,
                evidence=evidence,
                isforeshadowing=isforeshadowing,
                confidence=confidence,
            )
            # 2026-10-04 树键校验下沉：建根（或根重写）时把先到的暂挂子事件按到达序冲账
            self._flush_pending_children(ctx, tree_key)
        else:
            if not tree_key or not node_key:
                raise AnnotationStageRejection(
                    f"子事件的 el 必须是 树键/节点键: {el}",
                    record=record,
                    field="el",
                    code="bad_el",
                    expected='形如 t1/e2（节点键不得占用 root）；建树请用 write_event(isroot=true, el="t1")',
                )
            if node_key == RESERVED_ROOT_KEY:
                raise AnnotationStageRejection(
                    f"子事件不得占用节点键 {RESERVED_ROOT_KEY}",
                    record=record,
                    field="el",
                    code="reserved",
                    expected="换一个节点键（root 固定指根事件）",
                )
            if isforeshadowing or confidence is not None:
                raise AnnotationStageRejection(
                    "伏笔属性（isforeshadowing/confidence）只属于根事件",
                    record=record,
                    field="isforeshadowing",
                    code="not_on_child",
                    expected="子事件只填 el/type/description/characters",
                )
            if node_type is None:
                raise AnnotationStageRejection(
                    "子事件必须提供 type",
                    record=record,
                    field="type",
                    code="missing",
                    expected='type="main"（顺延主因链）或 "secondary"（挂在当时主链尾）',
                )
            if self.tree_key_index.get(tree_key) is None:
                # 2026-10-04 树键校验下沉：根未建时子事件不再即时拒绝，挂起等建根冲账
                # （写面本来就是纯内存账本、整章成功才单事务落库，调用期因果校验只制造返工）
                self.pending_child_events.setdefault(tree_key, []).append(
                    {
                        "record": record,
                        "node_key": node_key,
                        "node_type": node_type,
                        "description": description,
                        "evidence": evidence,
                        "characters": characters,
                    }
                )
                return record
            node_id = self._apply_event_child(
                ctx,
                record=record,
                tree_key=tree_key,
                node_key=node_key,
                node_type=node_type,
                description=description,
                evidence=evidence,
            )
        if characters is not None:
            self._apply_participants(
                ctx,
                node_record=record,
                node_id=node_id,
                characters=characters,
            )
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

    def _apply_event_root(
        self,
        ctx: EventBindingStateContext,
        *,
        record: str,
        tree_key: str,
        description: str,
        evidence: int | None,
        isforeshadowing: bool,
        confidence: Confidence | None,
    ) -> str:
        """用于建树并即时落账根事件（同树键重写按更新语义），返回根节点 id"""
        existing = self.event_trees.get(self.tree_key_index.get(tree_key, ""))
        if existing is not None:
            root_event = self._bound_event(existing["root_node_id"])
            root_event.evidence_paragraph_id = self._event_evidence_paragraph_id(
                ctx, evidence, record=record, existing=root_event
            )
            root_event.description = description
            root_event.is_foreshadow_setup = isforeshadowing
            root_event.payoff_likelihood = confidence
            existing["isforeshadowing"] = isforeshadowing
            return str(existing["root_node_id"])
        tree_id = self._tree_id(ctx, tree_key)
        root_node_id = self._node_id(ctx, tree_key, RESERVED_ROOT_KEY)
        evidence_paragraph_id = self._event_evidence_paragraph_id(ctx, evidence, record=record)
        root_event = BoundEvent(
            node_id=root_node_id,
            tree_id=tree_id,
            parent_node_id=None,
            cause_role="root",
            description=description,
            evidence_paragraph_id=evidence_paragraph_id,
            participants=[],
            is_foreshadow_setup=isforeshadowing,
            payoff_likelihood=confidence,
        )
        events_bound = list(self.bound_payloads.get("events") or [])
        events_bound.append(root_event)
        self.bound_payloads["events"] = events_bound
        self.domain_payloads["events"] = events_bound
        self.event_trees[tree_id] = {
            "tree_id": tree_id,
            "chapter_id": ctx.current_chapter_id,
            "chapter_order": ctx.current_chapter_order,
            "root_node_id": root_node_id,
            "trunk_tail": root_node_id,
            "isforeshadowing": isforeshadowing,
            # node_key → node_id：模型侧只用章内局部键寻址（根键固定 root）
            "nodes": {RESERVED_ROOT_KEY: root_node_id},
        }
        self.tree_key_index[tree_key] = tree_id
        self.authorized_event_ids.add(root_node_id)
        return root_node_id

    def _apply_event_child(
        self,
        ctx: EventBindingStateContext,
        *,
        record: str,
        tree_key: str,
        node_key: str,
        node_type: EventChildType,
        description: str,
        evidence: int | None,
    ) -> str:
        """用于在已建的树上追加/更新一个子事件，返回节点 id

        "main" 顺延主因链（成为新的链尾）/"secondary" 挂在当时主链尾；
        树内先后=调用顺序（order 参数已下线，无任何下游消费）。
        """
        tree = self._tree_by_key(tree_key, record)
        existing_node_id = tree["nodes"].get(node_key)
        if existing_node_id is not None:
            event = self._bound_event(str(existing_node_id))
            if str(event.cause_role) != str(node_type):
                raise AnnotationStageRejection(
                    f"节点已建，type 不允许改写: {tree_key}/{node_key}",
                    record=record,
                    field="type",
                    code="immutable",
                    expected="删除重写需换节点键（该节点 type=已定的 main/secondary）",
                )
            event.evidence_paragraph_id = self._event_evidence_paragraph_id(
                ctx, evidence, record=record, existing=event
            )
            event.description = description
            self._discard_resubmitted_pending({(node_key, description)}, exclude_tree=tree_key)
            return str(existing_node_id)
        parent_node_id = str(tree["trunk_tail"])
        node_id = self._node_id(ctx, tree_key, node_key)
        evidence_paragraph_id = self._event_evidence_paragraph_id(ctx, evidence, record=record)
        event = BoundEvent(
            node_id=node_id,
            tree_id=str(tree["tree_id"]),
            parent_node_id=parent_node_id,
            cause_role=cast("EventCauseRole", str(node_type)),
            description=description,
            evidence_paragraph_id=evidence_paragraph_id,
            participants=[],
        )
        events_bound = list(self.bound_payloads.get("events") or [])
        events_bound.append(event)
        self.bound_payloads["events"] = events_bound
        self.domain_payloads["events"] = events_bound
        tree["nodes"][node_key] = node_id
        if str(node_type) == "main":
            tree["trunk_tail"] = node_id
        self.authorized_event_ids.add(node_id)
        self._discard_resubmitted_pending({(node_key, description)}, exclude_tree=tree_key)
        return node_id

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
        """用于建根时按到达顺序冲账先于根提交的暂挂子事件（含各自参与者）"""
        pending = self.pending_child_events.pop(tree_key, None)
        if not pending:
            return
        for item in pending:
            node_id = self._apply_event_child(
                ctx,
                record=str(item["record"]),
                tree_key=tree_key,
                node_key=str(item["node_key"]),
                node_type=cast("EventChildType", item["node_type"]),
                description=str(item["description"]),
                evidence=item.get("evidence"),
            )
            characters = item.get("characters")
            if characters is not None:
                self._apply_participants(
                    ctx,
                    node_record=str(item["record"]),
                    node_id=node_id,
                    characters=characters,
                )

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
            participant_record = f"{node_record}/participant/{arg.entityid}"
            entity_name = ctx.resolve_entity_ref(arg.entityid, record=participant_record, field="entityid")
            key = _norm_entity_key(entity_name)
            if key in seen:
                raise AnnotationStageRejection(
                    f"同一实体在 characters 数组内重复出现: {entity_name}",
                    record=participant_record,
                    field="entityid",
                    code="duplicate_participant",
                    expected="每个实体一次提交只出现一次（本数组即该节点参与者的完整集合）",
                )
            seen.add(key)
            actual_type = ctx.graph.entity_type(entity_name)
            if actual_type is None:
                raise AnnotationStageRejection(
                    f"参与者实体未登记: {entity_name}",
                    record=participant_record,
                    field="entityid",
                    code="unregistered",
                    expected="先用 write_entity 登记本章实体",
                )
            # 2026-10-04 合同放开：role 可省略，按实体登记类型给缺省
            # （character→主体、location→地点、其余→客体）；显式写错仍拒
            effective_role = arg.role or (
                EventParticipantRole.LOCATION
                if actual_type == EntityType.LOCATION.value
                else EventParticipantRole.SUBJECT
                if actual_type == EntityType.CHARACTER.value
                else EventParticipantRole.OBJECT
            )
            if effective_role == EventParticipantRole.LOCATION and actual_type != EntityType.LOCATION.value:
                raise AnnotationStageRejection(
                    f"地点角色端点必须是 location: {entity_name}（登记类型 {actual_type}）",
                    record=participant_record,
                    field="role",
                    code="role_type_mismatch",
                    expected="地点角色只用于 location 实体",
                )
            has_observation = any(value is not None for value in (arg.narrative_role, arg.action, arg.emotion))
            if actual_type == EntityType.CHARACTER.value:
                # 2026-10-04 合同放开：三态字段可空落账（不再要求必填），缺省由消费方按空处理
                if arg.action is not None:
                    self._reject_duplicate_observation(participant_record, entity_name, arg.action)
                # 2026-10-04 三态全空不产动态状态行：同一人物在多个事件上无动作参与是放开后的
                # 正常形态，全空行既无信息量又会在收尾校验撞 (character, action=None) 重复语义；
                # 参与者本身仍随事件落账，只是不进 character_observations
                if has_observation:
                    self.observation_by_record[participant_record] = BoundCharacterObservation(
                        character=entity_name,
                        role_function=arg.narrative_role,
                        action=arg.action,
                        emotion=arg.emotion,
                    )
            elif has_observation:
                raise AnnotationStageRejection(
                    f"narrative_role/action/emotion 只属于 character 参与者: {entity_name}（登记类型 {actual_type}）",
                    record=participant_record,
                    field="narrative_role",
                    code="observation_on_noncharacter",
                    expected="非 character 条目只填 entityid/role",
                )
            try:
                participants.append(
                    EventParticipantInput(
                        entity=entity_name,
                        role=effective_role,
                        narrative_role=arg.narrative_role,
                        action=arg.action,
                        emotion=arg.emotion,
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

    def event_content(self, *, el: str, isroot: bool) -> dict[str, Any]:
        """用于回显 write_event 后该节点的服务端终值（节点 id/描述/伏笔属性/参与者三态）

        el 与 isroot 是模型侧提交别名、树上不存储，因此不进 content；id 纪律下
        content 带 run 级 uuid 节点 id（=落库 event_id），树级 uuid 不外露。
        """
        cleaned = unicodedata.normalize("NFC", el).strip()
        tree_key, _, node_key = cleaned.partition(EL_PATH_SEP)
        tree_key_clean = tree_key.strip()
        tree = self.event_trees.get(self.tree_key_index.get(tree_key_clean, ""))
        if tree is None:
            if tree_key_clean in self.pending_child_events:
                # 2026-10-04 树键校验下沉：暂挂子事件的回显即挂起状态本身
                return {
                    "deferred": True,
                    "note": f"树 {tree_key_clean} 尚未建根：该子事件已挂起，根建好后自动生效",
                }
            raise AnnotationInvariantError(f"write_event 回显需要账本内事件树: {tree_key}")
        if isroot or not node_key.strip():
            event = self._bound_event(str(tree["root_node_id"]))
        else:
            event = self._bound_event(str(tree["nodes"][node_key.strip()]))
        content: dict[str, Any] = {
            "id": str(event.node_id),
            "description": event.description,
        }
        if isroot:
            content["isforeshadowing"] = bool(tree["isforeshadowing"])
            confidence = event.payoff_likelihood
            content["confidence"] = str(confidence) if confidence is not None else None
        else:
            content["type"] = str(event.cause_role)
        content["characters"] = [p.model_dump(mode="json") for p in event.participants]
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
