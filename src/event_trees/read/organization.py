"正式事件、声明及原文证据的只读投影"

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, cast

from src.event_trees import storage_map as smap
from src.fact_graph.read.references import EntityReferenceProjection
from src.storage import Storage
from src.storage.records.models import ChapterAnnotationRecord as ChapterAnnotation
from src.storage.records.models import DiagnosisReportRecord as DiagnosisReport
from src.storage.records.models import NarrativeLinkRecord as NarrativeLink
from src.utils.identity import text_digest


class RunRequiresRebuildError(ValueError):
    """旧契约运行不接受读取层转换，必须修正正式链后从原文重建"""

    def __init__(self) -> None:
        super().__init__("该运行为旧契约，需要从原文重建")


@dataclass(frozen=True)
class EventView:
    """完整事件的读取投影：身份 + 真实生产者 + 全书事件正文与整体证据"""

    event_id: str
    producer_agent_id: str
    local_key: str
    identity_reason: str
    title: str | None
    problem: str | None
    summary: str | None
    event_type: str | None
    status: str | None
    progress: str | None
    first_text_position: int | None
    evidence: list[dict[str, Any]]
    source_agent_id: str | None


@dataclass(frozen=True)
class DeclarationView:
    """不可变章级声明：来源记录/章节与参与者/证据均为读取投影"""

    declaration_id: str
    record_id: str
    local_key: str
    title: str
    problem: str
    summary: str
    event_type: str
    status: str
    progress: str | None
    is_foreshadowing_root: bool
    payoff_likelihood: str | None
    strength: str | None
    participants: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    char_start: int
    char_end: int
    chapter_id: int | None
    chapter_order: int | None
    producer_agent_id: str | None

    @property
    def event_id(self) -> str:
        """来源身份的旧调用别名（等于 declaration_id，不是正式事件身份）"""
        return self.declaration_id

    @property
    def annotation_id(self) -> str:
        return self.record_id

    @property
    def payload_path(self) -> str:
        return f"declaration/{self.declaration_id}"

    @property
    def first_text_position(self) -> int:
        return self.char_start


@dataclass(frozen=True)
class LinkView:
    """语义/因果链路的读取形状（两端都引用完整事件或声明）"""

    relation_id: str
    source_kind: str
    source_id: str
    target_kind: str
    target_id: str
    relation_type: str
    reason: str
    evidence: list[dict[str, Any]]
    producer_agent_id: str
    source_operation_id: str | None


@dataclass(frozen=True)
class GroupView:
    """叙事线读取形状（parent_arc_id 仅线→线）"""

    arc_id: str
    parent_arc_id: str | None
    kind: str
    title: str
    objective: str
    role: str
    reason: str
    evidence: list[dict[str, Any]]
    producer_agent_id: str


@dataclass(frozen=True)
class OutcomeView:
    """事件结果读取形状"""

    outcome_id: str
    title: str
    description: str
    first_text_position: int
    evidence: list[dict[str, Any]]
    producer_agent_id: str


@dataclass(frozen=True)
class ArcLinkView:
    event_id: str
    arc_id: str
    role: str
    reason: str
    evidence: list[dict[str, Any]]


@dataclass(frozen=True)
class OutcomeLinkView:
    event_id: str
    outcome_id: str
    reason: str
    evidence: list[dict[str, Any]]


@dataclass(frozen=True)
class BindingView:
    declaration_id: str
    event_id: str
    producer_agent_id: str


@dataclass(frozen=True)
class ForeshadowingView:
    """伏笔动作的读取形状（旧 foreshadowing_actions 载荷字段保持）"""

    action_id: str
    action_type: str
    endpoint_kind: str
    root_event_id: str
    target_event_id: str | None
    chapter_id: int | None
    chapter_order: int | None
    source_operation_id: str
    evidence: list[dict[str, Any]]
    operation_order: int = 0
    evidence_scope: str = "paragraph"


def _event_sort_key(event: EventView) -> tuple[bool, int, str]:
    return (event.first_text_position is None, event.first_text_position or 0, event.event_id)


def _containment_child_id(row: NarrativeLink) -> str:
    """包含关系的子端身份：ck_narrative_links_shape 保证包含形状子端非空"""
    return cast(str, row.contained_child_id)


def _containment_parent_id(row: NarrativeLink) -> str:
    """包含关系的父端身份：ck_narrative_links_shape 保证包含形状父端非空"""
    return cast(str, row.contained_parent_id)


