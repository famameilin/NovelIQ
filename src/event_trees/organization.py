"完整事件组织草稿、原文绑定与正式产出保存"

from __future__ import annotations

import hashlib
import json
import threading
import unicodedata
from copy import deepcopy
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from src.event_trees import storage_map as smap
from src.fact_graph.outputs import SourceReference
from src.storage import Storage, new_id
from src.storage.records.models import CompleteEventRecord as CompleteEvent
from src.storage.records.models import ParagraphRecord as Paragraph
from src.utils.identity import text_digest


def _validate_narrative_description(value: str) -> str:
    if sum(not unicodedata.category(char).startswith("P") for char in value) > 20:
        raise ValueError("目标或说明最多20字，不计算标点，请精简后重写并重新提交")
    return value


def _validate_narrative_title(value: str) -> str:
    if sum(not unicodedata.category(char).startswith("P") for char in value) > 6:
        raise ValueError("标题最多6字，不计算标点，请精简后重写并重新提交")
    return value


NarrativeTitle = Annotated[
    str,
    Field(min_length=1, description="单一精练标题，最多6字；不计算Unicode标点，其余字符逐字计数；超限须重写"),
    AfterValidator(_validate_narrative_title),
]
NarrativeDescription = Annotated[
    str,
    Field(min_length=1, description="一句目标或结果说明，最多20字；不计算Unicode标点，其余字符逐字计数；超限须重写"),
    AfterValidator(_validate_narrative_description),
]


def snapshot_digest(payload: Any) -> str:
    """稳定摘要只绑定业务内容，不包含审计或容量租约"""
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def record_payloads(records: Any) -> list[dict[str, Any]]:
    """无序候选集合以内容排序，跨工作恢复顺序不改变核对结果"""
    return sorted((item.model_dump(mode="json") for item in records), key=snapshot_digest)


class CandidateConflict(ValueError):
    """可定位的候选冲突只返回真实生产者，不能重开无关会话"""

    def __init__(self, message: str, producer_agent_ids: list[str]) -> None:
        self.producer_agent_ids = tuple(sorted(set(producer_agent_ids)))
        super().__init__(message)


