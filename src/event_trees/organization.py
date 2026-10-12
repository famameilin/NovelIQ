"""全书组织的诊断草稿、证据查询和事务写入"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.storage.models import AnalysisOutput, EventNode, Paragraph
from src.storage.models.event_organization import EventMembership, EventReference, NarrativeArc
from src.utils.identity import stable_uuid


class OrganizationEvidence(BaseModel):
    """引用任务已保存事件；段落为空时只声明事件已有的章节依据"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: str = Field(min_length=1)
    paragraph_id: int | None = Field(default=None, ge=0)


class NarrativeArcDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    arc_id: str
    parent_arc_id: str | None = None
    kind: Literal["main", "subplot"]
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1)
    role: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence: list[OrganizationEvidence] = Field(min_length=1, max_length=100)


class EventMembershipDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: str
    arc_id: str | None = None
    role: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence: list[OrganizationEvidence] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def require_assignment_evidence(self) -> EventMembershipDraft:
        if self.arc_id is not None and not self.evidence:
            raise ValueError("已归属事件必须提供判断证据")
        return self


class EventReferenceDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    arc_id: str
    event_id: str
    role: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence: list[OrganizationEvidence] = Field(min_length=1, max_length=100)


class NarrativeOrganization(BaseModel):
    """一次诊断的最终组织事实，结构检查不替代主支线语义判断"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    arcs: list[NarrativeArcDraft] = Field(default_factory=list)
    memberships: list[EventMembershipDraft] = Field(default_factory=list)
    references: list[EventReferenceDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_structure(self) -> NarrativeOrganization:
        arcs = {arc.arc_id: arc for arc in self.arcs}
        members = {member.event_id: member for member in self.memberships}
        if len(arcs) != len(self.arcs) or len(members) != len(self.memberships):
            raise ValueError("叙事线身份或事件主要归属重复")
        for arc in self.arcs:
            current: str | None = arc.arc_id
            seen: set[str] = set()
            while current is not None:
                if current not in arcs:
                    raise ValueError(f"父级叙事线不存在: {current}")
                if current in seen:
                    raise ValueError(f"全书组织关系形成环: {current}")
                seen.add(current)
                current = arcs[current].parent_arc_id
        for member in self.memberships:
            if member.arc_id is not None and member.arc_id not in arcs:
                raise ValueError(f"事件归属叙事线不存在: {member.arc_id}")
        seen_refs: set[tuple[str, str]] = set()
        for ref in self.references:
            key = (ref.arc_id, ref.event_id)
            if key in seen_refs:
                raise ValueError("跨线引用重复")
            seen_refs.add(key)
            if ref.arc_id not in arcs or ref.event_id not in members:
                raise ValueError("跨线引用端点不存在")
            if members[ref.event_id].arc_id == ref.arc_id:
                raise ValueError("主要归属不能同时登记为跨线引用")
        return self


def _page_size(limit: int, maximum: int = 100) -> int:
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit 必须在 1 到 {maximum} 之间")
    return limit


def _event_dict(row: EventNode) -> dict[str, Any]:
    return {
        "event_id": row.event_id,
        "chapter_id": row.chapter_id,
        "chapter_order": row.chapter_order,
        "description": row.description,
        "tree_id": row.tree_id,
        "parent_event_id": row.parent_node_id,
        "participants": row.participants,
        "anchor_paragraph_ids": row.anchor_paragraph_ids,
        "evidence": row.evidence,
    }


class EventOrganizationDraft:
    """本轮工具只更新内存；成功完成后由诊断保存点提交一次"""

    def __init__(self, session: Session, run_id: str) -> None:
        self.session = session
        self.run_id = run_id
        self.arcs: dict[str, NarrativeArcDraft] = {}
        self.memberships: dict[str, EventMembershipDraft] = {}
        self.references: dict[tuple[str, str], EventReferenceDraft] = {}

    def search_events(
        self,
        query: str = "",
        *,
        chapter_id: int | None = None,
        tree_id: str | None = None,
        unassigned_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """有界分页覆盖已保存事件，局部组仅作为筛选条件"""
        _page_size(limit)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        stmt = select(EventNode).where(EventNode.run_id == self.run_id)
        if query:
            stmt = stmt.where(EventNode.description.icontains(query, autoescape=True))
        if chapter_id is not None:
            stmt = stmt.where(EventNode.chapter_id == chapter_id)
        if tree_id is not None:
            stmt = stmt.where(EventNode.tree_id == tree_id)
        if unassigned_only and self.memberships:
            stmt = stmt.where(EventNode.event_id.not_in(list(self.memberships)))
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.scalars(
            stmt.order_by(EventNode.chapter_order, EventNode.char_start, EventNode.event_id).offset(offset).limit(limit)
        ).all()
        return {
            "items": [_event_dict(row) for row in rows],
            "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
        }

    def read_events(self, event_ids: list[str]) -> list[dict[str, Any]]:
        """批量读取同一任务的真实事件，不能引用别的任务或未保存事件"""
        _page_size(len(event_ids))
        rows = self.session.scalars(
            select(EventNode).where(EventNode.run_id == self.run_id, EventNode.event_id.in_(event_ids))
        ).all()
        by_id = {row.event_id: row for row in rows}
        missing = set(event_ids) - set(by_id)
        if missing:
            raise ValueError(f"任务已保存事件不存在: {sorted(missing)}")
        return [_event_dict(by_id[event_id]) for event_id in event_ids]

    def read_passages(self, paragraph_ids: list[int], offset: int = 0, limit: int = 10) -> dict[str, Any]:
        """分段返回原文，长段落提供继续位置，避免一次灌入全文"""
        _page_size(len(paragraph_ids), 20)
        _page_size(limit, 20)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        rows = self.session.scalars(
            select(Paragraph)
            .where(Paragraph.run_id == self.run_id, Paragraph.paragraph_id.in_(paragraph_ids))
            .order_by(Paragraph.paragraph_id)
            .limit(limit)
        ).all()
        return {
            "items": [
                {
                    "paragraph_id": row.paragraph_id,
                    "chapter_id": row.chapter_id,
                    "text": row.text[offset : offset + 2000],
                    "next_offset": offset + 2000 if len(row.text) > offset + 2000 else None,
                }
                for row in rows
            ]
        }

    def _validate_evidence(self, evidence: list[OrganizationEvidence]) -> None:
        if not evidence:
            return
        events = {row["event_id"]: row for row in self.read_events(list({item.event_id for item in evidence}))}
        paragraph_ids = {item.paragraph_id for item in evidence if item.paragraph_id is not None}
        paragraphs = (
            {
                row.paragraph_id: row.chapter_id
                for row in self.session.scalars(
                    select(Paragraph).where(Paragraph.run_id == self.run_id, Paragraph.paragraph_id.in_(paragraph_ids))
                )
            }
            if paragraph_ids
            else {}
        )
        for item in evidence:
            if item.paragraph_id is None:
                continue
            if item.paragraph_id not in events[item.event_id]["anchor_paragraph_ids"]:
                raise ValueError(f"paragraph_id={item.paragraph_id} 不是事件 {item.event_id} 的真实锚点")
            if paragraphs.get(item.paragraph_id) != events[item.event_id]["chapter_id"]:
                raise ValueError("事件锚点原文不存在")

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
        """使用本轮稳定键登记或修正叙事线，不能按事件数量猜测主线"""
        if not key.strip():
            raise ValueError("叙事线稳定键不能为空")
        arc_id = stable_uuid("narrative_arc", self.run_id, key)
        arc = NarrativeArcDraft(
            arc_id=arc_id,
            parent_arc_id=parent_arc_id,
            kind=kind,
            title=title,
            objective=objective,
            role=role,
            reason=reason,
            evidence=evidence,
        )
        self._validate_evidence(arc.evidence)
        candidates = {**self.arcs, arc_id: arc}
        NarrativeOrganization(arcs=list(candidates.values()))
        self.arcs = candidates
        return arc_id

    def assign_events(
        self,
        event_ids: list[str],
        *,
        arc_id: str | None,
        role: str,
        reason: str,
        evidence: list[OrganizationEvidence],
    ) -> None:
        """批量归属或说明待归属原因，每个事件仍保存一条主要归属"""
        self.read_events(event_ids)
        self._validate_evidence(evidence)
        candidates = dict(self.memberships)
        references = {
            key: ref for key, ref in self.references.items() if not (ref.event_id in event_ids and ref.arc_id == arc_id)
        }
        for event_id in event_ids:
            candidates[event_id] = EventMembershipDraft(
                event_id=event_id, arc_id=arc_id, role=role, reason=reason, evidence=evidence
            )
        NarrativeOrganization(
            arcs=list(self.arcs.values()),
            memberships=list(candidates.values()),
            references=list(references.values()),
        )
        self.memberships = candidates
        self.references = references

    def reference_event(
        self,
        *,
        arc_id: str,
        event_id: str,
        role: str,
        reason: str,
        evidence: list[OrganizationEvidence],
    ) -> None:
        """跨线引用保留真实事件身份，不增加唯一事件数"""
        self.read_events([event_id])
        self._validate_evidence(evidence)
        ref = EventReferenceDraft(arc_id=arc_id, event_id=event_id, role=role, reason=reason, evidence=evidence)
        candidates = {**self.references, (arc_id, event_id): ref}
        NarrativeOrganization(
            arcs=list(self.arcs.values()),
            memberships=list(self.memberships.values()),
            references=list(candidates.values()),
        )
        self.references = candidates

    def read_draft(self, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """分页检查草稿归属，未登记的事件通过 search_events 查询"""
        _page_size(limit)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        members = sorted(self.memberships.values(), key=lambda item: item.event_id)
        arcs = sorted(self.arcs.values(), key=lambda item: item.arc_id)
        refs = sorted(self.references.values(), key=lambda item: (item.arc_id, item.event_id))
        return {
            "arcs": [item.model_dump() for item in arcs[offset : offset + limit]],
            "memberships": [item.model_dump() for item in members[offset : offset + limit]],
            "references": [item.model_dump() for item in refs[offset : offset + limit]],
            "totals": {"arcs": len(arcs), "memberships": len(members), "references": len(refs)},
        }

    def finish(self) -> NarrativeOrganization:
        result = NarrativeOrganization(
            arcs=list(self.arcs.values()),
            memberships=list(self.memberships.values()),
            references=list(self.references.values()),
        )
        validate_organization(self.session, self.run_id, result)
        return result


def validate_organization(session: Session, run_id: str, organization: NarrativeOrganization) -> None:
    """正常写入时核对任务范围、真实证据和全部事件覆盖，不设读取就绪门槛"""
    organization = NarrativeOrganization.model_validate(organization.model_dump())
    all_ids = set(session.scalars(select(EventNode.event_id).where(EventNode.run_id == run_id)))
    membership_ids = {item.event_id for item in organization.memberships}
    if membership_ids != all_ids:
        raise ValueError(
            f"全书事件归属未覆盖真实事件: 缺少={sorted(all_ids - membership_ids)[:20]}, "
            f"无效={sorted(membership_ids - all_ids)[:20]}"
        )
    draft = EventOrganizationDraft(session, run_id)
    # 批量归属常复用同一判断证据，去重分批校验避免逐事件重复查库
    evidence = list(
        {
            (ref.event_id, ref.paragraph_id): ref
            for item in [*organization.arcs, *organization.memberships, *organization.references]
            for ref in item.evidence
        }.values()
    )
    for start in range(0, len(evidence), 100):
        draft._validate_evidence(evidence[start : start + 100])


def save_organization(
    session: Session,
    run_id: str,
    organization: NarrativeOrganization,
    annotation_id: str,
) -> None:
    """组织表和诊断产物共用调用方事务，失败由诊断保存点整体回滚"""
    validate_organization(session, run_id, organization)
    output = session.get(AnalysisOutput, annotation_id)
    if output is None or output.run_id != run_id or output.kind != "agent_analysis":
        raise ValueError("全书组织必须与本任务诊断产物一同保存")
    for model in (EventReference, EventMembership):
        session.execute(delete(model).where(model.run_id == run_id))
    # 先清父引用再替换，避免自引用外键令同一任务的重新诊断删除失败
    from sqlalchemy import update

    session.execute(update(NarrativeArc).where(NarrativeArc.run_id == run_id).values(parent_arc_id=None))
    session.execute(delete(NarrativeArc).where(NarrativeArc.run_id == run_id))
    pending = {arc.arc_id: arc for arc in organization.arcs}
    saved: set[str] = set()
    while pending:
        ready = [arc for arc in pending.values() if arc.parent_arc_id is None or arc.parent_arc_id in saved]
        for arc in ready:
            session.add(NarrativeArc(run_id=run_id, annotation_id=annotation_id, **arc.model_dump(mode="json")))
            saved.add(arc.arc_id)
            del pending[arc.arc_id]
        session.flush()
    session.add_all(
        [
            EventMembership(run_id=run_id, annotation_id=annotation_id, **item.model_dump(mode="json"))
            for item in organization.memberships
        ]
    )
    session.add_all(
        [
            EventReference(run_id=run_id, annotation_id=annotation_id, **item.model_dump(mode="json"))
            for item in organization.references
        ]
    )
    session.flush()
