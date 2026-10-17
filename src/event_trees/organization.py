"""诊断内部的完整事件组织草稿、原文绑定与事务写入（2026-10-16 全库 3NF 改造）

写入目标关系（35 表冻结结构；旧 analysis_outputs / diagnosis_works checkpoint 退场）：
- 会话/工作/执行：executions 的整轮 session 形状、work_items 的诊断 work 与
  executions 的真实 invocation 形状（同表两形状互斥，不互相冒充）
- 完整事件：complete_events（身份 + 真实生产者 + 同一性理由）
- 阶段版本：event_revisions（显式 stage_index 链；声明绑定或 origin 正文恰一）
- 包含/关系：narrative_links（单父包含 / 语义关系两类互斥形状）
- 叙事组织：narrative_groups（叙事线/结果）与 narrative_links（线/结果关联）
- 组织核对：organization_checks（单事件/单声明核对与声明对/结构对判断四类形状）
- 冲突：conflict_records / conflict_claims
证据一律进入 source_evidence 的明确所有者列（owner 恰一 + ordinal 顺序）；
source_hashes 不新存，由声明绑定集合连接 organization_checks 的快照承诺读取重构。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.event_trees import storage_map as smap
from src.fact_graph.outputs import SourceReference
from src.storage.models import (
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
    ConflictRecord,
    DeclarationParticipant,
    EventDeclaration,
    EventForeshadowingAction,
    EventRevision,
    Execution,
    GraphEntity,
    GraphFact,
    NarrativeGroup,
    NarrativeLink,
    Paragraph,
    SourceEvidence,
    WorkItem,
)
from src.storage.models import (
    ConflictClaim as ConflictClaimRow,
)
from src.storage.models.base import naive_utcnow
from src.utils.identity import stable_uuid, text_digest

CONTRACT_VERSION: Literal["event-tree-declarations-v1"] = "event-tree-declarations-v1"


def snapshot_digest(payload: Any) -> str:
    """稳定摘要只绑定业务内容，不包含审计或容量租约"""
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def record_payloads(records: Any) -> list[dict[str, Any]]:
    """无序候选集合以内容排序，跨工作恢复顺序不改变已核对版本"""
    return sorted((item.model_dump(mode="json") for item in records), key=snapshot_digest)


class CandidateConflict(ValueError):
    """可定位的候选冲突只返回真实生产者，不能重开无关会话"""

    def __init__(self, message: str, work_ids: list[str]) -> None:
        self.work_ids = tuple(sorted(set(work_ids)))
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
    source_work_id: str = ""
    producer_invocation_id: str = ""


class NarrativeArcDraft(OrganizationRecord):
    arc_id: str
    parent_arc_id: str | None = None
    kind: Literal["main", "subplot"]
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1)
    role: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EventArcLinkDraft(OrganizationRecord):
    event_id: str
    arc_id: str
    role: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EventOutcomeDraft(OrganizationRecord):
    outcome_id: str
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    first_text_position: int = Field(ge=0)


class EventOutcomeLinkDraft(OrganizationRecord):
    event_id: str
    outcome_id: str
    reason: str = Field(min_length=1)


class ConflictClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claim: str = Field(min_length=1)
    evidence: list[OrganizationEvidence] = Field(min_length=1, max_length=100)


class BoundConflictClaim(OrganizationRecord):
    claim: str = Field(min_length=1)


class ConflictDraft(OrganizationRecord):
    conflict_id: str
    subject_kind: Literal["event", "declaration", "fact"]
    subject_id: str
    claims: list[BoundConflictClaim] = Field(min_length=2)
    reason: str = Field(min_length=1)
    resolution: Literal["unresolved"] = "unresolved"


class EventReviewDraft(BaseModel):
    """诊断产物的覆盖审计，不制造无原文依据的线或结果关联"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: str
    reason: str = Field(min_length=1)
    snapshot_hash: str = Field(min_length=1)
    source_work_id: str
    producer_invocation_id: str


class CompleteEventDraft(OrganizationRecord):
    """诊断尚未发布的完整事件；直接过程与子事件作为同一笔原子输入"""

    event_id: str
    local_key: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1)
    problem: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    status: Literal["ongoing", "resolved"]
    progress: str | None = None
    declaration_ids: list[str] = Field(default_factory=list)
    stage_order: list[str] = Field(default_factory=list)
    current_declaration_id: str | None = None
    reason: str = Field(min_length=1)
    source_hashes: dict[str, str] = Field(default_factory=dict)
    first_text_position: int = Field(ge=0)


class RevisionDraft(OrganizationRecord):
    revision_id: str
    event_id: str
    previous_revision_id: str | None = None
    summary: str = Field(min_length=1)
    progress: str | None = None
    status: Literal["ongoing", "resolved"]
    source_operation_id: str
    declaration_id: str | None = None
    title: str
    problem: str
    event_type: str
    participants: list[dict[str, Any]] = Field(default_factory=list)


class ContainmentDraft(OrganizationRecord):
    parent_event_id: str
    child_event_id: str
    reason: str = Field(min_length=1)


class DeclarationReviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    declaration_id: str
    source_hash: str
    reason: str = Field(min_length=1)
    source_work_id: str
    producer_invocation_id: str


class DeclarationComparisonDraft(OrganizationRecord):
    source_declaration_id: str
    target_declaration_ids: list[str] = Field(min_length=1)
    disposition: Literal["same_event", "independent", "related"]
    reason: str = Field(min_length=1)


class StructureReviewDraft(OrganizationRecord):
    source_event_id: str
    target_event_id: str
    disposition: Literal["contains", "part_of", "related", "independent"]
    reason: str = Field(min_length=1)
    snapshot_hash: str


class RelationDraft(OrganizationRecord):
    relation_id: str
    source_kind: Literal["event"]
    source_id: str
    target_kind: Literal["event"]
    target_id: str
    relation_type: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source_operation_id: str


