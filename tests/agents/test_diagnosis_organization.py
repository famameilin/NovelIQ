"""诊断完整事件组织的真实原文、多对多关系与保存事务验证

夹具自足：直接建立真实来源链（标注 work/执行/记录 + 章级声明 + 诊断会话/work/执行），
发布走正式入口（diagnosis_reports → event_records/event_revisions → event_links）。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from src.agents.diagnosis.persistence import save_diagnosis_result
from src.agents.diagnosis.tools import build_diagnosis_tools
from src.diagnosis.schema import AgentAnalysis
from src.event_trees import storage_map as smap
from src.event_trees.organization import (
    EventOrganizationDraft,
    NarrativeOrganization,
    OrganizationEvidence,
    validate_organization,
)
from src.storage.ids import new_id
from src.storage.models import (
    Agent,
    CompleteEvent,
    DiagnosisReport,
    NarrativeGroup,
    NarrativeLink,
)
from src.storage.repositories.diagnosis_event_writes import save_case_session_rows, save_diagnosis_events
from src.storage.repositories.organization_writes import save_organization
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import (
    add_annotation_source,
    add_declaration,
    add_diagnosis_context,
    first_paragraph,
    report_case_anchor,
)
from tests.support.storage_fixtures import storage_for

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
        self.session_id, self.agent_id = add_diagnosis_context(session, self.run_id)
        self.declarations: list[str] = []
        for chapter_id in range(1, chapters + 1):
            record_id, _agent_id = add_annotation_source(session, self.run_id, chapter_id, role="event")
            phrase = PHRASES[(chapter_id - 1) % len(PHRASES)]
            event_id = add_declaration(
                session,
                record_id=record_id,
                paragraph=first_paragraph(session, self.run_id, chapter_id=chapter_id),
                phrase=phrase,
                title=f"身份问题{len(self.declarations)}",
                problem="能否确认身份",
                summary=f"章节概要{len(self.declarations)}",
                event_type="身份确认",
            )
            self.declarations.append(event_id)
        session.flush()


def identity_draft(session, case: OrganizationCase) -> EventOrganizationDraft:
    from src.event_trees.diagnosis_persistence import hydrate_draft_from_run

    draft = EventOrganizationDraft(storage_for(session), case.run_id, case.session_id)
    draft.fixture_session = session
    draft.producer_agent_id = case.agent_id
    hydrate_draft_from_run(storage_for(session), case.run_id, draft)
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
    return draft.finish()


def _save_report(session, run_id, organization):
    """与正式保存同序：先报告与完整事件，再叙事组织"""
    from tests.support.storage_fixtures import insert_report_fixture

    report_id = insert_report_fixture(
        session, run_id, organization.source_agent_id, AgentAnalysis(narrative_organization=organization)
    )
    save_diagnosis_events(session, run_id, organization, report_id)
    save_organization(session, run_id, organization, report_id)
    session.commit()
    return report_id


def test_containment_second_parent_rejected_at_submission(organization_case):
    _case, event_ids, draft = organization_case
    # 工具面先到先得：子事件已有直接父时拒收第二个父包含
    with pytest.raises(ValueError, match="直接父"):
        draft.contain(
            parent_event_id=event_ids[1],
            child_event_id=event_ids[2],
            reason="另一个父候选",
            evidence=[OrganizationEvidence(paragraph_id=0)],
        )
    assert len(draft.containments) == 1


def _fresh_draft(session, case: OrganizationCase) -> EventOrganizationDraft:
    draft = EventOrganizationDraft(storage_for(session), case.run_id, case.session_id)
    draft.fixture_session = session
    draft.case_id = report_case_anchor(case.run_id)
    draft.producer_agent_id = case.agent_id
    return draft


def _submit_identity(draft, row, key: str) -> None:
    draft.event(
        key=key,
        title=row["title"],
        problem=row["problem"],
        summary=row["summary"],
        event_type=row["event_type"],
        status=row["status"],
        progress=row["progress"],
        from_chapter_id=row["from"],
        to_chapter_id=row["to"],
        reason="本例按原文明确判断每项声明为一个事件身份",
        evidence=[OrganizationEvidence(paragraph_id=row["evidence"][0]["paragraph_id"])],
    )


def test_identity_key_reuse_for_another_event_is_rejected(db_session):
    case = OrganizationCase(db_session)
    db_session.commit()
    draft = _fresh_draft(db_session, case)
    rows = list(draft._all_events().values())
    # 同一执行内局部键唯一：换声明复用同键拒收，同声明重发放行
    _submit_identity(draft, rows[0], "k1")
    with pytest.raises(ValueError, match="覆盖"):
        _submit_identity(draft, rows[1], "k1")
    _submit_identity(draft, rows[0], "k1")
    assert len(draft.events) == 1


def test_event_cannot_be_retracted_or_key_freed(db_session):
    case = OrganizationCase(db_session)
    draft = _fresh_draft(db_session, case)
    row = next(iter(draft._all_events().values()))
    _submit_identity(draft, row, "k1")
    event_id = next(iter(draft.events))
    with pytest.raises(ValueError):
        draft.retract(
            kind="identity", identifier=event_id, reason="禁止撤销事件", evidence=[OrganizationEvidence(paragraph_id=0)]
        )
    assert event_id in draft.events


def _second_producer(session, run_id: str) -> str:
    "同轮另一个诊断执行身份，作为关系行的真实生产者"
    producer = new_id()
    session.add(Agent(id=producer, run_id=run_id, type="case", status="running"))
    session.flush()
    return producer


def test_cross_session_references_persist_unstored_candidates(db_session):
    "其他会话引用未落库候选时，保存把候选一并落库且署名真实生产者"
    case = OrganizationCase(db_session)
    db_session.commit()
    draft = _fresh_draft(db_session, case)
    rows = list(draft._all_events().values())
    _submit_identity(draft, rows[0], "k1")
    _submit_identity(draft, rows[1], "k2")
    parent_id, child_id = sorted(draft.events)
    other = _second_producer(db_session, case.run_id)
    draft.producer_agent_id = other
    draft.contain(
        parent_event_id=parent_id,
        child_event_id=child_id,
        reason="其他执行判断的包含",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    save_case_session_rows(db_session, case.run_id, other, draft)
    db_session.commit()

    db_session.expire_all()
    for event_id in (parent_id, child_id):
        saved = db_session.get(CompleteEvent, event_id)
        assert saved is not None and saved.producer_agent_id == case.agent_id
    assert len(list(db_session.scalars(select(NarrativeLink).where(NarrativeLink.contained_child_id == child_id)))) == 1
    links = list(db_session.scalars(select(NarrativeLink).where(NarrativeLink.contained_child_id == child_id)))
    assert {row.producer_agent_id for row in links} == {other}

    save_case_session_rows(db_session, case.run_id, other, draft)
    save_case_session_rows(db_session, case.run_id, case.agent_id, draft)
    db_session.commit()
    assert (
        len(list(db_session.scalars(select(CompleteEvent).where(CompleteEvent.event_id.in_([parent_id, child_id])))))
        == 2
    )
    assert (
        len(
            list(
                db_session.scalars(
                    select(NarrativeLink).where(NarrativeLink.contained_child_id == child_id)
                )
            )
        )
        == 1
    )


def test_retract_blocked_when_other_execution_references_event(db_session):
    case = OrganizationCase(db_session)
    db_session.commit()
    draft = _fresh_draft(db_session, case)
    rows = list(draft._all_events().values())
    _submit_identity(draft, rows[0], "k1")
    minted = next(iter(draft.events))
    other = _second_producer(db_session, case.run_id)
    draft.producer_agent_id = other
    arc_id = _arc(draft)
    draft.link_event_arc(
        event_id=minted, arc_id=arc_id, role="推动", reason="复用其他执行的事件",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    draft.producer_agent_id = case.agent_id
    with pytest.raises(ValueError, match="只允许撤回"):
        draft.retract(
            kind="identity",
            identifier=minted,
            reason="本例验证被他人引用时不能撤回",
            evidence=[OrganizationEvidence(paragraph_id=rows[0]["evidence"][0]["paragraph_id"])],
        )
    assert minted in draft.events


def test_event_reference_remains_when_event_retraction_is_rejected(db_session):
    case = OrganizationCase(db_session)
    draft = _fresh_draft(db_session, case)
    row = next(iter(draft._all_events().values()))
    _submit_identity(draft, row, "k1")
    event_id = next(iter(draft.events))
    with pytest.raises(ValueError):
        draft.retract(
            kind="identity", identifier=event_id, reason="禁止撤销事件", evidence=[OrganizationEvidence(paragraph_id=0)]
        )
    assert event_id in draft.events


def test_complete_event_body_and_declaration_bindings_are_saved_independently(db_session, organization_case):
    case, event_ids, draft = organization_case
    organization = _organized(draft, event_ids)
    report_id = _save_report(db_session, case.run_id, organization)
    arc_links = [
        row
        for row in db_session.scalars(select(NarrativeLink))
        if row.arc_group_id is not None and row.member_event_id in event_ids
    ]
    assert len(arc_links) == 2
    outcomes = [
        row
        for row in db_session.scalars(select(NarrativeGroup))
        if row.outcome_description is not None and row.producer_agent_id == draft.producer_agent_id
    ]
    assert len(outcomes) == 1
    outcome_links = [
        row
        for row in db_session.scalars(select(NarrativeLink))
        if row.outcome_group_id is not None and row.member_event_id in event_ids
    ]
    assert len(outcome_links) == 2
    assert db_session.get(CompleteEvent, event_ids[0]).event_id == event_ids[0]
    from src.event_trees.organization import _run_event_dicts

    db_session.expire_all()
    projected = _run_event_dicts(storage_for(db_session), case.run_id)[event_ids[0]]
    assert projected["summary"] == draft.events[event_ids[0]].summary
    assert projected["event_type"] == draft.events[event_ids[0]].event_type
    assert "current_revision_id" not in projected
    assert organization.event_arc_links[0].evidence != organization.outcomes[0].evidence
    assert "memberships" not in organization.model_dump()
    assert "outcome_arc_links" not in organization.model_dump()
    report = db_session.get(DiagnosisReport, report_id)
    assert report is not None and report.agent_id == case.session_id


def test_events_can_be_saved_without_extra_review_records(organization_case):
    _case, event_ids, draft = organization_case
    assert draft.search_events(limit=1)["total"] == 3
    organization = draft.finish()
    assert len(organization.events) == len(event_ids)
    assert not {"reviewed_events", "structure_reviews"} & organization.model_dump().keys()


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
        validate_organization(storage_for(db_session), case.run_id, NarrativeOrganization.model_validate(payload))


def test_outcome_has_independent_identity_and_requires_each_relation(organization_case):
    _case, event_ids, draft = organization_case
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
        EventOrganizationDraft(storage_for(db_session), other.run_id).read_events([event_ids[0]])


def test_saved_annotation_events_are_directly_readable(organization_case):
    case, _, draft = organization_case
    assert draft.read_events([case.declarations[0]])[0]["event_id"] == case.declarations[0]


def _finalized_submission(session, case, draft, event_ids, *, diagnosis):
    """与正式报告保存同口径绑定运行时字段后提交，重投核验按正式合同字段比较"""
    from src.diagnosis.queries import DiagnosisQueries

    bindings = {event_id: event.event_id for event in draft.events.values() for event_id in event.source_event_ids}
    organization = _organized(draft, event_ids)
    return AgentAnalysis(
        novel_id=case.novel_id,
        foreshadow_expectation=DiagnosisQueries(storage_for(session)).calculate_foreshadow_expectation(
            case.run_id, declaration_bindings=bindings
        ),
        narrative_organization=organization,
        diagnosis=diagnosis,
    )


def _report_for(session, run_id: str) -> DiagnosisReport | None:
    return session.scalars(
        select(DiagnosisReport).join(Agent, Agent.id == DiagnosisReport.agent_id).where(Agent.run_id == run_id)
    ).one_or_none()


def test_save_failure_rolls_back_report_and_organization(db_session):
    case = OrganizationCase(db_session, chapters=1)
    db_session.commit()
    draft = identity_draft(db_session, case)
    draft.register_arc(
        key="identity",
        kind="main",
        title="身份",
        objective="找回身份",
        role="主线",
        reason="原文依据",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    analysis = AgentAnalysis(narrative_organization=draft.finish(), diagnosis="依据原文核对")

    def save_then_fail(session, current_run, organization, report_id):
        save_organization(session, current_run, organization, report_id)
        assert session.scalars(select(NarrativeGroup)).all()
        raise ValueError("保存失败")

    with patch("src.storage.repositories.diagnosis_publish.save_organization", side_effect=save_then_fail):
        with pytest.raises(ValueError, match="保存失败"):
            save_diagnosis_result(storage_for(db_session), case.run_id, analysis)
    assert _report_for(db_session, case.run_id) is None
    from src.event_trees.storage_map import run_events

    assert set(run_events(storage_for(db_session), case.run_id)) == set(case.declarations)


def test_diagnosis_uses_sources_without_contract_marker(db_session, organization_case):
    _case, event_ids, draft = organization_case
    db_session.flush()
    assert len(draft.finish().events) == len(event_ids)


def test_tools_expose_complete_events_and_remove_unique_primary_api(organization_case):
    _case, event_ids, draft = organization_case
    # 报告面与案例面按角色分别装配，两个面合起来覆盖全部写入与读取入口
    tools = {
        item.name: item
        for item in build_diagnosis_tools(
            storage_for(draft.fixture_session), draft.run_id, role="report", organization_draft=draft
        )
    }
    tools.update(
        {
            item.name: item
            for item in build_diagnosis_tools(
                storage_for(draft.fixture_session), draft.run_id, organization_draft=draft
            )
        }
    )
    assert {
        "write_diagnosis",
        "write_event",
        "write_arc",
        "write_outcome",
        "read_metrics",
        "read_topics",
    } <= set(tools)
    assert not {"assign_book_events", "reference_book_event", "event", "submit_diagnosis"} & set(tools)
    schema = tools["write_event"].args_schema.model_json_schema()
    operations = schema["properties"]["items"]["items"]["discriminator"]["mapping"]
    assert set(operations) == {"event", "contain", "relation", "retract"}
    for operation in ("review", "structure_review"):
        with pytest.raises(ValidationError):
            tools["write_event"].invoke({"items": [{"operation": operation, "event_ids": event_ids}]})


def test_declaration_rows_reads_evidence_in_one_batch(db_session, monkeypatch):
    case = OrganizationCase(db_session, chapters=3)
    db_session.commit()
    draft = EventOrganizationDraft(storage_for(db_session), case.run_id, case.agent_id)
    calls: list[int] = []
    original = smap.evidence_payload_groups

    def counting(session, run_id, groups):
        calls.append(len(groups))
        return original(session, run_id, groups)

    monkeypatch.setattr(smap, "evidence_payload_groups", counting)
    first = draft._all_events()
    second = draft._all_events()
    assert first == second
    assert calls == [len(case.declarations), len(case.declarations)]
