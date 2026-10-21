"""事件声明/完整事件/叙事组织测试夹具（六 agent 归属，本切片自足）

只做真实表行的分层写入：标注来源链（执行→正式记录）、章级声明与原文证据、
诊断整轮会话与真实尝试身份，以及沿正式保存入口（EventOrganizationDraft →
报告 → 完整事件 → 叙事组织）保存。夹具不复制旧 payload、不恢复旧行类型。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.diagnosis.schema import AgentAnalysis
from src.event_trees.organization import EventOrganizationDraft, OrganizationEvidence
from src.storage import new_id
from src.storage.models import (
    Agent,
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
    EventParticipant,
    GraphEntity,
    NarrativeLink,
    Paragraph,
    SourceEvidence,
)
from src.utils.identity import stable_digest
from tests.support.storage_fixtures import natural_record, storage_for


def report_case_anchor(run_id: str) -> str:
    """本 run 报告级组织单元的真实案例锚（与生产 report CaseUnit 同源）"""
    return stable_digest(run_id, "diagnosis_report")


def chapter_text(session: Session, run_id: str, chapter_id: int) -> str:
    row = natural_record(session, Chapter, {"run_id": run_id, "chapter_id": chapter_id})
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
    entity_id = new_id()
    session.add(GraphEntity(entity_id=entity_id, run_id=run_id, canonical_name=name, entity_type="character"))
    session.flush()
    return entity_id


def add_annotation_source(
    session: Session,
    run_id: str,
    chapter_id: int,
    *,
    role: str = "event",
) -> tuple[str, str]:
    """建立一份真实标注来源链（执行行直接带 run/章/角色），返回 (record_id, agent_id)"""
    agent_id = new_id()
    session.add(Agent(id=agent_id, run_id=run_id, type=role, status="success"))
    session.flush()
    record_id = new_id()
    session.add(
        ChapterAnnotation(
            record_id=record_id,
            agent_id=agent_id,
            run_id=run_id,
            chapter_id=chapter_id,
            role=role,
        )
    )
    session.flush()
    return record_id, agent_id


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
    payoff_likelihood: str | None = "medium",
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
    event_id = new_id()
    session.add(
        CompleteEvent(
            event_id=event_id,
            annotation_record_id=record_id,
            producer_agent_id=session.get(ChapterAnnotation, record_id).agent_id,
            from_chapter_id=paragraph.chapter_id,
            to_chapter_id=paragraph.chapter_id,
            local_key=local_key or f"el-{event_id}",
            title=title or (phrase or text[:12]),
            problem=problem,
            summary=summary if summary is not None else text,
            event_type=event_type,
            status=status,
            progress=progress,
            is_foreshadowing_root=is_foreshadowing_root,
            payoff_likelihood=payoff_likelihood if is_foreshadowing_root else None,
        )
    )
    session.flush()
    session.add(
        SourceEvidence(
            evidence_id=new_id(),
            ordinal=0,
            paragraph_id=int(paragraph.paragraph_id),
            start_char=start,
            end_char=end,
            complete_event_id=event_id,
        )
    )
    for ordinal, (name, role) in enumerate(participants):
        session.add(
            EventParticipant(
                participant_id=new_id(),
                event_id=event_id,
                participant_ordinal=ordinal,
                entity_id=ensure_character(session, run_id=str(paragraph.run_id), name=name),
                role=role,
            )
        )
    session.flush()
    return event_id


def add_diagnosis_context(session: Session, run_id: str) -> tuple[str, str]:
    "登记报告 Agent，返回组织写出者与审计身份"
    agent_id = new_id()
    session.add(Agent(id=agent_id, run_id=run_id, type="report", status="running"))
    session.flush()
    return agent_id, agent_id


def identity_every_declaration(
    session: Session,
    run_id: str,
    *,
    groups: list[list[str]] | None = None,
    context: tuple[str, str] | None = None,
) -> tuple[EventOrganizationDraft, dict[str, Any]]:
    """按显式分组提交声明核对、身份与全对比较（不保存）"""
    session_id, agent_id = context or add_diagnosis_context(session, run_id)
    draft = EventOrganizationDraft(storage_for(session), run_id, session_id)
    draft.fixture_session = session
    # 报告级组织单元：案例锚与生产 report 单元同源，调用来源是本次报告角色尝试
    draft.case_id = report_case_anchor(run_id)
    draft.producer_agent_id = agent_id
    from src.event_trees.diagnosis_persistence import hydrate_draft_from_run

    hydrate_draft_from_run(storage_for(session), run_id, draft)
    membership = {identifier: identifier for identifier in draft.events}
    return draft, {"membership": membership, "session_id": session_id, "agent_id": agent_id}


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
            elif any({item.source_id, item.target_id} == {source, target} for item in draft.relations.values()):
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
    from src.storage.repositories.diagnosis_event_writes import save_diagnosis_events
    from src.storage.repositories.organization_writes import save_organization
    from tests.support.storage_fixtures import insert_report_fixture

    organization = draft.finish()
    report_id = insert_report_fixture(
        session,
        run_id,
        str(draft.agent_id),
        AgentAnalysis(narrative_organization=organization, diagnosis=diagnosis),
    )
    save_diagnosis_events(session, run_id, organization, report_id)
    save_organization(session, run_id, organization, report_id)
    session.flush()
    return {item.event_id: item.event_id for item in organization.events}


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
    producer_agent_id: str,
    source_event_id: str,
    target_event_id: str,
    paragraph: Paragraph,
    relation_type: str = "reference",
    reason: str = "章级关系建议",
    operation_key: str | None = None,
) -> str:
    """章级声明之间的候选关系（标注期真实来源形状，带原文证据）"""
    link_id = new_id()
    session.add(
        NarrativeLink(
            link_id=link_id,
            producer_agent_id=producer_agent_id,
            reason=reason,
            semantic_source_event_id=source_event_id,
            semantic_target_event_id=target_event_id,
            relation_type=relation_type,
            source_operation_local_key=operation_key or f"proposal-{link_id}",
        )
    )
    session.flush()
    session.add(
        SourceEvidence(
            evidence_id=new_id(),
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
    producer_agent_id: str,
    source_event_id: str,
    paragraph: Paragraph,
    action_type: str = "setup",
    target_event_id: str | None = None,
    operation_key: str | None = None,
    operation_order: int = 0,
) -> str:
    """真实伏笔动作事实（root/target 事件身份是阶段声明绑定的读投影）"""
    from src.storage.models import EventForeshadowingAction

    action_id = new_id()
    session.add(
        EventForeshadowingAction(
            action_id=action_id,
            producer_agent_id=producer_agent_id,
            source_operation_local_key=operation_key or f"action-{action_id}",
            operation_order=operation_order,
            action_type=action_type,
            source_event_id=source_event_id,
            target_event_id=target_event_id,
        )
    )
    session.flush()
    session.add(
        SourceEvidence(
            evidence_id=new_id(),
            ordinal=0,
            paragraph_id=int(paragraph.paragraph_id),
            start_char=0,
            end_char=len(str(paragraph.text)),
            foreshadow_action_id=action_id,
        )
    )
    session.flush()
    return action_id