class EventTreeQuery:
    """全书事件树契约查询：fetch 分页顶层大事件，detail 输出同结构事件卡"""

    def __init__(self, session: Storage, run_id: str) -> None:
        self.session, self.run_id = session, run_id
        self._loaded = False
        self._containment_links: list[NarrativeLink] = []
        self._declaration_executions: dict[str, str] = {}

    # ------------------------------------------------------------------
    # 加载与契约校验
    # ------------------------------------------------------------------

    def _load_annotations(self) -> list[ChapterAnnotation]:
        return list(self.session.reads.event_trees_read_organization_load_annotations_1(self.run_id))

    def _load_report(self) -> DiagnosisReport | None:
        return self.session.reads.event_trees_read_organization_load_report_1(self.run_id)

    def _load(self) -> None:
        if self._loaded:
            return
        annotations = self._load_annotations()
        report = self._load_report()
        contract_outputs = bool(annotations) or report is not None
        self.organization_status = "ready" if report is not None else "pending_diagnosis"
        # 章节/段落基础投影先于声明与事件：声明章号与证据坐标都依赖它
        self.chapters: list[dict[str, Any]] = [
            {"chapter_id": row.chapter_id, "title": row.display_title or row.title, "chapter_order": int(row.sequence)}
            for index, row in enumerate(self.session.reads.event_trees_read_organization_load_2(self.run_id))
        ]
        self.orders: dict[int, int] = {row["chapter_id"]: row["chapter_order"] for row in self.chapters}
        self.paragraphs = {
            row.paragraph_id: row for row in self.session.reads.event_trees_read_organization_load_1(self.run_id)
        }
        self.events = self._load_events()
        self.declarations = self._load_declarations(annotations)
        self._load_containments()
        self.bindings = self._load_bindings()
        # 已有事件或声明必须保留正式来源产物
        if not contract_outputs and (self.declarations or self.events or self.bindings):
            raise RunRequiresRebuildError()
        self.entity_projection = EntityReferenceProjection.load(self.session, self.run_id)
        self._load_organization()
        self.actions = (
            [self._action_view(row) for row in self._action_rows] if self.organization_status == "ready" else []
        )
        self._validate_saved_contract()
        self._loaded = True

    def _load_events(self) -> dict[str, EventView]:
        event_rows = smap.run_events(self.session, self.run_id)
        if not event_rows:
            return {}
        event_ids = list(event_rows)
        evidence = smap.fetch_evidence(self.session, "complete_event_id", event_ids)
        result: dict[str, EventView] = {}
        for event_id, row in event_rows.items():
            payloads = smap.evidence_payloads(self.session, self.run_id, evidence.get(event_id, []))
            positions = (
                smap.global_positions(self.session, self.run_id, {item["paragraph_id"] for item in payloads})
                if payloads
                else {}
            )
            result[event_id] = EventView(
                event_id=event_id,
                producer_agent_id=row.producer_agent_id,
                local_key=row.local_key,
                identity_reason=row.identity_reason,
                title=row.title,
                problem=row.problem,
                summary=row.summary,
                event_type=row.event_type,
                status=row.status,
                progress=row.progress,
                first_text_position=(
                    min(positions[item["paragraph_id"]] + item["char_start"] for item in payloads) if payloads else None
                ),
                evidence=payloads,
                source_agent_id=row.producer_agent_id,
            )
        return result

    def _load_containments(self) -> None:
        self._containment_links = list(
            self.session.reads.event_trees_read_organization_load_containments_1(self.run_id)
        )
        self.parent_of: dict[str, NarrativeLink] = {_containment_child_id(row): row for row in self._containment_links}
        children_of: dict[str, list[NarrativeLink]] = {}
        for row in self._containment_links:
            children_of.setdefault(_containment_parent_id(row), []).append(row)
        for rows in children_of.values():
            if any(
                row.contained_parent_id not in self.events or row.contained_child_id not in self.events for row in rows
            ):
                raise ValueError("已保存事件包含端点不属于当前运行")
            rows.sort(key=lambda row: _event_sort_key(self.events[_containment_child_id(row)]))
        self.children_of = children_of

    def _declaration_participants(self, declaration_ids: list[str]) -> dict[str, list[dict[str, Any]]]:

        result: dict[str, list[dict[str, Any]]] = {key: [] for key in declaration_ids}
        if not declaration_ids:
            return result
        rows = list(self.session.reads.event_trees_read_organization_declaration_participants_1(declaration_ids))
        names: dict[str, str] = {}
        if rows:
            names = {
                row.entity_id: row.canonical_name
                for row in self.session.reads.event_trees_read_organization_declaration_participants_2(rows)
            }
        for row in rows:
            result[row.declaration_id].append(
                {
                    "entity": {"name": names.get(row.entity_id, row.entity_id), "entity_id": row.entity_id},
                    "role": row.role,
                    "narrative_role": row.narrative_role,
                    "action": row.action,
                    "emotion": row.emotion,
                }
            )
        return result

    def _load_declarations(self, annotations: list[ChapterAnnotation]) -> dict[str, DeclarationView]:

        if not annotations:
            return {}
        records = {row.record_id: row for row in annotations}
        execution_by_record = {row.record_id: row.agent_id for row in annotations}
        declaration_rows = list(self.session.reads.event_trees_read_organization_load_declarations_1(records))
        declaration_ids = [row.declaration_id for row in declaration_rows]
        evidence = smap.fetch_evidence(self.session, "declaration_id", declaration_ids)
        participants = self._declaration_participants(declaration_ids)
        self._declaration_executions = {
            row.declaration_id: execution_by_record[row.record_id] for row in declaration_rows
        }
        result: dict[str, DeclarationView] = {}
        for row in declaration_rows:
            record = records[row.record_id]
            chapter_id = int(record.chapter_id) if record.chapter_id is not None else None
            bound = smap.evidence_payloads(self.session, self.run_id, evidence.get(row.declaration_id, []))
            if not bound:
                raise ValueError(f"声明缺少原文证据: {row.declaration_id}")
            result[row.declaration_id] = DeclarationView(
                declaration_id=row.declaration_id,
                record_id=row.record_id,
                local_key=row.local_key,
                title=row.title,
                problem=row.problem,
                summary=row.summary,
                event_type=row.event_type,
                status=row.status,
                progress=row.progress,
                is_foreshadowing_root=bool(row.is_foreshadowing_root),
                payoff_likelihood=row.payoff_likelihood,
                strength=row.payoff_likelihood,
                participants=participants.get(row.declaration_id, []),
                evidence=bound,
                char_start=bound[0]["char_start"],
                char_end=bound[0]["char_end"],
                chapter_id=chapter_id,
                chapter_order=self.orders.get(chapter_id) if chapter_id is not None else None,
                producer_agent_id=record.agent_id,
            )
        return result

    def _load_bindings(self) -> dict[str, BindingView]:
        rows = self.session.reads.event_trees_read_organization_load_bindings_1(list(self.events))
        return {
            row.declaration_id: BindingView(
                declaration_id=row.declaration_id,
                event_id=row.event_id,
                producer_agent_id=self.events[row.event_id].producer_agent_id,
            )
            for row in rows
        }

    def _load_organization(self) -> None:

        producer_executions = smap.run_execution_ids(self.session, self.run_id)
        groups = list(self.session.reads.event_trees_read_organization_load_organization_1(producer_executions))
        group_evidence = smap.fetch_evidence(self.session, "narrative_group_id", [row.group_id for row in groups])
        self.arcs = {
            row.group_id: GroupView(
                arc_id=row.group_id,
                parent_arc_id=row.parent_arc_id,
                kind=row.arc_kind,
                title=row.title,
                objective=cast(str, row.arc_objective),
                role=cast(str, row.arc_role),
                reason=cast(str, row.arc_reason),
                evidence=smap.evidence_payloads(self.session, self.run_id, group_evidence.get(row.group_id, [])),
                producer_agent_id=row.producer_agent_id,
            )
            for row in groups
            if row.arc_kind is not None
        }
        self.outcomes = {
            row.group_id: OutcomeView(
                outcome_id=row.group_id,
                title=row.title,
                description=row.outcome_description,
                first_text_position=self._first_evidence_position(group_evidence.get(row.group_id, [])),
                evidence=smap.evidence_payloads(self.session, self.run_id, group_evidence.get(row.group_id, [])),
                producer_agent_id=row.producer_agent_id,
            )
            for row in groups
            if row.outcome_description is not None
        }
        links = list(self.session.reads.event_trees_read_organization_load_organization_2(producer_executions))
        link_evidence = smap.fetch_evidence(self.session, "narrative_link_id", [row.link_id for row in links])
        self.arc_links: list[ArcLinkView] = []
        self.outcome_links: list[OutcomeLinkView] = []
        self.relations: list[LinkView] = []
        self.declaration_relations: list[LinkView] = []
        for row in links:
            evidence = smap.evidence_payloads(self.session, self.run_id, link_evidence.get(row.link_id, []))
            if row.arc_group_id is not None:
                self.arc_links.append(
                    ArcLinkView(
                        event_id=cast(str, row.member_event_id),
                        arc_id=row.arc_group_id,
                        role=cast(str, row.arc_role),
                        reason=row.reason,
                        evidence=evidence,
                    )
                )
            elif row.outcome_group_id is not None:
                self.outcome_links.append(
                    OutcomeLinkView(
                        event_id=cast(str, row.member_event_id),
                        outcome_id=row.outcome_group_id,
                        reason=row.reason,
                        evidence=evidence,
                    )
                )
            elif row.semantic_source_event_id is not None and row.semantic_target_event_id is not None:
                self.relations.append(
                    self._link_view(
                        row, "event", row.semantic_source_event_id, "event", row.semantic_target_event_id, evidence
                    )
                )
            elif row.semantic_source_declaration_id is not None and row.semantic_target_declaration_id is not None:
                self.declaration_relations.append(
                    self._link_view(
                        row,
                        "declaration",
                        row.semantic_source_declaration_id,
                        "declaration",
                        row.semantic_target_declaration_id,
                        evidence,
                    )
                )
        self.arc_links.sort(key=lambda row: (row.event_id, row.arc_id))
        self.outcome_links.sort(key=lambda row: (row.event_id, row.outcome_id))
        self.relations.sort(key=lambda row: row.relation_id)
        self.declaration_relations.sort(key=lambda row: row.relation_id)
        self._action_rows = self._load_actions()

    def _link_view(
        self,
        row: NarrativeLink,
        source_kind: str,
        source_id: str,
        target_kind: str,
        target_id: str,
        evidence: list[dict[str, Any]],
    ) -> LinkView:
        return LinkView(
            relation_id=row.link_id,
            source_kind=source_kind,
            source_id=source_id,
            target_kind=target_kind,
            target_id=target_id,
            relation_type=row.relation_type or "",
            reason=row.reason,
            evidence=evidence,
            producer_agent_id=row.producer_agent_id,
            source_operation_id=row.source_operation_local_key,
        )

    def _first_evidence_position(self, rows: list[Any]) -> int:
        if not rows:
            return 0
        payloads = smap.evidence_payloads(self.session, self.run_id, rows)
        positions = smap.global_positions(self.session, self.run_id, {item["paragraph_id"] for item in payloads})
        return min(positions[item["paragraph_id"]] + item["char_start"] for item in payloads)

    def _load_actions(self):
        from src.event_trees.action_order import load_foreshadowing_actions

        return load_foreshadowing_actions(self.session, self.run_id)

    def _action_view(self, row: Any) -> ForeshadowingView:
        if row.root_event_id is None:
            raise ValueError("已发布伏笔缺少正式事件身份")
        return ForeshadowingView(
            action_id=row.action_id,
            action_type=row.action_type,
            endpoint_kind="event",
            root_event_id=row.root_event_id,
            target_event_id=row.target_event_id,
            chapter_id=row.chapter_id,
            chapter_order=row.chapter_order,
            source_operation_id=row.source_operation_id,
            evidence=row.evidence,
            operation_order=int(row.operation_order),
            evidence_scope=row.evidence_scope,
        )

    # ------------------------------------------------------------------
    # 契约校验
    # ------------------------------------------------------------------

    def _validate_evidence(self, evidence: list[dict[str, Any]]) -> None:
        """拒绝失效来源，不在 GET 中补造段落、坐标或引文"""
        if not evidence:
            raise ValueError("已保存对象缺少原文证据，需要从原文重建")
        for item in evidence:
            chapter_id = item.get("chapter_id")
            if chapter_id not in self.orders:
                raise ValueError("已保存证据章节不属于当前运行")
            if item.get("paragraph_id") is None:
                continue
            paragraph = self.paragraphs.get(item["paragraph_id"])
            if paragraph is None or paragraph.chapter_id != chapter_id:
                raise ValueError("已保存证据段落不属于来源章节")
            start, end = item.get("char_start", 0), item.get("char_end", len(paragraph.text))
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(paragraph.text):
                raise ValueError("已保存证据字符范围与原文不一致")
            if item.get("text_hash") and item["text_hash"] != text_digest(paragraph.text[start:end]):
                raise ValueError("已保存证据文本校验不一致")

    def _containment_evidence_payloads(self) -> list[list[dict[str, Any]]]:

        rows = smap.fetch_evidence(self.session, "narrative_link_id", [row.link_id for row in self._containment_links])
        return [
            smap.evidence_payloads(self.session, self.run_id, rows.get(row.link_id, []))
            for row in self._containment_links
        ]

    def _validate_saved_contract(self) -> None:
        "核验正式对象、来源与关系端点"
        # 案例会话逐案写正式树、报告最后落库：报告未存不代表树必须为空，按已有对象校验
        if self.organization_status == "ready" and set(self.bindings) != set(self.declarations):
            raise ValueError("已发布事件声明缺少完整的正式身份绑定")
        for binding in self.bindings.values():
            if binding.event_id not in self.events or binding.declaration_id not in self.declarations:
                raise ValueError("已发布声明归属与真实来源不一致")
        for event in self.events.values():
            if not all((event.title, event.problem, event.summary, event.event_type, event.status)):
                raise ValueError("全书事件缺少正式正文")
            self._ancestry(event.event_id)
        for link in self.arc_links:
            if link.event_id not in self.events or link.arc_id not in self.arcs:
                raise ValueError("已保存事件叙事线关联端点无效")
        for outcome_link in self.outcome_links:
            if outcome_link.event_id not in self.events or outcome_link.outcome_id not in self.outcomes:
                raise ValueError("已保存事件结果关联端点无效")
            if outcome_link.event_id in self.parent_of:
                raise ValueError("已保存全书结果关联必须指向顶层大事件")
        for relation in self.relations:
            self._locate("event", relation.source_id)
            self._locate("event", relation.target_id)
        for relation in self.declaration_relations:
            self._locate("declaration", relation.source_id)
            self._locate("declaration", relation.target_id)
        for action in self.actions:
            self._locate("event", action.root_event_id)
            if action.target_event_id is not None:
                self._locate("event", action.target_event_id)
        for evidence in [
            *(row.evidence for row in self.events.values()),
            *(row.evidence for row in self.declarations.values()),
            *self._containment_evidence_payloads(),
            *(row.evidence for row in self.arcs.values()),
            *(row.evidence for row in self.arc_links),
            *(row.evidence for row in self.outcomes.values()),
            *(row.evidence for row in self.outcome_links),
            *(row.evidence for row in self.relations),
            *(row.evidence for row in self.declaration_relations),
            *(row.evidence for row in self.actions),
        ]:
            self._validate_evidence(evidence)

    # ------------------------------------------------------------------
    # 位置与祖先
    # ------------------------------------------------------------------

    def _ancestry(self, event_id: str) -> list[str]:
        """沿单父包含上溯到顶层，返回自顶向下的祖先事件 id（不含自身）"""
        chain: list[str] = []
        current = event_id
        while current in self.parent_of:
            parent_id = _containment_parent_id(self.parent_of[current])
            if parent_id in chain:
                raise ValueError("已保存包含路径无效")
            chain.append(parent_id)
            current = parent_id
        return list(reversed(chain))

    def _first_evidence_chapter(self, evidence: list[dict[str, Any]]) -> int | None:
        chapter_ids = [item["chapter_id"] for item in evidence if item.get("chapter_id") in self.orders]
        return min(chapter_ids, key=lambda chapter_id: self.orders[chapter_id]) if chapter_ids else None

    def _event_entry(self, event: EventView) -> dict[str, Any]:
        chapter_id = self._first_evidence_chapter(event.evidence)
        return {
            "event_id": event.event_id,
            "title": event.title,
            "summary": event.summary,
            "event_type": event.event_type,
            "status": event.status,
            "first_text_position": event.first_text_position,
            "chapter_id": chapter_id,
            "chapter_order": self.orders.get(chapter_id) if chapter_id is not None else None,
        }

    def _locate(self, kind: str, endpoint_id: str) -> dict[str, Any]:
        """正式关系直接定位事件；声明仅提供原始贡献定位"""
        if kind == "event":
            event = self.events.get(endpoint_id)
            if event is None:
                raise ValueError("已保存关系的完整事件端点不属于当前运行")
            ancestry = self._ancestry(endpoint_id)
            return {
                "top_level_event_id": ancestry[0] if ancestry else endpoint_id,
                "ancestor_event_ids": ancestry,
                "evidence_position": event.first_text_position,
            }
        if kind != "declaration":
            raise ValueError("已保存关系端点类型无效")
        declaration = self.declarations.get(endpoint_id)
        if declaration is None:
            raise ValueError("声明来源不属于当前运行")
        return {
            "top_level_event_id": None,
            "ancestor_event_ids": [],
            "evidence_position": declaration.char_start,
        }

    def _relation_entry(self, relation: LinkView, *, locate: tuple[str, str]) -> dict[str, Any]:
        if relation.source_kind != "event" or relation.target_kind != "event":
            raise ValueError("正式事件关系必须直接引用正式事件")
        kind, endpoint_id = locate
        location = self._locate(kind, endpoint_id)
        return {
            "relation_id": relation.relation_id,
            "source_kind": relation.source_kind,
            "source_id": relation.source_id,
            "target_kind": relation.target_kind,
            "target_id": relation.target_id,
            "relation_type": relation.relation_type,
            "reason": relation.reason,
            "evidence": relation.evidence,
            **location,
            "locator": {
                "target_kind": kind,
                "target_id": endpoint_id,
                "title": self.events[endpoint_id].title,
                **location,
            },
        }

    def _counts(self) -> dict[str, int]:
        top_level = sum(1 for event in self.events.values() if event.event_id not in self.parent_of)
        return {
            "top_level_events": top_level,
            "child_events": len(self.events) - top_level,
            "all_events": len(self.events),
            "declarations": len(self.declarations),
            "outcomes": len(self.outcomes),
            "event_outcome_links": len(self.outcome_links),
            "arcs": len(self.arcs),
            "event_arc_links": len(self.arc_links),
            "relations": len(self.relations),
            "foreshadowing_actions": len(self.actions),
        }

    def _payload(self, events_page: list[EventView], next_cursor: str | None) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "organization_status": self.organization_status,
            "chapters": self.chapters,
            "counts": self._counts(),
            "arcs": [
                {
                    "arc_id": arc.arc_id,
                    "parent_arc_id": arc.parent_arc_id,
                    "kind": arc.kind,
                    "title": arc.title,
                    "objective": arc.objective,
                    "evidence": arc.evidence,
                }
                for arc in self.arcs.values()
            ],
            "events": [self._event_entry(event) for event in events_page],
            "outcomes": [
                {
                    "outcome_id": outcome.outcome_id,
                    "title": outcome.title,
                    "description": outcome.description,
                    "first_text_position": outcome.first_text_position,
                    "evidence": outcome.evidence,
                }
                for outcome in sorted(
                    self.outcomes.values(),
                    key=lambda item: (item.first_text_position is None, item.first_text_position or 0, item.outcome_id),
                )
            ],
            "event_arc_links": [
                {
                    "event_id": link.event_id,
                    "arc_id": link.arc_id,
                    "role": link.role,
                    "reason": link.reason,
                    "evidence": link.evidence,
                }
                for link in self.arc_links
            ],
            "event_outcome_links": [
                {
                    "event_id": link.event_id,
                    "outcome_id": link.outcome_id,
                    "reason": link.reason,
                    "evidence": link.evidence,
                }
                for link in self.outcome_links
            ],
            "relations": [
                self._relation_entry(relation, locate=(relation.target_kind, relation.target_id))
                for relation in self.relations
            ],
            "foreshadowing_actions": [
                {
                    "action_id": action.action_id,
                    "action_type": action.action_type,
                    "endpoint_kind": "event",
                    "root_event_id": action.root_event_id,
                    "target_event_id": action.target_event_id,
                    "chapter_id": action.chapter_id,
                    "chapter_order": action.chapter_order,
                    "source_operation_id": action.source_operation_id,
                    "evidence": action.evidence,
                    "evidence_scope": action.evidence_scope,
                }
                for action in self.actions
            ],
            "next_cursor": next_cursor,
        }

    def fetch(self, *, cursor: str | None = None, limit: int = 100) -> dict[str, Any]:
        """仅顶层大事件分页；叙事线、结果、关联、关系、动作与计数每页完整返回"""
        if not 1 <= limit <= 500:
            raise ValueError("分页大小必须在1到500之间")
        self._load()
        top_level = sorted(
            (event for event in self.events.values() if event.event_id not in self.parent_of), key=_event_sort_key
        )
        context: list[Any] = [self.run_id, "events"]
        offset = 0
        if cursor:
            try:
                data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                if data["query"] != context or type(data["offset"]) is not int or data["offset"] < 0:
                    raise ValueError
                offset = data["offset"]
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                raise ValueError("分页游标与当前事件树条件不匹配") from exc
        page = top_level[offset : offset + limit]
        next_cursor = (
            base64.urlsafe_b64encode(json.dumps({"query": context, "offset": offset + limit}).encode()).decode()
            if offset + limit < len(top_level)
            else None
        )
        return self._payload(page, next_cursor)

    def detail(self, node_id: str) -> dict[str, Any]:
        """同结构事件卡：各级完整事件同一 DTO，子事件经父卡逐级访问"""
        self._load()
        event = self.events.get(node_id)
        if event is None:
            raise LookupError("NODE_NOT_FOUND")
        evidence = list(
            {
                json.dumps(item, sort_keys=True, ensure_ascii=False): item
                for item in [*event.evidence, *self._source_evidence(event)]
            }.values()
        )
        characters: dict[str, dict[str, Any]] = {}
        for source in self._sources(event):
            for participant in self.entity_projection.participants(source.participants):
                entity = participant.get("entity") or {}
                if entity.get("entity_type") != "character" or entity.get("entity_id") in characters:
                    continue
                characters[entity["entity_id"]] = {
                    "entity_id": entity["entity_id"],
                    "name": entity.get("name"),
                    "role": participant.get("role"),
                }
        ancestry = self._ancestry(node_id)
        return {
            "kind": "event",
            "event_id": event.event_id,
            "run_id": self.run_id,
            "title": event.title,
            "summary": event.summary,
            "progress": event.progress,
            "event_type": event.event_type,
            "status": event.status,
            "arcs": [
                {
                    "arc_id": link.arc_id,
                    "title": self.arcs[link.arc_id].title,
                    "kind": self.arcs[link.arc_id].kind,
                    "role": link.role,
                    "reason": link.reason,
                    "evidence": link.evidence,
                }
                for link in self.arc_links
                if link.event_id == node_id
            ],
            "characters": list(characters.values()),
            "direct_children": [
                {
                    "event_id": _containment_child_id(row),
                    "title": self.events[_containment_child_id(row)].title,
                    "event_type": self.events[_containment_child_id(row)].event_type,
                    "status": self.events[_containment_child_id(row)].status,
                }
                for row in self.children_of.get(node_id, [])
            ],
            "evidence": evidence,
            "evidence_scope": (
                "paragraph"
                if evidence and all(item.get("paragraph_id") is not None for item in evidence)
                else "chapter"
            ),
            "source_chapters": sorted(
                {item["chapter_id"] for item in evidence if item.get("chapter_id") in self.orders},
                key=lambda chapter_id: self.orders[chapter_id],
            ),
            "ancestry": ancestry,
            "relations": [
                self._relation_entry(
                    relation,
                    locate=(
                        (relation.target_kind, relation.target_id)
                        if relation.source_kind == "event" and relation.source_id == node_id
                        else (relation.source_kind, relation.source_id)
                    ),
                )
                for relation in self.relations
                if (relation.source_kind == "event" and relation.source_id == node_id)
                or (relation.target_kind == "event" and relation.target_id == node_id)
            ],
        }

    def _source_evidence(self, event: EventView) -> list[dict[str, Any]]:
        "读取完整事件归属的全部章级原文来源"
        return [item for source in self._sources(event) for item in source.evidence]

    def _sources(self, event: EventView) -> list[DeclarationView]:
        "按真实章节顺序读取全部声明，不生成阶段链"
        return sorted(
            (self.declarations[key] for key, binding in self.bindings.items() if binding.event_id == event.event_id),
            key=lambda row: (row.chapter_order or 0, row.char_start, row.declaration_id),
        )

    def chapter_detail(self, chapter_id: int, declaration_id: str) -> dict[str, Any]:
        "读取声明自身章节的正文与来源，完整事件仅返回归属身份"
        self._load()
        source = self.declarations.get(declaration_id)
        if source is None or source.chapter_id != chapter_id:
            raise LookupError("NODE_NOT_FOUND")
        binding = self.bindings.get(declaration_id)
        from src.fact_graph.read.storage_projection import graph_projection

        boundary = graph_projection(self.session.graph).resolve_chapter_boundary(self.run_id, chapter_id=chapter_id)
        if boundary is None:
            raise LookupError("NODE_NOT_FOUND")
        projection = EntityReferenceProjection.load(self.session, self.run_id, boundary=boundary)
        return {
            "run_id": self.run_id,
            "chapter_id": source.chapter_id,
            "declaration_id": source.declaration_id,
            "event_id": binding.event_id if binding else None,
            "title": source.title,
            "problem": source.problem,
            "summary": source.summary,
            "status": source.status,
            "progress": source.progress,
            "event_type": source.event_type,
            "participants": projection.participants(source.participants),
            "evidence": list(source.evidence),
        }

    def declaration_source(self, declaration_id: str) -> list[dict[str, Any]]:
        """仅追索不可变声明原文，不将声明包装成另一个正式事件"""
        self._load()
        if declaration_id not in self.declarations:
            raise LookupError("NODE_NOT_FOUND")
        return list(self.declarations[declaration_id].evidence)

    def declaration_locator(self, declaration_id: str) -> dict[str, Any]:
        """声明审计定位仅返回声明来源，不生成 owner 跳转"""
        self._load()
        if declaration_id not in self.declarations:
            raise LookupError("NODE_NOT_FOUND")
        return {
            "target_kind": "declaration",
            "target_id": declaration_id,
            "title": self.declarations[declaration_id].title,
            **self._locate("declaration", declaration_id),
        }

    def export(self) -> dict[str, Any]:
        """全量导出：fetch 不分页 + 各级事件详情，供结果导出服务使用"""
        self._load()
        top_level = sorted(
            (event for event in self.events.values() if event.event_id not in self.parent_of), key=_event_sort_key
        )
        result = self._payload(top_level, None)
        result["details"] = [self.detail(event.event_id) for event in sorted(self.events.values(), key=_event_sort_key)]
        result["complete_events"] = [
            {
                "event_id": event.event_id,
                "title": event.title,
                "problem": event.problem,
                "summary": event.summary,
                "progress": event.progress,
                "status": event.status,
                "event_type": event.event_type,
                "source_agent_id": event.source_agent_id,
                "producer_agent_id": event.producer_agent_id,
                "local_key": event.local_key,
                "evidence": event.evidence,
                "first_text_position": event.first_text_position,
            }
            for event in sorted(self.events.values(), key=_event_sort_key)
        ]
        result["declarations"] = [
            {
                "declaration_id": declaration.declaration_id,
                "title": declaration.title,
                "problem": declaration.problem,
                "summary": declaration.summary,
                "event_type": declaration.event_type,
                "status": declaration.status,
                "progress": declaration.progress,
                "participants": list(declaration.participants),
                "evidence": declaration.evidence,
                "first_text_position": declaration.char_start,
                "char_end": declaration.char_end,
                "chapter_id": declaration.chapter_id,
                "chapter_order": declaration.chapter_order,
                "producer_agent_id": declaration.producer_agent_id,
                "annotation_id": declaration.record_id,
                "payload_path": declaration.payload_path,
            }
            for declaration in sorted(
                self.declarations.values(),
                key=lambda row: (row.char_start or 0, row.declaration_id),
            )
        ]
        result["declaration_bindings"] = [
            {
                "declaration_id": row.declaration_id,
                "event_id": row.event_id,
                "producer_agent_id": row.producer_agent_id,
            }
            for row in sorted(self.bindings.values(), key=lambda row: row.declaration_id)
        ]
        result["declaration_relations"] = [
            {
                "relation_id": row.relation_id,
                "source_declaration_id": row.source_id,
                "target_declaration_id": row.target_id,
                "relation_type": row.relation_type,
                "reason": row.reason,
                "evidence": row.evidence,
                "producer_agent_id": row.producer_agent_id,
                "source_operation_id": row.source_operation_id,
            }
            for row in self.declaration_relations
        ]
        result["containments"] = [
            {
                "parent_event_id": row.contained_parent_id,
                "child_event_id": row.contained_child_id,
                "reason": row.reason,
                "evidence": self._link_evidence_payloads(row.link_id),
            }
            for row in sorted(
                self.parent_of.values(), key=lambda row: (row.contained_parent_id, row.contained_child_id)
            )
        ]
        return result

    def _link_evidence_payloads(self, link_id: str) -> list[dict[str, Any]]:

        rows = smap.fetch_evidence(self.session, "narrative_link_id", [link_id])
        return smap.evidence_payloads(self.session, self.run_id, rows.get(link_id, []))