class OrganizationEvidence(BaseModel):
    """工具只接受真实段号与逐字引文，坐标和哈希由服务端绑定"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    paragraph_id: int = Field(ge=0)
    quote: str | None = Field(default=None, min_length=1)
    occurrence: int = Field(default=1, ge=1)
    event_id: str | None = Field(default=None, min_length=1)


class BoundOrganizationEvidence(SourceReference):
    """正式证据保留可选的完整事件引用与已绑定原文位置"""

    event_id: str | None = None


class OrganizationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence: list[BoundOrganizationEvidence] = Field(min_length=1, max_length=100)
    producer_agent_id: str = ""


class NarrativeArcDraft(OrganizationRecord):
    arc_id: str
    parent_arc_id: str | None = None
    kind: Literal["main", "subplot"]
    title: NarrativeTitle
    objective: NarrativeDescription
    role: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EventArcLinkDraft(OrganizationRecord):
    event_id: str
    arc_id: str
    role: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EventOutcomeDraft(OrganizationRecord):
    outcome_id: str
    title: NarrativeTitle
    description: NarrativeDescription
    first_text_position: int = Field(ge=0)


class EventOutcomeLinkDraft(OrganizationRecord):
    event_id: str
    outcome_id: str
    reason: str = Field(min_length=1)


class CompleteEventDraft(OrganizationRecord):
    """诊断待保存的完整事件；直接过程与子事件作为同一笔原子输入"""

    event_id: str
    local_key: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1)
    problem: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    status: Literal["ongoing", "resolved"]
    progress: str | None = None
    reason: str | None = None
    annotation_record_id: str | None = None
    from_chapter_id: int
    to_chapter_id: int
    is_foreshadowing_root: bool = False
    payoff_likelihood: str | None = None
    first_text_position: int = Field(ge=0)
    participants: list[dict[str, Any]] = Field(default_factory=list)


class ContainmentDraft(OrganizationRecord):
    parent_event_id: str
    child_event_id: str
    reason: str = Field(min_length=1)


class RelationDraft(OrganizationRecord):
    relation_id: str
    source_kind: Literal["event"]
    source_id: str
    target_kind: Literal["event"]
    target_id: str
    relation_type: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source_operation_id: str | None
    is_active: bool | None = True


class NarrativeOrganization(BaseModel):
    """完整事件的全书组织；章节概要、类型和包含结构保持不可变"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source_agent_id: str | None = None
    events: list[CompleteEventDraft] = Field(default_factory=list)
    relations: list[RelationDraft] = Field(default_factory=list)
    arcs: list[NarrativeArcDraft] = Field(default_factory=list)
    event_arc_links: list[EventArcLinkDraft] = Field(default_factory=list)
    outcomes: list[EventOutcomeDraft] = Field(default_factory=list)
    event_outcome_links: list[EventOutcomeLinkDraft] = Field(default_factory=list)
    containments: list[ContainmentDraft] = Field(default_factory=list)
    content_snapshot: str | None = None
    structure_snapshot: str | None = None

    @model_validator(mode="after")
    def validate_structure(self) -> NarrativeOrganization:
        arcs = {arc.arc_id: arc for arc in self.arcs}
        outcomes = {item.outcome_id for item in self.outcomes}
        for records, keys in (
            (self.events, {item.event_id for item in self.events}),
            (self.relations, {item.relation_id for item in self.relations}),
            (self.arcs, list(arcs)),
            (self.outcomes, list(outcomes)),
            (self.event_arc_links, {(item.event_id, item.arc_id) for item in self.event_arc_links}),
            (self.event_outcome_links, {(item.event_id, item.outcome_id) for item in self.event_outcome_links}),
        ):
            if len(records) != len(keys):
                raise ValueError("全书组织身份或关联端点重复")
        for arc in self.arcs:
            current: str | None = arc.arc_id
            seen: set[str] = set()
            while current is not None:
                if current not in arcs:
                    raise ValueError(f"父级叙事线不存在: {current}")
                if current in seen:
                    raise ValueError(f"叙事线父级形成环: {current}")
                seen.add(current)
                current = arcs[current].parent_arc_id
        for link in self.event_arc_links:
            if link.arc_id not in arcs:
                raise ValueError(f"叙事线关联端点不存在: {link.arc_id}")
        for outcome_link in self.event_outcome_links:
            if outcome_link.outcome_id not in outcomes:
                raise ValueError(f"结果关联端点不存在: {outcome_link.outcome_id}")
        if outcomes != {link.outcome_id for link in self.event_outcome_links}:
            raise ValueError("独立结果必须具有具体事件贡献关系")
        return self


# ---------------------------------------------------------------------------
# 诊断会话与真实执行的登记（新关系；不恢复 checkpoint）
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 本 run 的事件、完整事件与关系的读取投影
# ---------------------------------------------------------------------------


def run_annotation_event_ids(session: Storage, run_id: str) -> set[str]:
    """本 run 的章级事件：记录自身携带运行归属"""
    return smap.run_annotation_event_ids(session, run_id)


def _chapter_offsets(session: Storage, run_id: str, chapter_ids: set[int]) -> dict[int, int]:
    """章正文全文起点；空正文章节无切片，其段落也不存在证据"""
    return smap.chapter_offsets(session, run_id, chapter_ids)


def _paragraph_rows(session: Storage, run_id: str, paragraph_ids: set[int]) -> dict[int, Paragraph]:
    return smap.paragraph_rows(session, run_id, paragraph_ids)


def _evidence_payloads(session: Storage, run_id: str, rows: list[Any]) -> list[dict[str, Any]]:
    """证据行按 ordinal 重组为原文引用，哈希由不可变原文切片重算"""
    return smap.evidence_payloads(session, run_id, rows)


def _global_positions(session: Storage, run_id: str, paragraph_ids: set[int]) -> dict[int, int]:
    """段落全文起点 = 所属正文起点 + 章内起点"""
    return smap.global_positions(session, run_id, paragraph_ids)


def _first_text_position(session: Storage, run_id: str, evidence: list[Any]) -> int:
    """完整事件/结果的正文排序位置由其自身证据派生"""
    positions = smap.global_positions(session, run_id, {int(ref.paragraph_id) for ref in evidence})
    return min(positions[int(ref.paragraph_id)] + int(ref.char_start) for ref in evidence)


def _run_events(session: Storage, run_id: str) -> dict[str, CompleteEvent]:
    return smap.run_events(session, run_id)