class NarrativeOrganization(BaseModel):
    """完整事件的全书组织；章节概要、类型和包含结构保持不可变"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["event-tree-declarations-v1"] = CONTRACT_VERSION
    source_execution_id: str | None = None
    events: list[CompleteEventDraft] = Field(default_factory=list)
    revisions: list[RevisionDraft] = Field(default_factory=list)
    relations: list[RelationDraft] = Field(default_factory=list)
    arcs: list[NarrativeArcDraft] = Field(default_factory=list)
    event_arc_links: list[EventArcLinkDraft] = Field(default_factory=list)
    outcomes: list[EventOutcomeDraft] = Field(default_factory=list)
    event_outcome_links: list[EventOutcomeLinkDraft] = Field(default_factory=list)
    conflicts: list[ConflictDraft] = Field(default_factory=list)
    reviewed_events: list[EventReviewDraft] = Field(default_factory=list)
    declaration_reviews: list[DeclarationReviewDraft] = Field(default_factory=list)
    declaration_comparisons: list[DeclarationComparisonDraft] = Field(default_factory=list)
    containments: list[ContainmentDraft] = Field(default_factory=list)
    identity_snapshot: str | None = None
    structure_snapshot: str | None = None
    structure_reviews: list[StructureReviewDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_structure(self) -> NarrativeOrganization:
        arcs = {arc.arc_id: arc for arc in self.arcs}
        outcomes = {item.outcome_id for item in self.outcomes}
        for records, keys in (
            (self.events, {item.event_id for item in self.events}),
            (self.revisions, {item.revision_id for item in self.revisions}),
            (self.relations, {item.relation_id for item in self.relations}),
            (self.arcs, list(arcs)),
            (self.outcomes, list(outcomes)),
            (self.conflicts, {item.conflict_id for item in self.conflicts}),
            (self.reviewed_events, {item.event_id for item in self.reviewed_events}),
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
# 诊断会话、工作与真实执行的登记（新关系；不恢复 checkpoint）
# ---------------------------------------------------------------------------


def register_diagnosis_session(session: Session, *, run_id: str, session_id: str) -> None:
    """登记诊断整轮身份（executions 的 session 形状）；已存在且同 run 时幂等，不覆盖既有轮次"""
    existing = session.get(Execution, session_id)
    if existing is None:
        session.add(
            Execution(execution_id=session_id, session_run_id=run_id, session_created_at=naive_utcnow())
        )
        session.flush()
        return
    if existing.session_run_id != run_id:
        raise ValueError("诊断会话身份已属于其他运行")


def register_diagnosis_work(session: Session, *, session_id: str, work_id: str, role: str) -> None:
    """登记现有调度产生的诊断 work 身份；不发明划分，不保存 checkpoint"""
    existing = session.get(WorkItem, work_id)
    if existing is None:
        session.add(WorkItem(work_id=work_id, role=role, diagnosis_session_id=session_id))
        session.flush()
        return
    if existing.diagnosis_session_id != session_id or existing.role != role:
        raise ValueError("诊断工作身份已登记为其他会话或职责")


def register_diagnosis_execution(
    session: Session, *, work_id: str, execution_id: str, attempt_number: int
) -> None:
    """登记诊断 work 的真实尝试；执行事实与诊断上下文同事务写入"""
    existing = session.get(Execution, execution_id)
    if existing is not None:
        if existing.work_id != work_id or existing.attempt_number != attempt_number:
            raise ValueError("诊断执行身份已登记为其他工作或尝试序号")
        return
    duplicate = session.scalar(
        select(Execution.execution_id).where(
            Execution.work_id == work_id, Execution.attempt_number == attempt_number
        )
    )
    if duplicate is not None:
        raise ValueError("诊断工作的该次尝试已有真实执行")
    session.add(
        Execution(
            execution_id=execution_id,
            work_id=work_id,
            attempt_number=attempt_number,
            started_at=naive_utcnow(),
            status="running",
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# 本 run 的声明、完整事件与关系的读取投影
# ---------------------------------------------------------------------------


def run_declaration_ids(session: Session, run_id: str) -> set[str]:
    """本 run 的章级声明：记录→标注执行→标注 work 取得运行归属"""
    return smap.run_declaration_ids(session, run_id)


def _chapter_offsets(session: Session, run_id: str, chapter_ids: set[int]) -> dict[int, int]:
    """章正文全文起点；空正文章节无切片，其段落也不存在证据"""
    return smap.chapter_offsets(session, run_id, chapter_ids)


def _paragraph_rows(session: Session, run_id: str, paragraph_ids: set[int]) -> dict[int, Paragraph]:
    return smap.paragraph_rows(session, run_id, paragraph_ids)


def _evidence_payloads(session: Session, run_id: str, rows: list[Any]) -> list[dict[str, Any]]:
    """证据行按 ordinal 重组为原文引用，哈希由不可变原文切片重算"""
    return smap.evidence_payloads(session, run_id, rows)


def _global_positions(session: Session, run_id: str, paragraph_ids: set[int]) -> dict[int, int]:
    """段落全文起点 = 所属正文起点 + 章内起点"""
    return smap.global_positions(session, run_id, paragraph_ids)


def _first_text_position(session: Session, run_id: str, evidence: list[Any]) -> int:
    """完整事件/结果的正文排序位置由其自身证据派生"""
    positions = smap.global_positions(session, run_id, {int(ref.paragraph_id) for ref in evidence})
    return min(positions[int(ref.paragraph_id)] + int(ref.char_start) for ref in evidence)


def _run_events(session: Session, run_id: str) -> dict[str, CompleteEvent]:
    return smap.run_events(session, run_id)


def _current_event_contents(session: Session, event_ids: list[str]) -> dict[str, dict[str, Any]]:
    """当前阶段内容：绑定声明取不可变声明，origin 取独立内容；current 必须是显式链尾"""
    if not event_ids:
        return {}
    chains = smap.stage_chain(session, event_ids)
    tails: dict[str, EventRevision] = {}
    for event_id in event_ids:
        rows = chains.get(event_id) or []
        if not rows:
            raise ValueError(f"正式事件缺少阶段版本: event_id={event_id}")
        tails[event_id] = rows[-1]
    contents = smap.revision_contents(session, {event_id: [row] for event_id, row in tails.items()})
    return {event_id: contents[row.revision_id] for event_id, row in tails.items()}


def _run_event_dicts(session: Session, run_id: str) -> dict[str, dict[str, Any]]:
    """本 run 完整事件的读取形状：身份 + 当前内容 + 整体证据"""
    rows = _run_events(session, run_id)
    if not rows:
        return {}
    event_ids = list(rows)
    contents = _current_event_contents(session, event_ids)
    chains = smap.stage_chain(session, event_ids)
    evidence = smap.fetch_evidence(session, SourceEvidence.complete_event_id, event_ids)
    result: dict[str, dict[str, Any]] = {}
    for event_id in event_ids:
        payloads = _evidence_payloads(session, run_id, evidence.get(event_id, []))
        if not payloads:
            raise ValueError(f"正式事件缺少整体证据: event_id={event_id}")
        positions = _global_positions(session, run_id, {item["paragraph_id"] for item in payloads})
        stages = chains.get(event_id) or []
        current = stages[-1].revision_id if stages else None
        result[event_id] = {
            "event_id": event_id,
            "title": contents[event_id]["title"],
            "problem": contents[event_id]["problem"],
            "summary": contents[event_id]["summary"],
            "event_type": contents[event_id]["event_type"],
            "status": contents[event_id]["status"],
            "progress": contents[event_id]["progress"],
            "current_revision_id": current,
            "first_text_position": min(
                positions[item["paragraph_id"]] + item["char_start"] for item in payloads
            ),
            "evidence": payloads,
        }
    return result


def _published_arc_ids(session: Session, run_id: str) -> set[str]:
    """本 run 已发布的叙事线（经由真实诊断执行取得运行归属）"""
    stmt = select(NarrativeGroup.group_id).where(
        NarrativeGroup.producer_execution_id.in_(smap.run_execution_ids(run_id))
    )
    return set(session.scalars(stmt))


def _run_annotation_records(session: Session, run_id: str) -> list[Any]:
    stmt = (
        select(ChapterAnnotation, WorkItem, Chapter)
        .join(Execution, Execution.execution_id == ChapterAnnotation.execution_id)
        .join(WorkItem, WorkItem.work_id == Execution.work_id)
        .join(
            Chapter,
            (Chapter.run_id == WorkItem.annotation_run_id) & (Chapter.chapter_id == WorkItem.annotation_chapter_id),
        )
        .where(WorkItem.annotation_run_id == run_id)
    )
    return list(session.execute(stmt).all())


def _run_foreshadowing_actions(session: Session, run_id: str) -> list[Any]:
    """本 run 的伏笔动作：来源或目标声明属于本 run 的声明集合"""
    declarations = run_declaration_ids(session, run_id)
    if not declarations:
        return []
    stmt = select(EventForeshadowingAction).where(
        or_(
            EventForeshadowingAction.source_declaration_id.in_(declarations),
            EventForeshadowingAction.target_declaration_id.in_(declarations),
        )
    )
    return list(session.scalars(stmt.order_by(EventForeshadowingAction.operation_order)))


def _page_size(limit: int, maximum: int = 100) -> None:
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit 必须在 1 到 {maximum} 之间")


class EventOrganizationDraft:
    """只更新本轮内存；程序检查完整性后由诊断保存点一次提交"""

    def __init__(self, session: Session, run_id: str, execution_id: str | None = None) -> None:
        # execution_id 是诊断整轮的会话身份（diagnosis_sessions.session_id），不是单个 work 的调用
        self.session = session
        self.run_id = run_id
        self.execution_id = execution_id
        self.work_id: str | None = None
        self.producer_invocation_id: str | None = None
        self.responsible_ids: set[str] | None = None
        self.identity_snapshot: str | None = None
        self.structure_snapshot: str | None = None
        self.containments: dict[tuple[str, str], ContainmentDraft] = {}
        self.declaration_reviews: dict[str, DeclarationReviewDraft] = {}
        self.declaration_comparisons: dict[tuple[str, str], DeclarationComparisonDraft] = {}
        self.structure_reviews: dict[tuple[str, str], StructureReviewDraft] = {}
        self.events: dict[str, CompleteEventDraft] = {}
        self.revisions: dict[str, RevisionDraft] = {}
        self.relations: dict[str, RelationDraft] = {}
        self.arcs: dict[str, NarrativeArcDraft] = {}
        self.event_arc_links: dict[tuple[str, str], EventArcLinkDraft] = {}
        self.outcomes: dict[str, EventOutcomeDraft] = {}
        self.event_outcome_links: dict[tuple[str, str], EventOutcomeLinkDraft] = {}
        self.conflicts: dict[str, ConflictDraft] = {}
        self.reviewed_events: dict[str, EventReviewDraft] = {}

    def _all_events(self) -> dict[str, dict[str, Any]]:
        result = _run_event_dicts(self.session, self.run_id)
        result.update({key: item.model_dump(mode="json") for key, item in self.events.items()})
        return result

    def _parents(self) -> dict[str, str]:
        stmt = select(NarrativeLink).where(
            NarrativeLink.producer_execution_id.in_(smap.run_execution_ids(self.run_id)),
            NarrativeLink.contained_child_id.is_not(None),
        )
        parents = {
            row.contained_child_id: row.contained_parent_id
            for row in self.session.scalars(stmt)
            # ck_narrative_links_shape：包含形状两端同非空，读投影按该形状取非空对
            if row.contained_child_id is not None and row.contained_parent_id is not None
        }
        for edge in self.containments.values():
            prior = parents.get(edge.child_event_id)
            if prior is not None and prior != edge.parent_event_id:
                raise CandidateConflict(
                    f"包含候选存在多个直接父: child_event_id={edge.child_event_id}",
                    [
                        item.source_work_id
                        for item in self.containments.values()
                        if item.child_event_id == edge.child_event_id
                    ],
                )
            parents[edge.child_event_id] = edge.parent_event_id
        return parents

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
        unreviewed_only: bool = False,
        top_level_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """分页返回本次草稿与正式事件，零事件时也可从过程读取开始"""
        _page_size(limit)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        parents = self._parents()
        rows = [
            {**item, **self._event_hierarchy(key, parents)}
            for key, item in self._all_events().items()
            if (not unreviewed_only or key not in self.reviewed_events)
            and (not top_level_only or key not in parents)
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
        by_id, parents = self._all_events(), self._parents()
        if set(event_ids) - set(by_id):
            raise ValueError(f"本任务事件不存在: {sorted(set(event_ids) - set(by_id))}")
        return [
            {
                **by_id[key],
                **self._event_hierarchy(key, parents),
                "direct_child_event_ids": [child for child, parent in parents.items() if parent == key],
                "revisions": [item.model_dump(mode="json") for item in self.revisions.values() if item.event_id == key],
            }
            for key in event_ids
        ]

    def _declaration_rows(self) -> dict[str, dict[str, Any]]:
        """章级声明的正式读取：不可变声明 + 原标注记录/工作 + 参与者/证据/关系提议/伏笔动作"""
        session = self.session
        joined = _run_annotation_records(session, self.run_id)
        if not joined:
            return {}
        records = {row.record_id: row for row, _work, _chapter in joined}
        work_by_record = {row.record_id: work.work_id for row, work, _chapter in joined}
        chapter_by_record = {
            row.record_id: (int(work.annotation_chapter_id), int(chapter.sequence)) for row, work, chapter in joined
        }
        declarations = {
            row.declaration_id: row
            for row in session.scalars(select(EventDeclaration).where(EventDeclaration.record_id.in_(list(records))))
        }
        declaration_ids = list(declarations)
        if not declaration_ids:
            return {}
        participants: dict[str, list[dict[str, Any]]] = {key: [] for key in declaration_ids}
        names = {}
        participant_rows = list(
            session.scalars(
                select(DeclarationParticipant)
                .where(DeclarationParticipant.declaration_id.in_(declaration_ids))
                .order_by(DeclarationParticipant.declaration_id, DeclarationParticipant.participant_ordinal)
            )
        )
        if participant_rows:
            names = {
                row.entity_id: row.canonical_name
                for row in session.scalars(
                    select(GraphEntity).where(
                        GraphEntity.entity_id.in_({row.entity_id for row in participant_rows})
                    )
                )
            }
        for row in participant_rows:
            participants[row.declaration_id].append(
                {
                    "entity": {
                        "name": names.get(row.entity_id, row.entity_id),
                        "entity_id": row.entity_id,
                    },
                    "role": row.role,
                    "narrative_role": row.narrative_role,
                    "action": row.action,
                    "emotion": row.emotion,
                }
            )
        evidence = smap.fetch_evidence(session, SourceEvidence.declaration_id, declaration_ids)
        proposals: dict[str, list[dict[str, Any]]] = {key: [] for key in declaration_ids}
        link_rows = list(
            session.scalars(
                select(NarrativeLink).where(
                    NarrativeLink.producer_execution_id.in_(smap.run_execution_ids(self.run_id)),
                    NarrativeLink.semantic_source_declaration_id.is_not(None),
                    NarrativeLink.semantic_target_declaration_id.is_not(None),
                    or_(
                        NarrativeLink.semantic_source_declaration_id.in_(declaration_ids),
                        NarrativeLink.semantic_target_declaration_id.in_(declaration_ids),
                    ),
                )
            )
        )
        link_evidence = smap.fetch_evidence(
            session, SourceEvidence.narrative_link_id, [row.link_id for row in link_rows]
        )
        for link_row in link_rows:
            source_id, target_id = link_row.semantic_source_declaration_id, link_row.semantic_target_declaration_id
            payload: dict[str, Any] = {
                "relation_id": link_row.link_id,
                "source_declaration_id": source_id,
                "target_declaration_id": target_id,
                "relation_type": link_row.relation_type,
                "reason": link_row.reason,
                "evidence": _evidence_payloads(session, self.run_id, link_evidence.get(link_row.link_id, [])),
                "producer_invocation_id": link_row.producer_execution_id,
                "source_work_id": smap.work_of_execution(session, link_row.producer_execution_id),
            }
            for endpoint in (source_id, target_id):
                if endpoint in proposals:
                    proposals[endpoint].append(payload)
        actions: dict[str, list[dict[str, Any]]] = {key: [] for key in declaration_ids}
        for row in _run_foreshadowing_actions(session, self.run_id):
            if row.source_declaration_id not in declaration_ids and row.target_declaration_id not in declaration_ids:
                continue
            action_evidence = smap.fetch_evidence(session, SourceEvidence.foreshadow_action_id, [row.action_id])
            chapter_id, chapter_order = smap.annotation_chapter_of_execution(session, row.producer_execution_id)
            payload = {
                "action_id": row.action_id,
                "source_declaration_id": row.source_declaration_id,
                "target_declaration_id": row.target_declaration_id,
                "action_type": row.action_type,
                "chapter_id": chapter_id,
                "chapter_order": chapter_order,
                "evidence": _evidence_payloads(session, self.run_id, action_evidence.get(row.action_id, [])),
            }
            for endpoint in (row.source_declaration_id, row.target_declaration_id):
                if endpoint in actions:
                    actions[endpoint].append(payload)
        items: list[dict[str, Any]] = []
        for identifier, declaration in declarations.items():
            record = records[declaration.record_id]
            chapter_id, chapter_order = chapter_by_record[declaration.record_id]
            if record.contract_version != CONTRACT_VERSION:
                raise ValueError(f"声明缺少当前契约的已保存真实来源: {identifier}")
            bound = _evidence_payloads(session, self.run_id, evidence.get(identifier, []))
            if not bound:
                raise ValueError(f"声明缺少原文证据: {identifier}")
            payload = {
                "declaration_id": identifier,
                "title": declaration.title,
                "problem": declaration.problem,
                "summary": declaration.summary,
                "event_type": declaration.event_type,
                "status": declaration.status,
                "progress": declaration.progress,
                "participants": participants.get(identifier, []),
                "evidence": bound,
                "chapter_id": chapter_id,
                "chapter_order": chapter_order,
                "char_start": bound[0]["char_start"],
                "local_key": declaration.local_key,
                "source_work_id": work_by_record.get(declaration.record_id),
                "producer_invocation_id": record.execution_id,
            }
            payload.update(
                is_foreshadow_setup=declaration.is_foreshadowing_root,
                payoff_likelihood=declaration.payoff_likelihood,
                # strength 是 payoff_likelihood 的读投影，不双存第二份属性
                strength=declaration.payoff_likelihood,
                relation_proposals=proposals.get(identifier, []),
                source_actions=actions.get(identifier, []),
            )
            payload["source_hash"] = snapshot_digest(payload)
            items.append(payload)
        items.sort(key=lambda item: (item["chapter_order"], item["char_start"], item["declaration_id"]))
        return {item["declaration_id"]: item for item in items}

    def read_declarations(
        self, declaration_ids: list[str] | None = None, *, offset: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        """读取不可变声明；来源身份从不解释为已发布的事件身份"""
        _page_size(limit)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        all_rows = self._declaration_rows()
        if declaration_ids is not None:
            if not declaration_ids or len(set(declaration_ids)) != len(declaration_ids):
                raise ValueError("声明引用不能为空或重复")
            if set(declaration_ids) - set(all_rows):
                raise ValueError("声明引用不属于本 run")
            rows = [all_rows[key] for key in declaration_ids]
        else:
            rows = list(all_rows.values())
        return {
            "items": rows[offset : offset + limit],
            "total": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
        }

    def _declarations(self) -> dict[str, dict[str, Any]]:
        return self._declaration_rows()

    def _source(self) -> dict[str, Any]:
        if not self.work_id or not self.producer_invocation_id:
            raise ValueError("诊断贡献缺少实际 work 和调用来源")
        return {"source_work_id": self.work_id, "producer_invocation_id": self.producer_invocation_id}

    def review_declarations(self, declaration_ids: list[str], *, reason: str) -> None:
        all_sources = self._declarations()
        if set(declaration_ids) - set(all_sources):
            raise ValueError("声明引用不属于本 run")
        rows = [all_sources[key] for key in declaration_ids]
        source = self._source()
        if self.responsible_ids is not None and not set(declaration_ids) <= self.responsible_ids:
            raise ValueError("声明事实核对不在本 work 负责范围")
        for row in rows:
            self.declaration_reviews[row["declaration_id"]] = DeclarationReviewDraft(
                declaration_id=row["declaration_id"], source_hash=row["source_hash"], reason=reason, **source
            )

    def identity(
        self,
        *,
        key: str,
        title: str,
        problem: str,
        summary: str,
        event_type: str,
        status: Literal["ongoing", "resolved"],
        declaration_ids: list[str],
        stage_order: list[str],
        current_declaration_id: str,
        reason: str,
        evidence: list[OrganizationEvidence],
        progress: str | None = None,
    ) -> dict[str, Any]:
        """模型判断同一身份与阶段顺序，程序仅机械分配身份并保留所有来源原值"""
        if self.identity_snapshot is not None:
            raise ValueError("身份快照已冻结，禁止改变声明身份或阶段链")
        if (
            not declaration_ids
            or len(declaration_ids) != len(set(declaration_ids))
            or set(stage_order) != set(declaration_ids)
            or len(stage_order) != len(declaration_ids)
            or current_declaration_id != stage_order[-1]
        ):
            raise ValueError("stage_order 必须逐一包含所有声明且 current_declaration_id 为显式链尾")
        all_sources = self._declarations()
        if set(declaration_ids) - set(all_sources):
            raise ValueError("声明引用不属于本 run")
        rows = [all_sources[key] for key in declaration_ids]
        first = min(rows, key=lambda row: (row["chapter_order"], row["char_start"], row["declaration_id"]))
        if self.responsible_ids is not None and first["declaration_id"] not in self.responsible_ids:
            raise ValueError("跨范围身份判断须交由最早真实来源的责任 work 提交")
        event_id = stable_uuid("event_identity", self.run_id, *sorted(declaration_ids))
        bound = self.bind_evidence(evidence)
        candidate = CompleteEventDraft(
            event_id=event_id,
            local_key=key,
            title=title,
            problem=problem,
            summary=summary,
            event_type=event_type,
            status=status,
            progress=progress,
            declaration_ids=declaration_ids,
            stage_order=stage_order,
            current_declaration_id=current_declaration_id,
            reason=reason,
            source_hashes={row["declaration_id"]: row["source_hash"] for row in rows},
            first_text_position=self._first_position(bound),
            evidence=bound,
            **self._source(),
        )
        existing = self.events.get(event_id)
        if existing is not None and existing.source_work_id != self.work_id:
            raise ValueError("身份候选已经由其他责任 work 提交，不能覆盖其判断")
        proposed = {**self.events, event_id: candidate}
        # 完整候选集在屏障统一检查，不能以先提交者决定相交身份的胜者
        self.events = proposed
        self.reviewed_events.pop(event_id, None)
        return {"status": "accepted_candidate", "event_id": event_id, "declaration_ids": declaration_ids}

    def compare_declarations(
        self,
        *,
        source_declaration_id: str,
        target_declaration_ids: list[str],
        disposition: Literal["same_event", "independent", "related"],
        reason: str,
        evidence: list[OrganizationEvidence],
    ) -> None:
        """显式处置远近来源比较，责任锚点不决定故事语义"""
        if self.identity_snapshot is not None:
            raise ValueError("身份比较已冻结")
        rows = self._declarations()
        source = rows.get(source_declaration_id)
        if (
            source is None
            or not target_declaration_ids
            or len(set(target_declaration_ids)) != len(target_declaration_ids)
        ):
            raise ValueError("比较端点不存在或重复")
        if self.responsible_ids is not None and source_declaration_id not in self.responsible_ids:
            raise ValueError("比较来源不是本 work 的责任锚点")
        source_order = (source["chapter_order"], source["char_start"], source_declaration_id)
        for target_id in target_declaration_ids:
            target = rows.get(target_id)
            if target is None or (target["chapter_order"], target["char_start"], target_id) <= source_order:
                raise ValueError("跨范围比较必须由最早真实来源的责任 work 提交")
            existing = self.declaration_comparisons.get((source_declaration_id, target_id))
            if existing is not None and existing.source_work_id != self.work_id:
                raise ValueError("来源比较已由其他责任 work 提交，不能覆盖")
        item = DeclarationComparisonDraft(
            source_declaration_id=source_declaration_id,
            target_declaration_ids=target_declaration_ids,
            disposition=disposition,
            reason=reason,
            evidence=self.bind_evidence(evidence),
            **self._source(),
        )
        for target_id in target_declaration_ids:
            self.declaration_comparisons[(source_declaration_id, target_id)] = item

    def retract(
        self,
        *,
        kind: Literal["identity", "contain", "relation"],
        identifier: str,
        reason: str,
        evidence: list[OrganizationEvidence],
    ) -> None:
        """只允许实际生产者在对应屏障前撤回自己的候选，原操作仍保留审计"""
        if not reason.strip():
            raise ValueError("撤回须明确理由")
        self.bind_evidence(evidence)
        records: Any = {"identity": self.events, "contain": self.containments, "relation": self.relations}[kind]
        key: Any = tuple(identifier.split("/", 1)) if kind == "contain" else identifier
        item = records.get(key)
        if item is None or item.source_work_id != self.work_id:
            raise ValueError("只能撤回本 work 的实际候选")
        if (kind == "identity" and self.identity_snapshot is not None) or self.structure_snapshot is not None:
            raise ValueError("已冻结候选不能撤回")
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
        compared_event_ids: list[str],
        evidence: list[OrganizationEvidence],
        progress: str | None = None,
    ) -> dict[str, Any]:
        """跨章新增事件必须明确核对整个已有身份目录，不从名称猜测身份"""
        if self.identity_snapshot is None or self.structure_snapshot is not None:
            raise ValueError("新增跨章事件只在身份冻结后的结构阶段开放")
        if set(compared_event_ids) != set(self.events) or len(compared_event_ids) != len(set(compared_event_ids)):
            raise ValueError("新增事件须明确核对当前全部候选事件身份；同一事件应复用已有 event_id")
        source = self._source()
        bound = self.bind_evidence(evidence)
        event_id = stable_uuid("cross_chapter_event", self.run_id, self.work_id, key)
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
            first_text_position=self._first_position(bound),
            evidence=bound,
            **source,
        )
        if event_id in self.events and self.events[event_id] != candidate:
            raise ValueError("已接受事件不能被其他操作覆盖")
        self.events[event_id] = candidate
        return {"status": "accepted_candidate", "event_id": event_id}

    def contain(
        self, *, parent_event_id: str, child_event_id: str, reason: str, evidence: list[OrganizationEvidence]
    ) -> None:
        if self.identity_snapshot is None or self.structure_snapshot is not None:
            raise ValueError("包含只能在身份冻结后、结构冻结前提交")
        self.read_events([parent_event_id, child_event_id])
        if parent_event_id == child_event_id:
            raise ValueError("事件不能包含自身")
        edge = ContainmentDraft(
            parent_event_id=parent_event_id,
            child_event_id=child_event_id,
            reason=reason,
            evidence=self.bind_evidence(evidence),
            **self._source(),
        )
        previous = self.containments.get((parent_event_id, child_event_id))
        if previous is not None and previous.source_work_id != self.work_id:
            raise ValueError("不能覆盖其他 work 提交的包含候选，请引用原判断或显式交接")
        proposed = {**self.containments, (parent_event_id, child_event_id): edge}
        # 包含仅成为候选，完整集合在屏障统一裁定，不给先到候选语义优先权
        self.containments = proposed
        # 保留旧核对及其真实作者；屏障发现版本失效后回原 work，不丢失修正责任

    def structure_review(
        self,
        *,
        source_event_id: str,
        target_event_id: str,
        disposition: Literal["contains", "part_of", "related", "independent"],
        reason: str,
        evidence: list[OrganizationEvidence],
    ) -> None:
        if self.identity_snapshot is None or self.structure_snapshot is not None:
            raise ValueError("结构比较只在结构阶段开放")
        self.read_events([source_event_id, target_event_id])
        if source_event_id == target_event_id:
            raise ValueError("同一正式事件不能与自身作结构比较")
        bound = self.bind_evidence(evidence)
        pair = min(source_event_id, target_event_id), max(source_event_id, target_event_id)
        self.structure_reviews[pair] = StructureReviewDraft(
            source_event_id=source_event_id,
            target_event_id=target_event_id,
            disposition=disposition,
            reason=reason,
            evidence=bound,
            snapshot_hash=self.pair_snapshot(*pair),
            **self._source(),
        )

    def pair_snapshot(self, source: str, target: str) -> str:
        return snapshot_digest(
            {
                "events": [self.events[key].model_dump(mode="json") for key in sorted((source, target))],
                "containments": record_payloads(
                    item
                    for item in self.containments.values()
                    if {item.parent_event_id, item.child_event_id} == {source, target}
                ),
                "relations": record_payloads(
                    item
                    for item in self.relations.values()
                    if {item.source_id, item.target_id} == {source, target}
                ),
            }
        )

    def validate_events(self, events: dict[str, CompleteEventDraft] | None = None, *, require_coverage: bool) -> None:
        events = self.events if events is None else events
        declarations = self._declarations()
        used: dict[str, str] = {}
        for event in events.values():
            for identifier in event.declaration_ids:
                if identifier in used and used[identifier] != event.event_id:
                    raise CandidateConflict(
                        f"声明身份候选相冲突: declaration_id={identifier}",
                        [item.source_work_id for item in events.values() if identifier in item.declaration_ids],
                    )
                source = declarations.get(identifier)
                if source is None or event.source_hashes.get(identifier) != source["source_hash"]:
                    raise ValueError(f"声明来源不存在或已改变: {identifier}")
                used[identifier] = event.event_id
            if event.declaration_ids:
                if (
                    set(event.stage_order) != set(event.declaration_ids)
                    or len(event.stage_order) != len(event.declaration_ids)
                    or event.current_declaration_id != event.stage_order[-1]
                ):
                    raise ValueError("事件阶段链未完整明确指定")
        if require_coverage and set(used) != set(declarations):
            raise ValueError("声明身份判断未完整覆盖本次冻结来源")
        if require_coverage:
            if set(self.declaration_reviews) != set(declarations):
                raise ValueError("声明原始事实核对不完整")
            for identifier, review in self.declaration_reviews.items():
                if review.source_hash != declarations[identifier]["source_hash"]:
                    raise ValueError("声明事实核对的来源哈希已失效")

    def _validate_revisions(self, events: dict[str, CompleteEventDraft] | None = None) -> None:
        if self.revisions:
            raise ValueError("阶段从已确认声明原样生成，不接受无来源的额外 revision")

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
        if self.identity_snapshot is None or self.structure_snapshot is not None:
            raise ValueError("关系只能在身份冻结后、结构冻结前提交")
        self.read_events([source_id, target_id])
        if relation_type in {"main", "secondary", "contains", "containment", "same_identity"}:
            raise ValueError("身份、包含及旧主链标记不能伪装为普通事件关系")
        relation_id = stable_uuid("event_relation", self.run_id, self.work_id, key)
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
        # 核对快照故意保留，新增关系不能把原核对作者与剩余额度一起抹掉
        return relation_id

    def read_passages(self, paragraph_ids: list[int], offset: int = 0, limit: int = 10) -> dict[str, Any]:
        """有界读取真实原文；段号从工具回执获得，长段落按字符续读"""
        _page_size(len(paragraph_ids), 20)
        _page_size(limit, 20)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        rows = self.session.scalars(
            select(Paragraph)
            .where(Paragraph.run_id == self.run_id, Paragraph.paragraph_id.in_(paragraph_ids))
            .order_by(Paragraph.paragraph_id)
        ).all()
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
        arc_id = stable_uuid("narrative_arc", self.run_id, self.work_id, key)
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

    def review_events(self, event_ids: list[str], *, reason: str) -> None:
        """核对正式产物；无可证关联时明确说明，禁止为了覆盖而编造关联"""
        self.read_events(event_ids)
        reviews = {
            event_id: EventReviewDraft(
                event_id=event_id, reason=reason, snapshot_hash=self.event_snapshot(event_id), **self._source()
            )
            for event_id in event_ids
        }
        self.reviewed_events.update(reviews)

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
        outcome_id = stable_uuid("event_outcome", self.run_id, self.work_id, key)
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
        elif kind == "declaration":
            self.read_declarations([subject_id])
        elif kind == "fact":
            try:
                fact_id = int(subject_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("冲突事实主体必须是正式图谱事实流水号") from exc
            row = self.session.get(GraphFact, fact_id)
            producer_execution_id = None if row is None else row.direct_producer_execution_id
            if producer_execution_id is None or not _execution_in_run(self.session, producer_execution_id, self.run_id):
                raise ValueError("冲突事实主体不存在或不属于本 run")
        else:
            raise ValueError("冲突主体类型无效")

    def register_conflict(
        self,
        *,
        key: str,
        subject_kind: Literal["event", "declaration", "fact"],
        subject_id: str,
        claims: list[ConflictClaim],
        reason: str,
    ) -> str:
        """各项说法分别绑定证据，保留未解决，不裁定原文的唯一答案"""
        if not key.strip():
            raise ValueError("冲突稳定键不能为空")
        self._validate_subject(subject_kind, subject_id)
        # 每条陈述的真实来源是提交它的这次 work 调用，写入各自来源列而不是只挂在冲突登记行
        bound_claims = [
            BoundConflictClaim(claim=item.claim, evidence=self.bind_evidence(item.evidence), **self._source())
            for item in claims
        ]
        conflict_id = stable_uuid("diagnosis_conflict", self.run_id, self.work_id, key)
        self.conflicts[conflict_id] = ConflictDraft(
            conflict_id=conflict_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            claims=bound_claims,
            reason=reason,
            evidence=[ref for item in bound_claims for ref in item.evidence],
            **self._source(),
        )
        return conflict_id

    def read_conflicts(self, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """核对章节标注留下的冲突说法，保留其原始身份和来源"""
        _page_size(limit)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        rows = _run_conflicts(self.session, self.run_id)
        return {"items": rows[offset : offset + limit]}

    def read_draft(self, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """分别分页检查组织事实和完整事件覆盖审计"""
        _page_size(limit)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        groups: dict[str, list[BaseModel]] = {
            "events": list(self.events.values()),
            "revisions": list(self.revisions.values()),
            "relations": list(self.relations.values()),
            "arcs": list(self.arcs.values()),
            "event_arc_links": list(self.event_arc_links.values()),
            "outcomes": list(self.outcomes.values()),
            "event_outcome_links": list(self.event_outcome_links.values()),
            "conflicts": list(self.conflicts.values()),
            "reviewed_events": list(self.reviewed_events.values()),
        }
        return {
            **{
                name: [item.model_dump(mode="json") for item in values[offset : offset + limit]]
                for name, values in groups.items()
            },
            "totals": {name: len(values) for name, values in groups.items()},
        }

    def event_snapshot(self, event_id: str) -> str:
        return snapshot_digest(
            {
                "event": self.events[event_id].model_dump(mode="json"),
                "containments": record_payloads(
                    item
                    for item in self.containments.values()
                    if event_id in {item.parent_event_id, item.child_event_id}
                ),
                "relations": record_payloads(
                    item
                    for item in self.relations.values()
                    if event_id in {item.source_id, item.target_id}
                ),
            }
        )

    def freeze_identity(self) -> None:
        self.validate_events(require_coverage=True)
        rows = list(self._declarations())
        required = {(source, target) for index, source in enumerate(rows) for target in rows[index + 1 :]}
        if set(self.declaration_comparisons) != required:
            raise ValueError("来源比较清单未全部明确处置，不能冻结身份")
        groups = {identifier: item.event_id for item in self.events.values() for identifier in item.declaration_ids}
        for (source, target), item in self.declaration_comparisons.items():
            same = groups[source] == groups[target]
            if same != (item.disposition == "same_event"):
                raise CandidateConflict(
                    f"身份候选与来源比较相矛盾: {source} / {target}",
                    [
                        item.source_work_id,
                        *[
                            event.source_work_id
                            for event in self.events.values()
                            if {source, target} & set(event.declaration_ids)
                        ],
                    ],
                )
        digest = snapshot_digest(
            [
                item.model_dump(mode="json")
                for item in sorted(
                    (item for item in self.events.values() if item.declaration_ids), key=lambda item: item.event_id
                )
            ]
        )
        if self.identity_snapshot is not None and self.identity_snapshot != digest:
            raise ValueError("已冻结身份候选被改写")
        self.identity_snapshot = digest

    def freeze_structure(self) -> None:
        if self.identity_snapshot is None:
            raise ValueError("身份尚未冻结")
        parents = self._parents()
        for identifier in parents:
            try:
                self._event_hierarchy(identifier, parents)
            except ValueError as exc:
                raise CandidateConflict(str(exc), [edge.source_work_id for edge in self.containments.values()]) from exc
        events = sorted(self.events)
        required = {(source, target) for index, source in enumerate(events) for target in events[index + 1 :]}
        if set(self.structure_reviews) != required:
            raise ValueError("事件结构比较清单未完整处置")
        for pair, review in self.structure_reviews.items():
            if review.snapshot_hash != self.pair_snapshot(*pair):
                raise CandidateConflict(f"结构比较版本失效: endpoints={pair}", [review.source_work_id])
            parents = self._parents()
            source, target = review.source_event_id, review.target_event_id
            contains = parents.get(target) == source
            part_of = parents.get(source) == target
            related = any({item.source_id, item.target_id} == set(pair) for item in self.relations.values())
            actual = "contains" if contains else "part_of" if part_of else "related" if related else "independent"
            if review.disposition != actual:
                raise CandidateConflict(f"结构比较与显式接受记录不一致: endpoints={pair}", [review.source_work_id])
        if set(self.reviewed_events) != set(self.events):
            raise ValueError("事件结构核对不完整")
        for identifier, event_review in self.reviewed_events.items():
            if event_review.snapshot_hash != self.event_snapshot(identifier):
                raise CandidateConflict(f"事件结构核对版本改变: event_id={identifier}", [event_review.source_work_id])
        digest = snapshot_digest(
            {
                "events": record_payloads(self.events.values()),
                "containments": record_payloads(self.containments.values()),
                "relations": record_payloads(self.relations.values()),
            }
        )
        if self.structure_snapshot is not None and self.structure_snapshot != digest:
            raise ValueError("已冻结结构候选被改写")
        self.structure_snapshot = digest

    def finish(self) -> NarrativeOrganization:
        self.validate_events(require_coverage=True)
        if self.identity_snapshot is None or self.structure_snapshot is None:
            raise ValueError("身份和结构快照必须全部冻结后才能发布")
        result = NarrativeOrganization(
            source_execution_id=self.execution_id,
            events=list(self.events.values()),
            revisions=list(self.revisions.values()),
            relations=list(self.relations.values()),
            arcs=list(self.arcs.values()),
            event_arc_links=list(self.event_arc_links.values()),
            outcomes=list(self.outcomes.values()),
            event_outcome_links=list(self.event_outcome_links.values()),
            conflicts=list(self.conflicts.values()),
            reviewed_events=list(self.reviewed_events.values()),
            declaration_reviews=list(self.declaration_reviews.values()),
            declaration_comparisons=list(
                {
                    snapshot_digest(item.model_dump(mode="json")): item
                    for item in self.declaration_comparisons.values()
                }.values()
            ),
            containments=list(self.containments.values()),
            identity_snapshot=self.identity_snapshot,
            structure_snapshot=self.structure_snapshot,
            structure_reviews=list(self.structure_reviews.values()),
        )
        validate_organization(self.session, self.run_id, result)
        return result


def _work_of_execution(session: Session, execution_id: str) -> str | None:
    """执行的 work：session 形状无 work，真实 invocation 才有"""
    return smap.work_of_execution(session, execution_id)


def _execution_in_run(session: Session, execution_id: str, run_id: str) -> bool:
    """真实执行的本 run 归属：标注 work 直接带 run，诊断 work 经会话取得"""
    return smap.execution_in_run(session, execution_id, run_id)


def _annotation_chapter_of_execution(session: Session, execution_id: str) -> tuple[int | None, int | None]:
    """章级伏笔动作的来源章序：从其真实生产执行的标注 work 与章节取得"""
    return smap.annotation_chapter_of_execution(session, execution_id)


def _run_conflict_rows(session: Session, run_id: str) -> list[Any]:
    """本 run 的冲突记录：真实登记执行属于本 run 的标注或诊断 work"""
    return list(
        session.scalars(
            select(ConflictRecord)
            .where(ConflictRecord.producer_execution_id.in_(smap.run_execution_ids(run_id)))
            .order_by(ConflictRecord.conflict_id)
        )
    )


def _run_conflicts(session: Session, run_id: str) -> list[dict[str, Any]]:
    """冲突的读取形状：主体类型、逐条陈述及各自证据"""
    return smap.conflict_payloads(session, run_id)


def validate_organization(session: Session, run_id: str, organization: NarrativeOrganization) -> None:
    """保存前核对完整事件全量覆盖、同 run 端点、独立结果及每项真实证据"""
    organization = NarrativeOrganization.model_validate(organization.model_dump())
    records = _run_annotation_records(session, run_id)
    if any(row.contract_version != CONTRACT_VERSION for row, _work, _chapter in records):
        raise ValueError("章节正式产物属于旧契约，需要从原文重建")
    all_ids = set(_run_events(session, run_id))
    all_ids.update(item.event_id for item in organization.events)
    reviewed_ids = {item.event_id for item in organization.reviewed_events}
    if reviewed_ids != all_ids:
        raise ValueError(
            f"完整事件核对未全量覆盖: 缺少={sorted(all_ids - reviewed_ids)[:20]}, "
            f"无效={sorted(reviewed_ids - all_ids)[:20]}"
        )
    draft = EventOrganizationDraft(session, run_id)
    draft.events = {item.event_id: item for item in organization.events}
    draft.declaration_reviews = {item.declaration_id: item for item in organization.declaration_reviews}
    draft.containments = {(item.parent_event_id, item.child_event_id): item for item in organization.containments}
    draft.relations = {item.relation_id: item for item in organization.relations}
    draft.reviewed_events = {item.event_id: item for item in organization.reviewed_events}
    draft.structure_reviews = {
        (min(item.source_event_id, item.target_event_id), max(item.source_event_id, item.target_event_id)): item
        for item in organization.structure_reviews
    }
    for item in organization.declaration_comparisons:
        for target in item.target_declaration_ids:
            draft.declaration_comparisons[(item.source_declaration_id, target)] = item
    draft.validate_events(require_coverage=True)
    draft.freeze_identity()
    if draft.identity_snapshot != organization.identity_snapshot:
        raise ValueError("身份快照与实际来源判断不一致")
    draft.freeze_structure()
    if draft.structure_snapshot != organization.structure_snapshot:
        raise ValueError("结构快照与实际接受记录不一致")
    child_ids = set(draft._parents())
    for linked_event_id in [item.event_id for item in organization.event_arc_links] + [
        item.event_id for item in organization.event_outcome_links
    ]:
        if linked_event_id not in all_ids:
            raise ValueError("关联完整事件端点不属于本 run")
    if child_ids & {link.event_id for link in organization.event_outcome_links}:
        raise ValueError("全书结果贡献端点必须是顶层完整事件")
    for conflict in organization.conflicts:
        draft._validate_subject(conflict.subject_kind, conflict.subject_id)
    refs = [
        ref
        for records in (
            organization.events,
            organization.revisions,
            organization.relations,
            organization.arcs,
            organization.outcomes,
            organization.event_arc_links,
            organization.event_outcome_links,
            organization.conflicts,
            organization.containments,
            organization.declaration_comparisons,
            organization.structure_reviews,
        )
        for item in records
        for ref in item.evidence
    ]
    refs.extend(ref for item in organization.conflicts for claim in item.claims for ref in claim.evidence)
    for records in (
        organization.events,
        organization.containments,
        organization.relations,
        organization.arcs,
        organization.event_arc_links,
        organization.outcomes,
        organization.event_outcome_links,
        organization.conflicts,
        organization.declaration_comparisons,
    ):
        for record in records:
            if not record.source_work_id or not record.producer_invocation_id:
                raise ValueError("诊断贡献缺少真实 work 和调用来源")
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
        if outcome.first_text_position != min(
            positions[ref.paragraph_id] + ref.char_start for ref in outcome.evidence
        ):
            raise ValueError("结果正文排序位置必须由证据派生")


def _write_evidence_rows(session: Session, owner: dict[str, Any], evidence: list[Any]) -> None:
    """证据逐条按原顺序进入 source_evidence；owner 恰一由目标表 CHECK 保证"""
    smap.write_evidence_rows(session, owner, evidence)


def _require_report(session: Session, run_id: str, report_id: str, session_id: str | None) -> Any:
    """正式组织必须与本次诊断会话的报告一同保存，不接受其他产物冒充"""
    from src.storage.models import DiagnosisReport

    report = session.get(DiagnosisReport, report_id)
    if report is None:
        raise ValueError("全书组织必须与本任务诊断报告一同保存")
    owner = session.get(Execution, report.session_id)
    if owner is None or owner.session_run_id != run_id:
        raise ValueError("诊断报告不属于本运行")
    if session_id is not None and report.session_id != session_id:
        raise ValueError("诊断报告与本次诊断会话不一致")
    return report


def save_organization(session: Session, run_id: str, organization: NarrativeOrganization, report_id: str) -> None:
    """与诊断报告共用调用方事务；只替换本 run 的诊断组织，不改章节事件"""
    validate_organization(session, run_id, organization)
    _require_report(session, run_id, report_id, organization.source_execution_id)
    if _published_arc_ids(session, run_id):
        raise ValueError("叙事组织已发布，禁止替换旧运行产物")
    # 叙事线与结果同表两类形状：父线只能指向线，按父先子后逐层落库
    pending = {arc.arc_id: arc for arc in organization.arcs}
    saved: set[str] = set()
    while pending:
        ready = [arc for arc in pending.values() if arc.parent_arc_id is None or arc.parent_arc_id in saved]
        if not ready:
            raise ValueError("叙事线父级不存在或形成环，不能发布")
        for arc in ready:
            session.add(
                NarrativeGroup(
                    group_id=arc.arc_id,
                    producer_execution_id=arc.producer_invocation_id,
                    title=arc.title,
                    arc_kind=arc.kind,
                    arc_objective=arc.objective,
                    arc_role=arc.role,
                    arc_reason=arc.reason,
                    parent_arc_id=arc.parent_arc_id,
                )
            )
            saved.add(arc.arc_id)
            del pending[arc.arc_id]
        session.flush()
    for arc in organization.arcs:
        _write_evidence_rows(session, {"narrative_group_id": arc.arc_id}, arc.evidence)
    for item in organization.outcomes:
        session.add(
            NarrativeGroup(
                group_id=item.outcome_id,
                producer_execution_id=item.producer_invocation_id,
                title=item.title,
                outcome_description=item.description,
            )
        )
    session.flush()
    for item in organization.outcomes:
        _write_evidence_rows(session, {"narrative_group_id": item.outcome_id}, item.evidence)
    for link in organization.event_arc_links:
        link_id = stable_uuid("arc_link", link.event_id, link.arc_id)
        session.add(
            NarrativeLink(
                link_id=link_id,
                producer_execution_id=link.producer_invocation_id,
                reason=link.reason,
                member_event_id=link.event_id,
                arc_group_id=link.arc_id,
                arc_role=link.role,
            )
        )
        _write_evidence_rows(session, {"narrative_link_id": link_id}, link.evidence)
    for outcome_link in organization.event_outcome_links:
        link_id = stable_uuid("outcome_link", outcome_link.event_id, outcome_link.outcome_id)
        session.add(
            NarrativeLink(
                link_id=link_id,
                producer_execution_id=outcome_link.producer_invocation_id,
                reason=outcome_link.reason,
                member_event_id=outcome_link.event_id,
                outcome_group_id=outcome_link.outcome_id,
            )
        )
        _write_evidence_rows(session, {"narrative_link_id": link_id}, outcome_link.evidence)
    session.flush()
    _write_conflicts(session, organization)
    session.flush()


def _write_conflicts(session: Session, organization: NarrativeOrganization) -> None:
    """冲突登记：主体恰一类型，每条陈述保留自己的来源与独立证据"""
    subject_columns = {
        "event": "subject_event_id",
        "declaration": "subject_declaration_id",
        "fact": "subject_fact_id",
    }
    for conflict in organization.conflicts:
        subject_id: Any = (
            int(conflict.subject_id) if conflict.subject_kind == "fact" else conflict.subject_id
        )
        session.add(
            ConflictRecord(
                conflict_id=conflict.conflict_id,
                producer_execution_id=conflict.producer_invocation_id,
                reason=conflict.reason,
                **{subject_columns[conflict.subject_kind]: subject_id},
            )
        )
        # 诊断陈述与证据的 conflict_id/claim_id 外键不靠 ORM 表排序保证：冲突行先落库
        session.flush()
        for ordinal, claim in enumerate(conflict.claims):
            claim_id = stable_uuid("conflict_claim", conflict.conflict_id, str(ordinal))
            session.add(
                ConflictClaimRow(
                    claim_id=claim_id,
                    conflict_id=conflict.conflict_id,
                    claim_ordinal=ordinal,
                    producer_execution_id=claim.producer_invocation_id,
                    claim_text=claim.claim,
                )
            )
            session.flush()
            _write_evidence_rows(session, {"claim_id": claim_id}, claim.evidence)
        _write_evidence_rows(session, {"conflict_id": conflict.conflict_id}, conflict.evidence)
    session.flush()
