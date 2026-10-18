"""诊断完整事件组织的真实原文、多对多关系与保存事务验证（2026-10-16 全库 3NF 改造）

夹具自足：直接建立真实来源链（标注 work/执行/记录 + 章级声明 + 诊断会话/work/执行），
发布走正式入口（diagnosis_reports → complete_events/event_revisions → narrative_links）。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from src.agents.diagnosis.persistence import save_diagnosis_result
from src.agents.diagnosis.tools import build_diagnosis_tools
from src.diagnosis.read import fetch_diagnosis_payload
from src.diagnosis.schema import AgentAnalysis
from src.event_trees.diagnosis_persistence import save_diagnosis_events
from src.event_trees.organization import (
    ConflictClaim,
    EventOrganizationDraft,
    NarrativeOrganization,
    OrganizationEvidence,
    save_organization,
    validate_organization,
)
from src.storage.models import (
    ConflictClaim as ConflictClaimRow,
)
from src.storage.models import (
    ConflictRecord,
    DiagnosisReport,
    EventRevision,
    Execution,
    NarrativeGroup,
    NarrativeLink,
)
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import (
    add_annotation_source,
    add_declaration,
    add_diagnosis_context,
    first_paragraph,
    report_case_anchor,
)

CONTRACT = "event-tree-declarations-v1"
TEXTS = ["顾霜找回了身份。贺重明证实身份。", "他说等待了十年。她说等待了十四年。"]
PHRASES = ("找回了身份", "等待了十年", "贺重明")


class OrganizationCase:
    """三章原文 + 三份真实声明 + 诊断会话/work/执行身份"""

    def __init__(self, session, *, chapters: int = 3) -> None:
        self.session = session
        self.run_id = ""
        self.novel_id, self.run_id = create_run_with_chunks(
            session,
            texts=[TEXTS[index % len(TEXTS)] for index in range(chapters)],
            chapter_ids=list(range(1, chapters + 1)),
            title="组织测试",
        )
        self.session_id, self.execution_id = add_diagnosis_context(session, self.run_id)
        self.declarations: list[str] = []
        for chapter_id in range(1, chapters + 1):
            record_id, _execution_id = add_annotation_source(
                session, self.run_id, chapter_id, role="event"
            )
            phrase = PHRASES[(chapter_id - 1) % len(PHRASES)]
            declaration_id = add_declaration(
                session,
                record_id=record_id,
                paragraph=first_paragraph(session, self.run_id, chapter_id=chapter_id),
                phrase=phrase,
                title=f"身份问题{len(self.declarations)}",
                problem="能否确认身份",
                summary=f"章节概要{len(self.declarations)}",
                event_type="身份确认",
            )
            self.declarations.append(declaration_id)
        session.flush()


def identity_draft(session, case: OrganizationCase) -> EventOrganizationDraft:
    """逐项提交身份判断、声明核对与来源比较，随后冻结身份"""
    draft = EventOrganizationDraft(session, case.run_id, case.session_id)
    draft.case_id = report_case_anchor(case.run_id)
    draft.producer_invocation_id = case.execution_id
    sources = list(draft._declarations().values())
    for row in sources:
        evidence = [OrganizationEvidence(paragraph_id=row["evidence"][0]["paragraph_id"])]
        draft.identity(
            key=row["declaration_id"],
            title=row["title"],
            problem=row["problem"],
            summary=row["summary"],
            event_type=row["event_type"],
            status=row["status"],
            progress=row["progress"],
            declaration_ids=[row["declaration_id"]],
            stage_order=[row["declaration_id"]],
            current_declaration_id=row["declaration_id"],
            reason="本例按原文明确判断每项声明为一个事件身份",
            evidence=evidence,
        )
        draft.review_declarations([row["declaration_id"]], reason="逐项核对不可变声明与原文")
    for index, row in enumerate(sources):
        for target in sources[index + 1 :]:
            draft.compare_declarations(
                source_declaration_id=row["declaration_id"],
                target_declaration_ids=[target["declaration_id"]],
                disposition="independent",
                reason="本例各声明是独立问题",
                evidence=[OrganizationEvidence(paragraph_id=row["evidence"][0]["paragraph_id"])],
            )
    draft.freeze_identity()
    return draft


@pytest.fixture
def organization_case(db_session):
    case = OrganizationCase(db_session, chapters=3)
    db_session.commit()
    draft = identity_draft(db_session, case)
    event_ids = list(draft.events)
    draft.contain(
        parent_event_id=event_ids[0],
        child_event_id=event_ids[2],
        reason="确认身份中的子问题",
        evidence=[OrganizationEvidence(paragraph_id=0, quote="找回了身份")],
    )
    return case, event_ids, draft


def _freeze_structure(draft):
    ids = list(draft.events)
    for index, source in enumerate(ids):
        for target in ids[index + 1 :]:
            disposition = (
                "contains"
                if (source, target) in draft.containments
                else "part_of"
                if (target, source) in draft.containments
                else "independent"
            )
            draft.structure_review(
                source_event_id=source,
                target_event_id=target,
                disposition=disposition,
                reason="本测试按已明确声明的包含或独立关系完成比较",
                evidence=[OrganizationEvidence(paragraph_id=0)],
            )
    draft.freeze_structure()


def _arc(draft, key="identity"):
    return draft.register_arc(
        key=key,
        kind="main",
        title="身份线",
        objective="确认身份",
        role="主线",
        reason="围绕身份冲突持续发展",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )


def _organized(draft, event_ids):
    arc_a, arc_b = _arc(draft), _arc(draft, "relationship")
    for arc in (arc_a, arc_b):
        draft.link_event_arc(
            event_id=event_ids[0],
            arc_id=arc,
            role="推动",
            reason="推动对应问题",
            evidence=[OrganizationEvidence(paragraph_id=0, quote="找回了身份")],
        )
    draft.review_events(event_ids, reason="已核对各事件身份及结构，关联依据单独记录")
    outcome = draft.register_outcome(
        key="recognized",
        title="身份获确认",
        description="两人的行动使身份得到确认",
        evidence=[OrganizationEvidence(paragraph_id=0, quote="证实身份")],
    )
    for event_id in event_ids[:2]:
        draft.link_event_outcome(
            event_id=event_id,
            outcome_id=outcome,
            reason="对身份确认作出贡献",
            evidence=[OrganizationEvidence(paragraph_id=0, quote="找回了身份", event_id=event_id)],
        )
    _freeze_structure(draft)
    return draft.finish()


def _publish(session, run_id, organization):
    """与正式发布同序：先报告与完整事件，再叙事组织"""
    from src.agents.diagnosis.persistence import save_diagnosis_report

    report_id = save_diagnosis_report(
        session, run_id, organization.source_execution_id, AgentAnalysis(narrative_organization=organization)
    )
    save_diagnosis_events(session, run_id, organization, report_id)
    save_organization(session, run_id, organization, report_id)
    session.commit()
    return report_id


def test_complete_event_current_content_comes_from_bound_declaration(db_session, organization_case):
    case, event_ids, draft = organization_case
    organization = _organized(draft, event_ids)
    report_id = _publish(db_session, case.run_id, organization)
    assert len(
        [row for row in db_session.scalars(select(NarrativeLink)) if row.arc_group_id is not None]
    ) == 2
    outcomes = [
        row for row in db_session.scalars(select(NarrativeGroup)) if row.outcome_description is not None
    ]
    assert len(outcomes) == 1
    assert len(
        [row for row in db_session.scalars(select(NarrativeLink)) if row.outcome_group_id is not None]
    ) == 2
    # 当前内容从声明绑定读取；绑定声明是显式阶段链尾
    stages = list(
        db_session.scalars(
            select(EventRevision)
            .where(EventRevision.event_id == event_ids[0])
            .order_by(EventRevision.stage_index)
        )
    )
    current = stages[-1]
    assert current.declaration_id == draft.events[event_ids[0]].current_declaration_id
    # 已发布事件的内容由绑定声明投影读出，不再有第二份可写副本
    from src.event_trees.organization import _run_event_dicts

    db_session.expire_all()
    source = draft._declarations()[current.declaration_id]
    projected = _run_event_dicts(db_session, case.run_id)[event_ids[0]]
    assert projected["summary"] == source["summary"]
    assert projected["event_type"] == source["event_type"]
    assert projected["current_revision_id"] == current.revision_id
    assert organization.event_arc_links[0].evidence != organization.outcomes[0].evidence
    assert "memberships" not in organization.model_dump()
    assert "outcome_arc_links" not in organization.model_dump()
    report = db_session.get(DiagnosisReport, report_id)
    assert report is not None and report.session_id == case.session_id


def test_finish_covers_complete_events_and_unlinked_reviews(organization_case):
    _case, event_ids, draft = organization_case
    assert draft.search_events(limit=1)["total"] == 3
    draft.review_events(event_ids[:2], reason="暂无可证关联")
    assert draft.search_events(unreviewed_only=True)["items"][0]["event_id"] == event_ids[2]
    with pytest.raises(ValueError, match="核对不完整"):
        _freeze_structure(draft)
    draft.review_events(event_ids[2:], reason="子事件产物已核对")
    _freeze_structure(draft)
    assert len(draft.finish().reviewed_events) == 3


def test_evidence_uses_real_quote_and_rejects_model_coordinates(organization_case):
    _case, _event_ids, draft = organization_case
    bound = draft.bind_evidence([OrganizationEvidence(paragraph_id=0, quote="找回了身份")])[0]
    assert bound.char_start == 2
    assert bound.char_end == 7
    with pytest.raises(ValueError, match="不匹配原文"):
        draft.bind_evidence([OrganizationEvidence(paragraph_id=0, quote="伪造引文")])
    with pytest.raises(ValueError, match="不存在"):
        draft.bind_evidence([OrganizationEvidence(paragraph_id=1000)])
    with pytest.raises(ValidationError):
        OrganizationEvidence(paragraph_id=0, char_start=0, text_hash="invented")


def test_save_revalidates_bound_source_hash(db_session, organization_case):
    case, event_ids, draft = organization_case
    organization = _organized(draft, event_ids)
    payload = organization.model_dump()
    payload["event_arc_links"][0]["evidence"][0]["text_hash"] = "invented"
    with pytest.raises(ValueError, match="哈希"):
        validate_organization(db_session, case.run_id, NarrativeOrganization.model_validate(payload))


def test_outcome_has_independent_identity_and_requires_each_relation(organization_case):
    _case, event_ids, draft = organization_case
    draft.review_events(event_ids, reason="已核对")
    outcome = draft.register_outcome(
        key="identity",
        title="身份确认",
        description="身份最终得到证实",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    assert outcome == draft.register_outcome(
        key="identity",
        title="身份确认",
        description="身份最终得到证实",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    with pytest.raises(ValueError, match="贡献关系"):
        _freeze_structure(draft)
        draft.finish()
    with pytest.raises(ValueError, match="顶层"):
        draft.link_event_outcome(
            event_id=event_ids[2],
            outcome_id=outcome,
            reason="子问题结束",
            evidence=[OrganizationEvidence(paragraph_id=0)],
        )
    with pytest.raises(ValueError, match="limit"):
        draft.link_event_outcome(event_id=event_ids[0], outcome_id=outcome, reason="形成结果", evidence=[])


def test_cross_run_complete_event_is_rejected(db_session, organization_case):
    _case, event_ids, _draft = organization_case
    other = OrganizationCase(db_session, chapters=1)
    db_session.flush()
    with pytest.raises(ValueError, match="本任务事件不存在"):
        EventOrganizationDraft(db_session, other.run_id).read_events([event_ids[0]])


def test_conflict_preserves_each_claim_and_only_unresolved(db_session, organization_case):
    case, event_ids, draft = organization_case
    draft.review_events(event_ids, reason="核对两种原文说法")
    conflict_id = draft.register_conflict(
        key="waiting",
        subject_kind="event",
        subject_id=event_ids[0],
        claims=[
            ConflictClaim(claim="等待十年", evidence=[OrganizationEvidence(paragraph_id=1, quote="十年")]),
            ConflictClaim(claim="等待十四年", evidence=[OrganizationEvidence(paragraph_id=1, quote="十四年")]),
        ],
        reason="同一次等待时长的两项说法不一致",
    )
    _freeze_structure(draft)
    organization = draft.finish()
    _publish(db_session, case.run_id, organization)
    row = db_session.get(ConflictRecord, conflict_id)
    claims = list(
        db_session.scalars(
            select(ConflictClaimRow)
            .where(ConflictClaimRow.conflict_id == conflict_id)
            .order_by(ConflictClaimRow.claim_ordinal)
        )
    )
    assert [item.claim_text for item in claims] == ["等待十年", "等待十四年"]
    assert row.reason == "同一次等待时长的两项说法不一致"
    assert len(draft.read_conflicts()["items"]) == 1
    assert draft.read_conflicts()["items"][0]["resolution"] == "unresolved"
    first_conflict = draft.read_conflicts()["items"][0]["claims"][0]
    assert first_conflict["claim"] == "等待十年"
    payload = organization.model_dump()
    payload["conflicts"][0]["resolution"] = "ten_years"
    with pytest.raises(ValidationError):
        NarrativeOrganization.model_validate(payload)


def _finalized_submission(session, case, draft, event_ids, *, diagnosis):
    """与 DiagnosisDomain.publish 同口径绑定运行时字段后提交，重投核验按正式合同字段比较"""
    from src.diagnosis.queries import DiagnosisQueries

    bindings = {
        declaration_id: event.event_id for event in draft.events.values() for declaration_id in event.declaration_ids
    }
    organization = _organized(draft, event_ids)
    return AgentAnalysis(
        novel_id=case.novel_id,
        foreshadow_expectation=DiagnosisQueries(session).calculate_foreshadow_expectation(
            case.run_id, declaration_bindings=bindings
        ),
        narrative_organization=organization,
        diagnosis=diagnosis,
    )


def test_same_frozen_publication_replay_keeps_report_and_case_warnings(db_session, organization_case):
    case, event_ids, draft = organization_case
    analysis = _finalized_submission(db_session, case, draft, event_ids, diagnosis="完整已核对结果")
    save_diagnosis_result(db_session, case.run_id, analysis)
    report = _report_for(db_session, case.run_id)
    assert report is not None
    report_id = report.report_id
    from src.storage.models import CaseEntry

    db_session.add(
        CaseEntry(
            entry_id="warning-entry-0",
            warning_report_id=report_id,
            warning_ordinal=0,
            attempted_case_reference="case-x",
            warning_message="案例保存失败",
        )
    )
    db_session.commit()
    save_diagnosis_result(db_session, case.run_id, analysis)
    assert db_session.get(DiagnosisReport, report_id) is not None
    assert fetch_diagnosis_payload(db_session, case.run_id)["diagnosis"] == "完整已核对结果"
    assert _report_for(db_session, case.run_id).report_id == report_id
    with pytest.raises(ValueError, match="不一致"):
        save_diagnosis_result(db_session, case.run_id, analysis.model_copy(update={"diagnosis": "不同结果"}))


def _report_for(session, run_id: str) -> DiagnosisReport | None:
    return session.scalars(
        select(DiagnosisReport)
        .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
        .where(Execution.session_run_id == run_id)
    ).one_or_none()


def test_save_failure_rolls_back_report_and_organization(db_session):
    case = OrganizationCase(db_session, chapters=1)
    db_session.commit()
    draft = identity_draft(db_session, case)
    draft.review_events(list(draft.events), reason="核对")
    draft.register_arc(
        key="identity",
        kind="main",
        title="身份",
        objective="找回身份",
        role="主线",
        reason="原文依据",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    _freeze_structure(draft)
    analysis = AgentAnalysis(narrative_organization=draft.finish(), diagnosis="依据原文核对")

    def save_then_fail(session, current_run, organization, report_id):
        save_organization(session, current_run, organization, report_id)
        assert session.scalars(select(NarrativeGroup)).all()
        raise ValueError("保存失败")

    with patch("src.agents.diagnosis.persistence.save_organization", side_effect=save_then_fail):
        with pytest.raises(ValueError, match="保存失败"):
            save_diagnosis_result(db_session, case.run_id, analysis)
    assert _report_for(db_session, case.run_id) is None
    from src.event_trees.storage_map import run_events

    assert run_events(db_session, case.run_id) == {}


def test_old_chapter_contract_cannot_be_promoted_by_diagnosis(db_session, organization_case):
    _case, event_ids, draft = organization_case
    draft.review_events(event_ids, reason="已核对")
    _freeze_structure(draft)
    stale_run_id = draft.run_id
    add_annotation_source(db_session, stale_run_id, 1, role="metric", contract_version="old")
    db_session.flush()
    with pytest.raises(ValueError, match="旧契约.*重建"):
        draft.finish()


def test_tools_expose_complete_events_and_remove_unique_primary_api(organization_case):
    _case, event_ids, draft = organization_case
    tools = {item.name: item for item in build_diagnosis_tools(draft.session, draft.run_id, organization_draft=draft)}
    assert {
        "write_diagnosis",
        "write_event",
        "write_arc",
        "write_outcome",
        "write_conflict",
        "read_metrics",
        "read_topics",
    } <= set(tools)
    assert not {"assign_book_events", "reference_book_event", "event", "submit_diagnosis"} & set(tools)
    assert '"written"' in tools["write_event"].invoke(
        {
            "items": [
                {
                    "operation": "review",
                    "event_ids": event_ids,
                    "reason": "已核对",
                }
            ]
        }
    )
    assert draft.search_events(unreviewed_only=True)["total"] == 0