def _run_event_dicts(session: Storage, run_id: str) -> dict[str, dict[str, Any]]:
    """本 run 完整事件的读取形状：身份 + 当前内容 + 整体证据"""
    rows = _run_events(session, run_id)
    if not rows:
        return {}
    event_ids = list(rows)
    evidence = smap.fetch_evidence(session, "complete_event_id", event_ids)
    grouped = smap.evidence_payload_groups(session, run_id, [evidence.get(identifier, []) for identifier in rows])
    participant_rows = list(session.reads.event_trees_organization_annotation_event_rows_1(event_ids))
    entities = (
        {row.entity_id: row for row in session.reads.event_trees_organization_annotation_event_rows_4(participant_rows)}
        if participant_rows
        else {}
    )
    result: dict[str, dict[str, Any]] = {}
    positions = _global_positions(session, run_id, {item["paragraph_id"] for payloads in grouped for item in payloads})
    for (event_id, row), payloads in zip(rows.items(), grouped, strict=True):
        if not payloads:
            raise ValueError(f"正式事件缺少整体证据: event_id={event_id}")
        result[event_id] = {
            "event_id": event_id,
            "title": row.title,
            "problem": row.problem,
            "summary": row.summary,
            "event_type": row.event_type,
            "status": row.status,
            "progress": row.progress,
            "from": row.from_chapter_id,
            "to": row.to_chapter_id,
            "is_foreshadowing_root": row.is_foreshadowing_root,
            "participants": [
                {
                    "entity": {
                        "entity_id": item.entity_id,
                        "name": entities[item.entity_id].canonical_name,
                        "entity_type": entities[item.entity_id].entity_type,
                    },
                    "role": item.role,
                    "action": item.action,
                    "emotion": item.emotion,
                    "narrative_role": item.narrative_role,
                }
                for item in participant_rows
                if item.event_id == event_id
            ],
            "first_text_position": min(positions[item["paragraph_id"]] + item["char_start"] for item in payloads),
            "evidence": payloads,
        }
    return result


def _run_annotation_records(session: Storage, run_id: str) -> list[Any]:
    """本 run 的章级标注记录：记录自身带 run/章归属，不经 work 推导"""
    return list(session.reads.event_trees_organization_run_annotation_records_1(run_id))


def _run_foreshadowing_actions(session: Storage, run_id: str) -> list[Any]:
    """本 run 的伏笔动作：来源或目标事件属于本 run 的事件集合"""
    annotation_events = run_annotation_event_ids(session, run_id)
    if not annotation_events:
        return []
    return list(session.reads.event_trees_organization_run_foreshadowing_actions_1(annotation_events))


def _page_size(limit: int, maximum: int = 100) -> None:
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit 必须在 1 到 {maximum} 之间")


