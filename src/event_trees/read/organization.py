"""正式事件与阶段的只读投影；章级声明只供追索，不形成第二种业务身份

- 章级声明 = event_declarations（来源归属从 chapter_annotations → executions → work_items 取得）
- 完整事件 = complete_events（正文不在事件行，当前内容取显式 stage_index 链尾）
- 阶段版本 = event_revisions（声明绑定或独立 origin 正文恰一，前驱为 index−1 投影）
- 包含/关系 = narrative_links；叙事线/结果 = narrative_groups 及两者的关联链路
- 核对/冲突 = organization_checks / conflict_records + conflict_claims
证据一律从 source_evidence 的所有者列读回，不在读取时补造坐标或哈希。
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.event_trees import storage_map as smap
from src.fact_graph.read.references import EntityReferenceProjection
from src.storage.models import (
    Chapter,
    ChapterAnnotation,
    DiagnosisReport,
    EventDeclaration,
    EventRevision,
    Execution,
    NarrativeGroup,
    NarrativeLink,
    Paragraph,
)
from src.utils.identity import text_digest

CONTRACT_VERSION = "event-tree-declarations-v1"


class RunRequiresRebuildError(ValueError):
    """旧契约运行不接受读取层转换，必须修正正式链后从原文重建"""

    def __init__(self) -> None:
        super().__init__("该运行为旧契约，需要从原文重建")


@dataclass(frozen=True)
class EventView:
    """完整事件的读取投影：身份 + 真实生产者 + 当前阶段内容与整体证据"""

    event_id: str
    producer_execution_id: str
    local_key: str
    identity_reason: str
    title: str | None
    problem: str | None
    summary: str | None
    event_type: str | None
    status: str | None
    progress: str | None
    current_revision_id: str | None
    first_text_position: int | None
    evidence: list[dict[str, Any]]
    source_execution_id: str | None


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
    producer_invocation_id: str | None
    contract_version: str

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
class RevisionView:
    """阶段版本：声明阶段取声明正文，origin 阶段取 origin_* 正文；前驱为 index−1"""

    revision_id: str
    event_id: str
    stage_index: int
    previous_revision_id: str | None
    declaration_id: str | None
    title: str
    problem: str
    summary: str
    event_type: str
    status: str
    progress: str | None
    participants: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    producer_invocation_id: str
    source_execution_id: str | None
    source_operation_id: str


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
    producer_invocation_id: str
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
    producer_invocation_id: str


@dataclass(frozen=True)
class OutcomeView:
    """事件结果读取形状"""

    outcome_id: str
    title: str
    description: str
    first_text_position: int
    evidence: list[dict[str, Any]]
    producer_invocation_id: str


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
    revision_id: str
    producer_invocation_id: str


@dataclass(frozen=True)
class ConflictView:
    conflict_id: str
    subject_kind: str
    subject_id: str
    claims: list[dict[str, Any]]
    reason: str
    resolution: str
    evidence: list[dict[str, Any]]
    producer_invocation_id: str


@dataclass(frozen=True)
class ForeshadowingView:
    """伏笔动作的读取形状"""

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

    def __init__(self, session: Session, run_id: str) -> None:
        self.session, self.run_id = session, run_id
        self._loaded = False
        self._containment_links: list[NarrativeLink] = []
        self._revision_rows: list[EventRevision] = []
        self._declaration_executions: dict[str, str] = {}

    # ------------------------------------------------------------------
    # 加载与契约校验
    # ------------------------------------------------------------------

    def _load_annotations(self) -> list[ChapterAnnotation]:
        stmt = (
            select(ChapterAnnotation)
            .where(ChapterAnnotation.run_id == self.run_id)
            .order_by(ChapterAnnotation.created_at, ChapterAnnotation.record_id)
        )
        return list(self.session.scalars(stmt))

    def _load_report(self) -> DiagnosisReport | None:
        return self.session.scalars(
            select(DiagnosisReport)
            .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
            .where(Execution.session_run_id == self.run_id)
            .order_by(DiagnosisReport.created_at.desc(), DiagnosisReport.report_id.desc())
            .limit(1)
        ).first()

    def _load(self) -> None:
        if self._loaded:
            return
        annotations = self._load_annotations()
        report = self._load_report()
        contract_outputs = bool(annotations) or report is not None
        # 正式保存的版本标记允许合法零事件运行，不能用业务对象数量猜测契约
        if any(row.contract_version != CONTRACT_VERSION for row in annotations) or (
            report is not None and report.contract_version != CONTRACT_VERSION
        ):
            raise RunRequiresRebuildError()
        self.organization_status = "ready" if report is not None else "pending_diagnosis"
        # 章节/段落基础投影先于声明与事件：声明章号与证据坐标都依赖它
        self.chapters: list[dict[str, Any]] = [
            {"chapter_id": row.chapter_id, "title": row.display_title or row.title, "chapter_order": index + 1}
            for index, row in enumerate(
                self.session.scalars(
                    select(Chapter)
                    .where(Chapter.run_id == self.run_id, Chapter.text.is_not(None))
                    .order_by(Chapter.sequence, Chapter.chapter_id)
                )
            )
        ]
        self.orders: dict[int, int] = {row["chapter_id"]: row["chapter_order"] for row in self.chapters}
        self.paragraphs = {
            row.paragraph_id: row
            for row in self.session.scalars(select(Paragraph).where(Paragraph.run_id == self.run_id))
        }
        self.events = self._load_events()
        self.declarations = self._load_declarations(annotations)
        self.revisions = self._load_revisions()
        self._load_containments()
        self.bindings = {
            row.declaration_id: BindingView(
                declaration_id=row.declaration_id,
                event_id=row.event_id,
                revision_id=row.revision_id,
                producer_invocation_id=self.events[row.event_id].producer_execution_id,
            )
            for row in self._revision_rows
            if row.declaration_id is not None
        }
        # 尚未生成任何标注的合法空运行没有契约标记；已有对象却丢失来源产物不能冒充空运行
        if not contract_outputs and (self.declarations or self.events or self.revisions):
            raise RunRequiresRebuildError()
        self.entity_projection = EntityReferenceProjection.load(self.session, self.run_id)
        self._load_organization()
        self.actions = (
            [self._action_view(row) for row in self._action_rows] if self.organization_status == "ready" else []
        )
        self.conflicts = [ConflictView(**row) for row in smap.conflict_payloads(self.session, self.run_id)]
        self._validate_saved_contract()
        self._loaded = True

    def _load_events(self) -> dict[str, EventView]:
        event_rows = smap.run_events(self.session, self.run_id)
        if not event_rows:
            return {}
        event_ids = list(event_rows)
        chains = smap.stage_chain(self.session, event_ids)
        contents: dict[str, dict[str, Any]] = {}
        for event_id, rows in chains.items():
            if rows:
                contents[event_id] = smap.revision_contents(self.session, {event_id: [rows[-1]]})[rows[-1].revision_id]
        evidence = smap.fetch_evidence(self.session, smap.SourceEvidence.complete_event_id, event_ids)
        result: dict[str, EventView] = {}
        for event_id, row in event_rows.items():
            payloads = smap.evidence_payloads(self.session, self.run_id, evidence.get(event_id, []))
            positions = (
                smap.global_positions(self.session, self.run_id, {item["paragraph_id"] for item in payloads})
                if payloads
                else {}
            )
            content = contents.get(event_id) or {}
            session_id = self.session.scalar(
                select(Execution.execution_id).where(Execution.session_run_id == self.run_id)
            )
            stages = chains.get(event_id) or []
            result[event_id] = EventView(
                event_id=event_id,
                producer_execution_id=row.producer_execution_id,
                local_key=row.local_key,
                identity_reason=row.identity_reason,
                title=content.get("title"),
                problem=content.get("problem"),
                summary=content.get("summary"),
                event_type=content.get("event_type"),
                status=content.get("status"),
                progress=content.get("progress"),
                current_revision_id=stages[-1].revision_id if stages else None,
                first_text_position=(
                    min(positions[item["paragraph_id"]] + item["char_start"] for item in payloads)
                    if payloads
                    else None
                ),
                evidence=payloads,
                source_execution_id=session_id,
            )
        return result

    def _load_containments(self) -> None:
        self._containment_links = list(
            self.session.scalars(
                select(NarrativeLink).where(
                    NarrativeLink.producer_execution_id.in_(smap.run_execution_ids(self.run_id)),
                    NarrativeLink.contained_child_id.is_not(None),
                )
            )
        )
        self.parent_of: dict[str, NarrativeLink] = {
            _containment_child_id(row): row for row in self._containment_links
        }
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
        from src.storage.models import DeclarationParticipant, GraphEntity

        result: dict[str, list[dict[str, Any]]] = {key: [] for key in declaration_ids}
        if not declaration_ids:
            return result
        rows = list(
            self.session.scalars(
                select(DeclarationParticipant)
                .where(DeclarationParticipant.declaration_id.in_(declaration_ids))
                .order_by(DeclarationParticipant.declaration_id, DeclarationParticipant.participant_ordinal)
            )
        )
        names: dict[str, str] = {}
        if rows:
            names = {
                row.entity_id: row.canonical_name
                for row in self.session.scalars(
                    select(GraphEntity).where(GraphEntity.entity_id.in_({row.entity_id for row in rows}))
                )
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
        from src.storage.models import SourceEvidence

        if not annotations:
            return {}
        records = {row.record_id: row for row in annotations}
        execution_by_record = {row.record_id: row.execution_id for row in annotations}
        declaration_rows = list(
            self.session.scalars(select(EventDeclaration).where(EventDeclaration.record_id.in_(list(records))))
        )
        declaration_ids = [row.declaration_id for row in declaration_rows]
        evidence = smap.fetch_evidence(self.session, SourceEvidence.declaration_id, declaration_ids)
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
                producer_invocation_id=record.execution_id,
                contract_version=record.contract_version,
            )
        return result

    def _load_revisions(self) -> dict[str, RevisionView]:
        from src.storage.models import SourceEvidence

        event_ids = list(self.events)
        self._revision_rows = (
            list(
                self.session.scalars(
                    select(EventRevision)
                    .where(EventRevision.event_id.in_(event_ids))
                    .order_by(EventRevision.event_id, EventRevision.stage_index)
                )
            )
            if event_ids
            else []
        )
        if not self._revision_rows:
            return {}
        contents = smap.revision_contents(
            self.session,
            {
                event_id: [row for row in self._revision_rows if row.event_id == event_id]
                for event_id in event_ids
            },
        )
        declaration_ids = [row.declaration_id for row in self._revision_rows if row.declaration_id is not None]
        declaration_evidence = smap.fetch_evidence(self.session, SourceEvidence.declaration_id, declaration_ids)
        event_evidence = smap.fetch_evidence(self.session, SourceEvidence.complete_event_id, event_ids)
        grouped: dict[str, list[EventRevision]] = {}
        for row in self._revision_rows:
            grouped.setdefault(row.event_id, []).append(row)
        result: dict[str, RevisionView] = {}
        for event_id, rows in grouped.items():
            for index, row in enumerate(rows):
                content = contents[row.revision_id]
                if row.declaration_id is not None:
                    declaration = self.declarations.get(row.declaration_id)
                    if declaration is None:
                        raise ValueError("已保存阶段绑定的声明不属于当前运行")
                    rev_evidence = smap.evidence_payloads(
                        self.session, self.run_id, declaration_evidence.get(row.declaration_id, [])
                    )
                    rev_participants = declaration.participants
                    source_execution_id = self._declaration_executions.get(row.declaration_id)
                    producer_invocation_id = declaration.producer_invocation_id or row.declaration_id
                else:
                    event = self.events[event_id]
                    rev_evidence = smap.evidence_payloads(
                        self.session, self.run_id, event_evidence.get(event_id, [])
                    )
                    rev_participants = []
                    source_execution_id = event.source_execution_id
                    producer_invocation_id = event.producer_execution_id
                result[row.revision_id] = RevisionView(
                    revision_id=row.revision_id,
                    event_id=event_id,
                    stage_index=int(row.stage_index),
                    previous_revision_id=rows[index - 1].revision_id if index > 0 else None,
                    declaration_id=row.declaration_id,
                    title=content["title"],
                    problem=content["problem"],
                    summary=content["summary"],
                    event_type=content["event_type"],
                    status=content["status"],
                    progress=content["progress"],
                    participants=rev_participants,
                    evidence=rev_evidence,
                    producer_invocation_id=str(producer_invocation_id),
                    source_execution_id=source_execution_id,
                    source_operation_id=f"stage/{event_id}/{row.stage_index}",
                )
        return result

    def _load_organization(self) -> None:
        from src.storage.models import SourceEvidence

        producer_executions = smap.run_execution_ids(self.run_id)
        groups = list(
            self.session.scalars(
                select(NarrativeGroup)
                .where(NarrativeGroup.producer_execution_id.in_(producer_executions))
                .order_by(NarrativeGroup.group_id)
            )
        )
        group_evidence = smap.fetch_evidence(
            self.session, SourceEvidence.narrative_group_id, [row.group_id for row in groups]
        )
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
                producer_invocation_id=row.producer_execution_id,
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
                producer_invocation_id=row.producer_execution_id,
            )
            for row in groups
            if row.outcome_description is not None
        }
        links = list(
            self.session.scalars(
                select(NarrativeLink)
                .where(NarrativeLink.producer_execution_id.in_(producer_executions))
                .order_by(NarrativeLink.link_id)
            )
        )
        link_evidence = smap.fetch_evidence(
            self.session, SourceEvidence.narrative_link_id, [row.link_id for row in links]
        )
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
            producer_invocation_id=row.producer_execution_id,
            source_operation_id=row.source_operation_local_key,
        )

    def _first_evidence_position(self, rows: list[Any]) -> int:
        if not rows:
            return 0
        payloads = smap.evidence_payloads(self.session, self.run_id, rows)
        positions = smap.global_positions(
            self.session, self.run_id, {item["paragraph_id"] for item in payloads}
        )
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

    def _current_revision(self, event: EventView) -> RevisionView:
        revision = self.revisions.get(event.current_revision_id or "")
        if revision is None or revision.event_id != event.event_id:
            raise ValueError("已保存事件缺少有效的正式当前版本，需要从原文重建")
        return revision

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
        from src.storage.models import SourceEvidence

        rows = smap.fetch_evidence(
            self.session, SourceEvidence.narrative_link_id, [row.link_id for row in self._containment_links]
        )
        return [
            smap.evidence_payloads(self.session, self.run_id, rows.get(row.link_id, []))
            for row in self._containment_links
        ]

    def _validate_saved_contract(self) -> None:
        """读取只核验正式对象，不忽略错误端点或用旧字段补救版本"""
        # 案例会话逐案写正式树、报告最后落库：报告未存不代表树必须为空，按已有对象校验
        if self.organization_status == "ready" and set(self.bindings) != set(self.declarations):
            raise ValueError("已发布事件声明缺少完整的正式身份绑定")
        for binding in self.bindings.values():
            revision = self.revisions.get(binding.revision_id)
            declaration = self.declarations.get(binding.declaration_id)
            event = self.events.get(binding.event_id)
            if (
                event is None
                or revision is None
                or revision.event_id != binding.event_id
                or revision.declaration_id != binding.declaration_id
                or declaration is None
            ):
                raise ValueError("已发布声明绑定与事件阶段或真实标注来源不一致")
            if any(
                getattr(revision, field) != getattr(declaration, field)
                for field in ("title", "problem", "summary", "event_type", "status", "progress")
            ):
                raise ValueError("已发布阶段与不可变声明原始贡献不一致")
        confirmed_revisions: set[str] = set()
        for event in self.events.values():
            self._current_revision(event)
            self._ancestry(event.event_id)
            stages = self._stages(event)
            if [row.stage_index for row in stages] != list(range(len(stages))):
                raise ValueError("已保存事件阶段序号不连续，需要从原文重建")
            for stage in stages:
                confirmed_revisions.add(stage.revision_id)
                self._validate_evidence(stage.evidence)
        if confirmed_revisions != set(self.revisions):
            raise ValueError("已保存版本不在事件的正式当前版本链内")
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
        for conflict in self.conflicts:
            if conflict.subject_kind in {"event", "declaration"}:
                self._locate(conflict.subject_kind, conflict.subject_id)
            if not conflict.claims:
                raise ValueError("已保存原文冲突缺少未解决说法")
            for claim in conflict.claims:
                self._validate_evidence(claim.get("evidence") or claim.get("source") or [])
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
            *(row.evidence for row in self.conflicts),
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
        revision = self._current_revision(event)
        chapter_id = self._first_evidence_chapter(event.evidence)
        return {
            "event_id": event.event_id,
            "title": event.title,
            "summary": revision.summary,
            "event_type": event.event_type,
            "status": revision.status,
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
            "contract_version": CONTRACT_VERSION,
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
        context: list[Any] = [self.run_id, CONTRACT_VERSION, "events"]
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
        revision = self._current_revision(event)
        evidence = list(
            {
                json.dumps(item, sort_keys=True, ensure_ascii=False): item
                for item in [*event.evidence, *self._revision_evidence(event)]
            }.values()
        )
        characters: dict[str, dict[str, Any]] = {}
        for stage in self._stages(event):
            for participant in self.entity_projection.participants(stage.participants):
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
            "summary": revision.summary,
            "progress": revision.progress,
            "event_type": event.event_type,
            "status": revision.status,
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
                    "status": self._current_revision(self.events[_containment_child_id(row)]).status,
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
            "revision_id": event.current_revision_id,
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

    def _revision_evidence(self, event: EventView) -> list[dict[str, Any]]:
        """跨章来源包含全部已确认版本，不以当前版本裁掉此前章的依据"""
        return [item for revision in self._stages(event) for item in revision.evidence]

    def _stages(self, event: EventView) -> list[RevisionView]:
        """严格沿已确认的阶段链读取，不按章号或日期重新推断阶段顺序"""
        stages: list[RevisionView] = []
        revision = self._current_revision(event)
        while True:
            stages.append(revision)
            if revision.previous_revision_id is None:
                return list(reversed(stages))
            revision = self.revisions[revision.previous_revision_id]

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
        result["event_records"] = [
            {
                "event_id": event.event_id,
                "title": event.title,
                "problem": event.problem,
                "summary": self._current_revision(event).summary,
                "progress": self._current_revision(event).progress,
                "status": self._current_revision(event).status,
                "event_type": event.event_type,
                "current_revision_id": event.current_revision_id,
                "source_execution_id": event.source_execution_id,
                "producer_invocation_id": event.producer_execution_id,
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
                "participants": self.entity_projection.participants(declaration.participants),
                "evidence": declaration.evidence,
                "first_text_position": declaration.char_start,
                "char_end": declaration.char_end,
                "chapter_id": declaration.chapter_id,
                "chapter_order": declaration.chapter_order,
                "producer_invocation_id": declaration.producer_invocation_id,
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
                "revision_id": row.revision_id,
                "producer_invocation_id": row.producer_invocation_id,
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
                "producer_invocation_id": row.producer_invocation_id,
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
        result["revisions"] = [
            {
                "revision_id": row.revision_id,
                "event_id": row.event_id,
                "previous_revision_id": row.previous_revision_id,
                "declaration_id": row.declaration_id,
                "participants": self.entity_projection.participants(row.participants),
                "title": row.title,
                "problem": row.problem,
                "event_type": row.event_type,
                "summary": row.summary,
                "status": row.status,
                "progress": row.progress,
                "source_execution_id": row.source_execution_id,
                "producer_invocation_id": row.producer_invocation_id,
                "source_operation_id": row.source_operation_id,
                "evidence": row.evidence,
            }
            for row in sorted(self.revisions.values(), key=lambda row: row.revision_id)
        ]
        result["conflicts"] = [
            {
                "conflict_id": row.conflict_id,
                "subject_kind": row.subject_kind,
                "subject_id": row.subject_id,
                "claims": row.claims,
                "reason": row.reason,
                "resolution": row.resolution,
                "evidence": row.evidence,
            }
            for row in self.conflicts
        ]
        return result

    def _link_evidence_payloads(self, link_id: str) -> list[dict[str, Any]]:
        from src.storage.models import SourceEvidence

        rows = smap.fetch_evidence(self.session, SourceEvidence.narrative_link_id, [link_id])
        return smap.evidence_payloads(self.session, self.run_id, rows.get(link_id, []))
