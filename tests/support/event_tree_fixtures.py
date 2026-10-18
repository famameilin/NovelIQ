"""事件声明/完整事件/叙事组织测试夹具（六 agent 归属，本切片自足）

只做真实表行的分层写入：标注来源链（执行→正式记录）、章级声明与原文证据、
诊断整轮会话与真实尝试身份，以及沿正式保存入口（EventOrganizationDraft →
报告 → 完整事件 → 叙事组织）保存。夹具不复制旧 payload、不恢复旧行类型。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.diagnosis.schema import AgentAnalysis
from src.event_trees.organization import (
    EventOrganizationDraft,
    OrganizationEvidence,
    register_diagnosis_execution,
    register_diagnosis_session,
)
from src.storage.models import (
    Chapter,
    ChapterAnnotation,
    DeclarationParticipant,
    EventDeclaration,
    Execution,
    GraphEntity,
    NarrativeLink,
    Paragraph,
    SourceEvidence,
    naive_utcnow,
)
from src.utils.identity import stable_digest

CONTRACT_VERSION = "event-tree-declarations-v1"


def report_case_anchor(run_id: str) -> str:
    """本 run 报告级组织单元的真实案例锚（与生产 report CaseUnit 同源）"""
    return stable_digest(run_id, "diagnosis_report")


def chapter_text(session: Session, run_id: str, chapter_id: int) -> str:
    row = session.get(Chapter, {"run_id": run_id, "chapter_id": chapter_id})
    if row is None or row.text is None:
        raise ValueError(f"章节没有原文: run_id={run_id} chapter_id={chapter_id}")
    return str(row.text)


def paragraphs_of(session: Session, run_id: str, chapter_id: int) -> list[Paragraph]:
    return list(
        session.scalars(
            select(Paragraph)
            .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id)
            .order_by(Paragraph.paragraph_index)
        )
    )


def first_paragraph(session: Session, run_id: str, *, chapter_id: int = 1) -> Paragraph:
    rows = paragraphs_of(session, run_id, chapter_id)
    if not rows:
        raise ValueError(f"章节没有段落事实源: run_id={run_id} chapter_id={chapter_id}")
    return rows[0]


def ensure_character(session: Session, *, run_id: str, name: str) -> str:
    """参与者引用的正式角色实体：同 run 内按规范名取唯一身份"""
    existing = session.scalar(
        select(GraphEntity).where(
            GraphEntity.run_id == run_id,
            GraphEntity.canonical_name == name,
            GraphEntity.entity_type == "character",
        )
    )
    if existing is not None:
        return str(existing.entity_id)
    entity_id = str(uuid4())
    session.add(
        GraphEntity(entity_id=entity_id, run_id=run_id, canonical_name=name, entity_type="character")
    )
    session.flush()
    return entity_id


def add_annotation_source(
    session: Session,
    run_id: str,
    chapter_id: int,
    *,
    role: str = "event",
    contract_version: str = CONTRACT_VERSION,
) -> tuple[str, str]:
    """建立一份真实标注来源链（执行行直接带 run/章/角色），返回 (record_id, execution_id)"""
    execution_id = uuid4().hex
    session.add(
        Execution(
            execution_id=execution_id,
            run_id=run_id,
            chapter_id=chapter_id,
            role=role,
            attempt_number=1,
            started_at=naive_utcnow(),
            status="success",
        )
    )
    session.flush()
    record_id = str(uuid4())
    session.add(
        ChapterAnnotation(
            record_id=record_id,
            execution_id=execution_id,
            run_id=run_id,
            chapter_id=chapter_id,
            role=role,
            contract_version=contract_version,
            chapter_consolidation_version="v1",
        )
    )
    session.flush()
    return record_id, execution_id


def add_declaration(
    session: Session,
    *,
    record_id: str,
    paragraph: Paragraph,
    phrase: str | None = None,
    title: str | None = None,
    problem: str = "能否完成本项行动",
    summary: str | None = None,
    event_type: str = "行动",
    status: str = "ongoing",
    progress: str | None = None,
    is_foreshadowing_root: bool = False,
    payoff_likelihood: str | None = None,
    participants: tuple[tuple[str, str], ...] = (),
    local_key: str | None = None,
) -> str:
    """写入不可变章级声明及其首条原文证据（quote 为 None 时取整段）"""
    text = str(paragraph.text)
    if phrase is None:
        start, end = 0, len(text)
    else:
        start = text.find(phrase)
        if start < 0:
            raise ValueError(f"声明引文不在段落原文中: phrase={phrase!r}")
        end = start + len(phrase)
    declaration_id = str(uuid4())
    session.add(
        EventDeclaration(
            declaration_id=declaration_id,
            record_id=record_id,
            local_key=local_key or f"el-{declaration_id[:8]}",
            title=title or (phrase or text[:12]),
            problem=problem,
            summary=summary if summary is not None else text,
            event_type=event_type,
            status=status,
            progress=progress,
            is_foreshadowing_root=is_foreshadowing_root,
            payoff_likelihood=payoff_likelihood,
        )
    )
    session.flush()
    session.add(
        SourceEvidence(
            evidence_id=str(uuid4()),
            ordinal=0,
            paragraph_id=int(paragraph.paragraph_id),
            start_char=start,
            end_char=end,
            declaration_id=declaration_id,
        )
    )
    for ordinal, (name, role) in enumerate(participants):
        session.add(
            DeclarationParticipant(
                participant_id=str(uuid4()),
                declaration_id=declaration_id,
                participant_ordinal=ordinal,
                entity_id=ensure_character(session, run_id=str(paragraph.run_id), name=name),
                role=role,
            )
        )
    session.flush()
    return declaration_id


def add_diagnosis_context(session: Session, run_id: str) -> tuple[str, str]:
    """登记诊断整轮会话与报告角色的真实尝试，返回 (session_id, execution_id)

    同一 run 再次登记是本轮的又一次真实尝试（跨轮累计序号），不覆盖既有终态行。
    """
    from sqlalchemy import func

    session_id = f"diag-session-{uuid4().hex[:12]}"
    execution_id = uuid4().hex
    attempt = int(
        session.scalar(
            select(func.count()).select_from(Execution).where(Execution.run_id == run_id, Execution.role == "report")
        )
        or 0
    ) + 1
    register_diagnosis_session(session, run_id=run_id, session_id=session_id)
    register_diagnosis_execution(
        session, run_id=run_id, execution_id=execution_id, role="report", attempt_number=attempt
    )
    return session_id, execution_id


def identity_every_declaration(
    session: Session,
    run_id: str,
    *,
    groups: list[list[str]] | None = None,
    context: tuple[str, str] | None = None,
) -> tuple[EventOrganizationDraft, dict[str, Any]]:
    """按显式分组提交声明核对、身份与全对比较（不保存）"""
    session_id, execution_id = context or add_diagnosis_context(session, run_id)
    draft = EventOrganizationDraft(session, run_id, session_id)
    # 报告级组织单元：案例锚与生产 report 单元同源，调用来源是本次报告角色尝试
    draft.case_id = report_case_anchor(run_id)
    draft.producer_invocation_id = execution_id
    rows = list(draft._declarations().values())
    by_id = {row["declaration_id"]: row for row in rows}
    groups = groups if groups is not None else [[row["declaration_id"]] for row in rows]
    membership = {identifier: index for index, group in enumerate(groups) for identifier in group}
    for group in groups:
        current = by_id[group[-1]]
        draft.identity(
            key=group[0],
            title=current["title"],
            problem=current["problem"],
            summary=current["summary"],
            event_type=current["event_type"],
            status=current["status"],
            progress=current["progress"],
            declaration_ids=list(group),
            stage_order=list(group),
            current_declaration_id=group[-1],
            reason="夹具显式判断本组声明组成一个事件身份",
            evidence=[
                OrganizationEvidence(paragraph_id=item["paragraph_id"]) for item in row_evidence(by_id[group[0]])
            ],
        )
        draft.review_declarations(list(group), reason="夹具已逐项核对不可变声明与原文")
    for index, row in enumerate(rows):
        for target in rows[index + 1 :]:
            source_id, target_id = row["declaration_id"], target["declaration_id"]
            draft.compare_declarations(
                source_declaration_id=source_id,
                target_declaration_ids=[target_id],
                disposition="same_event" if membership[source_id] == membership[target_id] else "independent",
                reason="夹具按显式分组核对两项声明身份",
                evidence=[OrganizationEvidence(paragraph_id=row_evidence(row)[0]["paragraph_id"])],
            )
    return draft, {"membership": membership, "session_id": session_id, "execution_id": execution_id}


def row_evidence(row: dict[str, Any]) -> list[dict[str, Any]]:
    return list(row["evidence"])


def close_structure(
    session: Session,
    draft: EventOrganizationDraft,
    *,
    evidence_paragraph_id: int,
) -> None:
    """按草稿已提交的包含/关系逐对收口结构判断并核对全部事件（不保存）"""
    events = sorted(draft.events)
    for index, source in enumerate(events):
        for target in events[index + 1 :]:
            if (source, target) in draft.containments:
                disposition = "contains"
            elif (target, source) in draft.containments:
                disposition = "part_of"
            elif any(
                {item.source_id, item.target_id} == {source, target} for item in draft.relations.values()
            ):
                disposition = "related"
            else:
                disposition = "independent"
            draft.structure_review(
                source_event_id=source,
                target_event_id=target,
                disposition=disposition,
                reason="夹具按本例显式提交的包含/关系完成结构判断",
                evidence=[OrganizationEvidence(paragraph_id=evidence_paragraph_id)],
            )
    for event_id in events:
        draft.review_events([event_id], reason="夹具已核对正式身份与结构")


def publish_draft(
    session: Session,
    run_id: str,
    draft: EventOrganizationDraft,
    *,
    diagnosis: str | None = None,
) -> dict[str, str]:
    """沿正式保存入口保存报告、完整事件与叙事组织，返回声明→事件映射"""
    from src.agents.diagnosis.persistence import save_diagnosis_report
    from src.event_trees.diagnosis_persistence import save_diagnosis_events
    from src.event_trees.organization import save_organization

    organization = draft.finish()
    report_id = save_diagnosis_report(
        session,
        run_id,
        str(draft.execution_id),
        AgentAnalysis(narrative_organization=organization, diagnosis=diagnosis),
    )
    save_diagnosis_events(session, run_id, organization, report_id)
    save_organization(session, run_id, organization, report_id)
    session.flush()
    return {
        declaration_id: item.event_id
        for item in organization.events
        for declaration_id in item.declaration_ids
    }


def publish_declarations(
    session: Session,
    run_id: str,
    *,
    groups: list[list[str]] | None = None,
    evidence_paragraph_id: int | None = None,
    diagnosis: str | None = None,
) -> tuple[dict[str, str], EventOrganizationDraft]:
    """一步保存全部声明的独立/同组身份，返回 (声明→事件, 草稿)"""
    draft, _meta = identity_every_declaration(session, run_id, groups=groups)
    paragraph_id = (
        first_paragraph(session, run_id).paragraph_id if evidence_paragraph_id is None else evidence_paragraph_id
    )
    close_structure(session, draft, evidence_paragraph_id=int(paragraph_id))
    mapping = publish_draft(session, run_id, draft, diagnosis=diagnosis)
    return mapping, draft


def add_declaration_relation(
    session: Session,
    *,
    producer_execution_id: str,
    source_declaration_id: str,
    target_declaration_id: str,
    paragraph: Paragraph,
    relation_type: str = "reference",
    reason: str = "章级关系建议",
    operation_key: str | None = None,
) -> str:
    """章级声明之间的候选关系（标注期真实来源形状，带原文证据）"""
    link_id = str(uuid4())
    session.add(
        NarrativeLink(
            link_id=link_id,
            producer_execution_id=producer_execution_id,
            reason=reason,
            semantic_source_declaration_id=source_declaration_id,
            semantic_target_declaration_id=target_declaration_id,
            relation_type=relation_type,
            source_operation_local_key=operation_key or f"proposal-{link_id[:8]}",
        )
    )
    session.flush()
    session.add(
        SourceEvidence(
            evidence_id=str(uuid4()),
            ordinal=0,
            paragraph_id=int(paragraph.paragraph_id),
            start_char=0,
            end_char=len(str(paragraph.text)),
            narrative_link_id=link_id,
        )
    )
    session.flush()
    return link_id


def add_foreshadowing_action(
    session: Session,
    *,
    producer_execution_id: str,
    source_declaration_id: str,
    paragraph: Paragraph,
    action_type: str = "setup",
    target_declaration_id: str | None = None,
    operation_key: str | None = None,
    operation_order: int = 0,
) -> str:
    """真实伏笔动作事实（root/target 事件身份是阶段声明绑定的读投影）"""
    from src.storage.models import EventForeshadowingAction

    action_id = str(uuid4())
    session.add(
        EventForeshadowingAction(
            action_id=action_id,
            producer_execution_id=producer_execution_id,
            source_operation_local_key=operation_key or f"action-{action_id[:8]}",
            operation_order=operation_order,
            action_type=action_type,
            source_declaration_id=source_declaration_id,
            target_declaration_id=target_declaration_id,
        )
    )
    session.flush()
    session.add(
        SourceEvidence(
            evidence_id=str(uuid4()),
            ordinal=0,
            paragraph_id=int(paragraph.paragraph_id),
            start_char=0,
            end_char=len(str(paragraph.text)),
            foreshadow_action_id=action_id,
        )
    )
    session.flush()
    return action_id