class EventOrganizationDraft:
    """只更新本轮内存；程序检查完整性后由诊断保存点一次提交"""

    def _identifier(self, *key):
        if key not in self._identifiers:
            self._identifiers[key] = new_id()
        return self._identifiers[key]

    def __init__(self, session: Storage, run_id: str, agent_id: str | None = None) -> None:
        # agent_id 是诊断整轮的会话身份（executions 的 session 形状），不是单个案例的调用
        self.session = session
        self.lock = threading.RLock()
        self.publication_lock = threading.RLock()
        self.cache_reads = False
        self._stored_view: tuple[dict[str, dict[str, Any]], dict[str, str]] | None = None
        self.run_id = run_id
        self._identifiers: dict[tuple, str] = {}
        self.agent_id = agent_id
        self.producer_agent_id: str | None = None
        self.content_snapshot: str | None = None
        self.structure_snapshot: str | None = None
        self.containments: dict[tuple[str, str], ContainmentDraft] = {}
        self.events: dict[str, CompleteEventDraft] = {}
        self.relations: dict[str, RelationDraft] = {}
        self.saved_relation_ids: set[str] = set()
        self.arcs: dict[str, NarrativeArcDraft] = {}
        self.event_arc_links: dict[tuple[str, str], EventArcLinkDraft] = {}
        self.outcomes: dict[str, EventOutcomeDraft] = {}
        self.event_outcome_links: dict[tuple[str, str], EventOutcomeLinkDraft] = {}

    def _all_events(self) -> dict[str, dict[str, Any]]:
        return self.read_view()[0]

    def _parents(self) -> dict[str, str]:
        return self.read_view()[1]

    def refresh_read_cache(self) -> None:
        "正式提交后失效存储视图，下一次读取按正式记录重新装载"
        with self.publication_lock:
            self._stored_view = None

    def read_view(self) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        "在同一读取视图中合并正式事件、草稿与包含关系"
        with self.publication_lock:
            stored = self._stored_view if self.cache_reads else None
            if stored is None:
                stored = (
                    _run_event_dicts(self.session, self.run_id),
                    {
                        row.contained_child_id: row.contained_parent_id
                        for row in self.session.reads.event_trees_organization_parents_1(self.run_id)
                        if row.contained_child_id is not None and row.contained_parent_id is not None
                    },
                )
                if self.cache_reads:
                    self._stored_view = stored
            with self.lock:
                events, parents = deepcopy(stored)
                events.update({key: item.model_dump(mode="json") for key, item in self.events.items()})
                for edge in self.containments.values():
                    prior = parents.get(edge.child_event_id)
                    if prior is not None and prior != edge.parent_event_id:
                        raise CandidateConflict(
                            f"包含候选存在多个直接父: child_event_id={edge.child_event_id}",
                            [item.producer_agent_id for item in self.containments.values()
                             if item.child_event_id == edge.child_event_id],
                        )
                    parents[edge.child_event_id] = edge.parent_event_id
                return events, parents

    @staticmethod
    def _event_hierarchy(event_id: str, parents: dict[str, str]) -> dict[str, Any]:
        """由实际包含关系给出合法结果端点，不把子事件贡献自动改挂到父事件"""
        root = event_id
        seen: set[str] = set()
        while root in parents:
            if root in seen:
                raise ValueError(f"完整事件包含关系形成环: {root}")
            seen.add(root)
            root = parents[root]
        return {
            "parent_event_id": parents.get(event_id),
            "top_level_event_id": root,
            "is_top_level": event_id == root,
        }

    def search_events(
        self,
        query: str = "",
        *,
        top_level_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """分页返回本次草稿与正式事件，零事件时也可从过程读取开始"""
        _page_size(limit)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        by_id, parents = self.read_view()
        rows = [
            {**item, **self._event_hierarchy(key, parents)}
            for key, item in by_id.items()
            if (not top_level_only or key not in parents)
            and (
                not query
                or query.casefold()
                in " ".join(str(item[field]) for field in ("title", "problem", "summary")).casefold()
            )
        ]
        rows.sort(key=lambda item: (item["first_text_position"] or 0, item["event_id"]))
        return {
            "items": rows[offset : offset + limit],
            "total": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
        }

    def read_events(self, event_ids: list[str]) -> list[dict[str, Any]]:
        _page_size(len(event_ids))
        by_id, parents = self.read_view()
        missing = sorted(set(event_ids) - set(by_id))
        if missing:
            raise ValueError(f"本任务事件不存在: {missing}")
        return [
            {
                **by_id[key],
                **self._event_hierarchy(key, parents),
                "direct_child_event_ids": [child for child, parent in parents.items() if parent == key],
            }
            for key in event_ids
        ]

    def _source(self) -> dict[str, Any]:
        if not self.producer_agent_id:
            raise ValueError("诊断贡献缺少真实生产者")
        return {"producer_agent_id": self.producer_agent_id}

    def _require_free_key(self, key: str, event_id: str) -> None:
        """局部键在同一执行内唯一：被其他事件占用时拒收，同一事件重发放行"""
        holder = next(
            (
                item
                for item in self.events.values()
                if item.producer_agent_id == self.producer_agent_id and item.local_key == key
            ),
            None,
        )
        if holder is not None and holder.event_id != event_id:
            raise ValueError(
                f"局部键已被本执行的其他事件占用: key={key} event_id={holder.event_id} title={holder.title}；"
                "同一执行内局部键必须唯一且不随章节、批次重置；请换用未占用的键（建议由事件 id 派生），"
                "或复用、撤回占用的候选后重新提交"
            )

    def retract(
        self,
        *,
        kind: Literal["contain", "relation"],
        identifier: str,
        reason: str,
        evidence: list[OrganizationEvidence],
    ) -> None:
        """撤回当前生产者尚未保存的包含或关系候选"""
        if kind not in {"contain", "relation"}:
            raise ValueError("只允许撤回包含或关系候选")
        if not reason.strip():
            raise ValueError("撤回须明确理由")
        self.bind_evidence(evidence)
        records: Any = {"contain": self.containments, "relation": self.relations}[kind]
        key: Any = tuple(identifier.split("/", 1)) if kind == "contain" else identifier
        item = records.get(key)
        if item is None or item.producer_agent_id != self.producer_agent_id:
            raise ValueError("只能撤回当前生产者的实际候选")
        saved = self.session.reads.event_trees_organization_parents_1(self.run_id) if kind == "contain" else []
        if any((row.contained_parent_id, row.contained_child_id) == key for row in saved):
            raise ValueError("已保存的包含关系不可撤回")
        if kind == "relation" and identifier in self.saved_relation_ids:
            raise ValueError("已保存的事件关系不可撤回")
        del records[key]

    def event(
        self,
        *,
        key: str,
        title: str,
        problem: str,
        summary: str,
        event_type: str,
        status: Literal["ongoing", "resolved"],
        reason: str,
        from_chapter_id: int,
        to_chapter_id: int,
        evidence: list[OrganizationEvidence],
        progress: str | None = None,
    ) -> dict[str, Any]:
        """依据正文创建不可变事件，起止章节独立于包含结构"""
        if not key.strip() or not reason.strip():
            raise ValueError("事件局部键和理由不能为空")
        self.session.narrative.validate_event_range(self.run_id, from_chapter_id, to_chapter_id)
        bound = self.bind_evidence(evidence)
        holder = next(
            (
                item
                for item in self.events.values()
                if item.producer_agent_id == self.producer_agent_id and item.local_key == key
            ),
            None,
        )
        event_id = (
            holder.event_id
            if holder is not None
            else self._identifier("event", self.run_id, self.producer_agent_id, key)
        )
        candidate = CompleteEventDraft(
            event_id=event_id,
            local_key=key,
            title=title,
            problem=problem,
            summary=summary,
            event_type=event_type,
            status=status,
            progress=progress,
            reason=reason,
            from_chapter_id=from_chapter_id,
            to_chapter_id=to_chapter_id,
            first_text_position=self._first_position(bound),
            evidence=bound,
            **self._source(),
        )
        self._require_free_key(key, event_id)
        if event_id in self.events and self.events[event_id] != candidate:
            raise ValueError("已接受事件不能被其他操作覆盖")
        self.events[event_id] = candidate
        return {"status": "accepted_candidate", "event_id": event_id}

    def contain(
        self, *, parent_event_id: str, child_event_id: str, reason: str, evidence: list[OrganizationEvidence]
    ) -> None:
        self.read_events([parent_event_id, child_event_id])
        if parent_event_id == child_event_id:
            raise ValueError("事件不能包含自身")
        # 一个子事件只能有一个直接父、包含不成环，
        # 冲突的第二份包含在提交时拒收，由模型在原会话内改判
        parents = self._parents()
        holder = parents.get(child_event_id)
        if holder is not None and holder != parent_event_id:
            raise ValueError(
                f"子事件已有直接父: child_event_id={child_event_id} parent_event_id={holder}；"
                "一个子事件只能有一个直接父，改挂须先撤回原包含候选"
            )
        cursor: str | None = parent_event_id
        seen: set[str] = set()
        while cursor is not None:
            if cursor == child_event_id:
                raise ValueError(f"包含与既有包含关系成环: parent={parent_event_id} child={child_event_id}")
            if cursor in seen:
                break
            seen.add(cursor)
            cursor = parents.get(cursor)
        edge = ContainmentDraft(
            parent_event_id=parent_event_id,
            child_event_id=child_event_id,
            reason=reason,
            evidence=self.bind_evidence(evidence),
            **self._source(),
        )
        previous = self.containments.get((parent_event_id, child_event_id))
        if previous is not None and previous.producer_agent_id != self.producer_agent_id:
            raise ValueError("不能覆盖其他生产者提交的包含候选，请引用原判断或显式交接")
        self.containments = {**self.containments, (parent_event_id, child_event_id): edge}


    def validate_events(self, events: dict[str, CompleteEventDraft] | None = None) -> None:
        """校验事件章节身份、正文证据与包含端点"""
        events = self.events if events is None else events
        for event in events.values():
            self.session.narrative.validate_event_range(self.run_id, event.from_chapter_id, event.to_chapter_id)
        all_ids = set(self._all_events()) | set(events)
        parents = self._parents()
        for child, parent in parents.items():
            if child not in all_ids or parent not in all_ids:
                raise ValueError("包含端点不属于本运行")
            self._event_hierarchy(child, parents)

    def relate_events(
        self,
        *,
        key: str,
        source_kind: Literal["event"],
        source_id: str,
        target_kind: Literal["event"],
        target_id: str,
        relation_type: str,
        reason: str,
        evidence: list[OrganizationEvidence],
    ) -> str:
        self.read_events([source_id, target_id])
        if relation_type in {"main", "secondary", "contains", "containment", "same_identity"}:
            raise ValueError("身份、包含及旧主链标记不能伪装为普通事件关系")
        relation_id = self._identifier("event_relation", self.run_id, self.producer_agent_id, key)
        self.relations[relation_id] = RelationDraft(
            relation_id=relation_id,
            source_kind=source_kind,
            source_id=source_id,
            target_kind=target_kind,
            target_id=target_id,
            relation_type=relation_type,
            reason=reason,
            evidence=self.bind_evidence(evidence),
            source_operation_id=key,
            **self._source(),
        )
        return relation_id

    def read_passages(self, paragraph_ids: list[int], offset: int = 0, limit: int = 10) -> dict[str, Any]:
        """有界读取真实原文；段号从工具回执获得，长段落按字符续读"""
        _page_size(len(paragraph_ids), 20)
        _page_size(limit, 20)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        rows = self.session.reads.event_trees_organization_read_passages_1(paragraph_ids, self.run_id)
        if set(paragraph_ids) - {row.paragraph_id for row in rows}:
            raise ValueError("本任务原文段落不存在")
        return {
            "items": [
                {
                    "paragraph_id": row.paragraph_id,
                    "chapter_id": row.chapter_id,
                    "text": row.text[offset : offset + 2000],
                    "next_offset": offset + 2000 if len(row.text) > offset + 2000 else None,
                }
                for row in rows[:limit]
            ]
        }

    def bind_evidence(self, evidence: list[OrganizationEvidence]) -> list[BoundOrganizationEvidence]:
        """沿用原文锚点的逐字绑定规则，不接受模型提交坐标或哈希"""
        _page_size(len(evidence))
        event_ids = list({item.event_id for item in evidence if item.event_id is not None})
        if event_ids:
            self.read_events(event_ids)
        paragraph_ids = {item.paragraph_id for item in evidence}
        paragraphs = _paragraph_rows(self.session, self.run_id, paragraph_ids)
        bound = []
        for item in evidence:
            row = paragraphs.get(item.paragraph_id)
            if row is None:
                raise ValueError(f"本任务原文段落不存在: {item.paragraph_id}")
            start, end = 0, len(row.text)
            if item.quote is not None:
                start = -1
                for _ in range(item.occurrence):
                    start = row.text.find(item.quote, start + 1)
                    if start < 0:
                        raise ValueError("quote 或 occurrence 不匹配原文")
                end = start + len(item.quote)
            elif item.occurrence != 1:
                raise ValueError("完整段落引用 occurrence 必须为 1")
            bound.append(
                BoundOrganizationEvidence(
                    event_id=item.event_id,
                    paragraph_id=row.paragraph_id,
                    chapter_id=row.chapter_id,
                    char_start=start,
                    char_end=end,
                    text_hash=text_digest(row.text[start:end]),
                )
            )
        return bound

    def _first_position(self, evidence: list[BoundOrganizationEvidence]) -> int:
        positions = _global_positions(self.session, self.run_id, {ref.paragraph_id for ref in evidence})
        return min(positions[ref.paragraph_id] + ref.char_start for ref in evidence)

    def register_arc(
        self,
        *,
        key: str,
        kind: Literal["main", "subplot"],
        title: str,
        objective: str,
        role: str,
        reason: str,
        evidence: list[OrganizationEvidence],
        parent_arc_id: str | None = None,
    ) -> str:
        """登记或修正叙事线，不据数量和局部树键推定主线"""
        if not key.strip():
            raise ValueError("叙事线稳定键不能为空")
        arc_id = self._identifier("narrative_arc", self.run_id, self.producer_agent_id, key)
        arc = NarrativeArcDraft(
            arc_id=arc_id,
            kind=kind,
            title=title,
            objective=objective,
            role=role,
            reason=reason,
            parent_arc_id=parent_arc_id,
            evidence=self.bind_evidence(evidence),
            **self._source(),
        )
        candidates = {**self.arcs, arc_id: arc}
        NarrativeOrganization(arcs=list(candidates.values()))
        self.arcs = candidates
        return arc_id


    def link_event_arc(
        self, *, event_id: str, arc_id: str, role: str, reason: str, evidence: list[OrganizationEvidence]
    ) -> None:
        """同一完整事件可关联多线，各项关系独立保存理由与证据"""
        self.read_events([event_id])
        if arc_id not in self.arcs:
            raise ValueError("叙事线关联端点不存在")
        link = EventArcLinkDraft(
            event_id=event_id,
            arc_id=arc_id,
            role=role,
            reason=reason,
            evidence=self.bind_evidence(evidence),
            **self._source(),
        )
        self.event_arc_links[(event_id, arc_id)] = link

    def register_outcome(self, *, key: str, title: str, description: str, evidence: list[OrganizationEvidence]) -> str:
        """结果身份由本轮稳定键派生，不包含任何来源事件身份"""
        if not key.strip():
            raise ValueError("结果稳定键不能为空")
        outcome_id = self._identifier("event_outcome", self.run_id, self.producer_agent_id, key)
        bound = self.bind_evidence(evidence)
        self.outcomes[outcome_id] = EventOutcomeDraft(
            outcome_id=outcome_id,
            title=title,
            description=description,
            evidence=bound,
            first_text_position=self._first_position(bound),
            **self._source(),
        )
        return outcome_id

    def link_event_outcome(
        self, *, event_id: str, outcome_id: str, reason: str, evidence: list[OrganizationEvidence]
    ) -> None:
        """结果贡献只接受顶层完整事件，关系证据不能省略或借用结果证据"""
        self.read_events([event_id])
        if outcome_id not in self.outcomes:
            raise ValueError("结果关联端点不存在")
        hierarchy = self._event_hierarchy(event_id, self._parents())
        if not hierarchy["is_top_level"]:
            raise ValueError(
                "全书结果贡献端点必须是顶层完整事件，子事件进展保存在章节产物中；"
                f"event_id={event_id}，parent_event_id={hierarchy['parent_event_id']}，"
                f"top_level_event_id={hierarchy['top_level_event_id']}。"
                "请核对顶层事件后重新提交该贡献的理由和证据，本次未自动替换端点"
            )
        link = EventOutcomeLinkDraft(
            event_id=event_id,
            outcome_id=outcome_id,
            reason=reason,
            evidence=self.bind_evidence(evidence),
            **self._source(),
        )
        self.event_outcome_links[(event_id, outcome_id)] = link

    def _validate_subject(self, kind: str, subject_id: str) -> None:
        if kind == "event":
            self.read_events([subject_id])
        elif kind == "fact":
            try:
                fact_id = str(subject_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("冲突事实主体必须是正式图谱事实流水号") from exc
            row = self.session.reads.event_trees_organization_validate_subject_1(fact_id)
            producer_agent_id = None if row is None else row.direct_producer_agent_id
            if producer_agent_id is None or not _execution_in_run(self.session, producer_agent_id, self.run_id):
                raise ValueError("冲突事实主体不存在或不属于本 run")
        else:
            raise ValueError("冲突主体类型无效")

    def read_draft(self, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """分页读取事件、关系、叙事线及结果"""
        _page_size(limit)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        groups: dict[str, list[BaseModel]] = {
            "events": list(self.events.values()),
            "relations": list(self.relations.values()),
            "arcs": list(self.arcs.values()),
            "event_arc_links": list(self.event_arc_links.values()),
            "outcomes": list(self.outcomes.values()),
            "event_outcome_links": list(self.event_outcome_links.values()),
        }
        return {
            **{
                name: [item.model_dump(mode="json") for item in values[offset : offset + limit]]
                for name, values in groups.items()
            },
            "totals": {name: len(values) for name, values in groups.items()},
        }


    def content_digest(self) -> str:
        """按事件正文和章节范围计算保存快照"""
        return snapshot_digest(record_payloads(self.events.values()))

    def structure_digest(self) -> str:
        """结构摘要：按当前事件、包含与关系实时计算，用于报告绑定与保存快照"""
        return snapshot_digest(
            {
                "events": record_payloads(self.events.values()),
                "containments": record_payloads(self.containments.values()),
                "relations": record_payloads(self.relations.values()),
            }
        )

    def finish(self) -> NarrativeOrganization:
        self.validate_events()
        self.content_snapshot = self.content_digest()
        self.structure_snapshot = self.structure_digest()
        result = NarrativeOrganization(
            source_agent_id=self.agent_id,
            events=list(self.events.values()),
            relations=list(self.relations.values()),
            arcs=list(self.arcs.values()),
            event_arc_links=list(self.event_arc_links.values()),
            outcomes=list(self.outcomes.values()),
            event_outcome_links=list(self.event_outcome_links.values()),
            containments=list(self.containments.values()),
            content_snapshot=self.content_snapshot,
            structure_snapshot=self.structure_snapshot,
        )
        validate_organization(self.session, self.run_id, result)
        return result


def _execution_in_run(session: Storage, agent_id: str, run_id: str) -> bool:
    """真实执行的本 run 归属：调用形状直接带 run，整轮会话形状带 session_run"""
    return smap.execution_in_run(session, agent_id, run_id)


def _annotation_chapter_of_execution(session: Storage, agent_id: str) -> tuple[int | None, int | None]:
    """章级伏笔动作的来源章序：从其真实生产执行的记录归属与章节取得"""
    return smap.annotation_chapter_of_execution(session, agent_id)


def validate_organization(session: Storage, run_id: str, organization: NarrativeOrganization) -> None:
    """保存前校验同 run 端点、独立结果及每项真实证据"""
    organization = NarrativeOrganization.model_validate(organization.model_dump())
    all_ids = set(_run_events(session, run_id))
    all_ids.update(item.event_id for item in organization.events)
    draft = EventOrganizationDraft(session, run_id)
    draft.events = {item.event_id: item for item in organization.events}
    draft.containments = {(item.parent_event_id, item.child_event_id): item for item in organization.containments}
    draft.relations = {item.relation_id: item for item in organization.relations}
    draft.validate_events()
    if draft.content_digest() != organization.content_snapshot:
        raise ValueError("身份快照与实际来源判断不一致")
    if draft.structure_digest() != organization.structure_snapshot:
        raise ValueError("结构快照与实际接受记录不一致")
    child_ids = set(draft._parents())
    for linked_event_id in [item.event_id for item in organization.event_arc_links] + [
        item.event_id for item in organization.event_outcome_links
    ]:
        if linked_event_id not in all_ids:
            raise ValueError("关联完整事件端点不属于本 run")
    if child_ids & {link.event_id for link in organization.event_outcome_links}:
        raise ValueError("全书结果贡献端点必须是顶层完整事件")
    refs = [
        ref
        for records in (
            organization.events,
            organization.relations,
            organization.arcs,
            organization.outcomes,
            organization.event_arc_links,
            organization.event_outcome_links,
            organization.containments,
        )
        for item in records
        for ref in item.evidence
    ]
    for records in (
        organization.events,
        organization.containments,
        organization.relations,
        organization.arcs,
        organization.event_arc_links,
        organization.outcomes,
        organization.event_outcome_links,
    ):
        for record in records:
            if not record.producer_agent_id:
                raise ValueError("诊断贡献缺少真实 Agent 写出者")
    paragraphs = _paragraph_rows(session, run_id, {ref.paragraph_id for ref in refs})
    for ref in refs:
        row = paragraphs.get(ref.paragraph_id)
        if (
            row is None
            or int(row.chapter_id) != ref.chapter_id
            or ref.char_end > len(row.text)
            or text_digest(row.text[ref.char_start : ref.char_end]) != ref.text_hash
        ):
            raise ValueError("组织证据坐标或哈希与本 run 原文不一致")
        if ref.event_id is not None and ref.event_id not in all_ids:
            raise ValueError("组织证据引用的完整事件不属于本 run")
    positioned_records: list[CompleteEventDraft | EventOutcomeDraft] = [*organization.events, *organization.outcomes]
    positions = _global_positions(session, run_id, {ref.paragraph_id for ref in refs})
    for outcome in positioned_records:
        if outcome.first_text_position != min(positions[ref.paragraph_id] + ref.char_start for ref in outcome.evidence):
            raise ValueError("结果正文排序位置必须由证据派生")
