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
from src.event_trees.organization import EventOrganizationDraft, validate_organization
from src.event_trees.organization_models import NarrativeOrganization, OrganizationEvidence
from src.event_trees.read.organization import EventTreeQuery
from src.storage.ids import new_id
from src.storage.models import (
    Agent,
    CompleteEvent,
    DiagnosisReport,
    NarrativeGroup,
    NarrativeLink,
)
from src.storage.repositories.diagnosis_event_writes import save_diagnosis_events
from src.storage.repositories.organization_writes import save_organization
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import (
    add_annotation_source,
    add_declaration,
    add_diagnosis_context,
    first_paragraph,
    report_case_anchor,
    select_event_lines,
)
from tests.support.storage_fixtures import storage_for

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
            phrase = TEXTS[(chapter_id - 1) % len(TEXTS)][:3]
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


def tree_of(draft, event_id: str) -> str:
    return next(item.tree_id for item in draft.queues.values() if event_id in item.event_ids)


@pytest.fixture
def organization_case(db_session):
    case = OrganizationCase(db_session, chapters=6)
    db_session.commit()
    draft = identity_draft(db_session, case)
    event_ids = list(draft.events)
    draft.reference(
        parent_tree_id=tree_of(draft, event_ids[0]),
        child_tree_id=tree_of(draft, event_ids[2]),
        reason="确认身份中的子问题",
        evidence=[OrganizationEvidence(paragraph_id=0, quote="找回了身份")],
    )
    select_event_lines(draft, event_ids[1:])
    return case, event_ids, draft


def _organized(draft, event_ids):
    draft.register_outcome(
        key="recognized",
        title="身份获确认",
        description="两人的行动使身份得到确认",
        evidence=[OrganizationEvidence(paragraph_id=0, quote="证实身份")],
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
    from src.storage.repositories.queue_writes import save_event_line_flags

    save_event_line_flags(session, run_id, organization.event_line_ids, organization.event_line_names)
    session.commit()
    return report_id


def test_multiple_parents_are_preserved_and_cycle_is_rejected(organization_case):
    _case, event_ids, draft = organization_case
    draft.reference(
        parent_tree_id=tree_of(draft, event_ids[1]),
        child_tree_id=tree_of(draft, event_ids[2]),
        reason="第二个真实父级",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    assert draft.queue_graph().event_parents(event_ids[2]) == event_ids[:2]
    with pytest.raises(ValueError, match="成环"):
        draft.reference(
            parent_tree_id=tree_of(draft, event_ids[2]),
            child_tree_id=tree_of(draft, event_ids[0]),
            reason="非法闭环",
            evidence=[OrganizationEvidence(paragraph_id=0)],
        )


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


def test_other_producer_cannot_reference_unpublished_candidates(db_session):
    case = OrganizationCase(db_session)
    db_session.commit()
    draft = _fresh_draft(db_session, case)
    rows = list(draft._all_events().values())
    _submit_identity(draft, rows[0], "k1")
    parent = next(iter(draft.events))
    parent_tree = draft.queue(
        event_ids=[parent], reason="完整队列", evidence=[OrganizationEvidence(paragraph_id=0)]
    )
    child_tree = draft.queue_graph().event_tree[rows[1]["event_id"]]
    draft.producer_agent_id = _second_producer(db_session, case.run_id)
    with pytest.raises(ValueError, match="已读取"):
        draft.reference(
            parent_tree_id=parent_tree,
            child_tree_id=child_tree,
            reason="不可借用未保存候选",
            evidence=[OrganizationEvidence(paragraph_id=0)],
        )
    assert not draft.queue_references
    assert db_session.get(CompleteEvent, parent) is None


def test_retract_blocked_when_other_execution_references_event(db_session):
    case = OrganizationCase(db_session)
    db_session.commit()
    draft = _fresh_draft(db_session, case)
    rows = list(draft._all_events().values())
    _submit_identity(draft, rows[0], "k1")
    minted = next(iter(draft.events))
    other = _second_producer(db_session, case.run_id)
    draft.producer_agent_id = other
    draft.register_outcome(
        key="identity",
        title="身份确认",
        description="身份最终得到证实",
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
    outcomes = [
        row
        for row in db_session.scalars(select(NarrativeGroup))
        if row.kind == "outcome" and row.producer_agent_id == draft.producer_agent_id
    ]
    assert len(outcomes) == 1
    assert "outcome_group_id" not in NarrativeLink.__table__.c
    assert {"tree_id", "member_event_id", "parent_tree_id", "child_tree_id"} <= set(NarrativeLink.__table__.c.keys())
    assert db_session.get(CompleteEvent, event_ids[0]).event_id == event_ids[0]
    from src.event_trees.organization_queries import _run_event_dicts

    db_session.expire_all()
    projected = _run_event_dicts(storage_for(db_session), case.run_id)[event_ids[0]]
    assert projected["summary"] == draft.events[event_ids[0]].summary
    assert projected["event_type"] == draft.events[event_ids[0]].event_type
    assert "current_revision_id" not in projected
    assert "event_outcome_links" not in organization.model_dump()
    assert "memberships" not in organization.model_dump()
    assert "outcome_arc_links" not in organization.model_dump()
    assert not {"arcs", "event_arc_links"} & organization.model_dump().keys()
    report = db_session.get(DiagnosisReport, report_id)
    assert report is not None and report.agent_id == case.session_id


def test_events_can_be_saved_without_extra_review_records(organization_case):
    _case, event_ids, draft = organization_case
    assert draft.search_events(limit=1)["total"] == len(event_ids)
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
    payload["outcomes"][0]["evidence"][0]["text_hash"] = "invented"
    with pytest.raises(ValueError, match="哈希"):
        validate_organization(storage_for(db_session), case.run_id, NarrativeOrganization.model_validate(payload))


def test_outcome_has_independent_identity_and_own_text_evidence(organization_case):
    _case, event_ids, draft = organization_case
    args = {
        "key": "identity",
        "title": "身份确认",
        "description": "身份最终得到证实",
        "evidence": [OrganizationEvidence(paragraph_id=0)],
    }
    outcome = draft.register_outcome(**args)
    assert outcome == draft.register_outcome(**args)
    result = draft.finish()
    assert result.outcomes[0].outcome_id == outcome
    assert "event_outcome_links" not in result.model_dump()
    with pytest.raises(ValidationError):
        draft.register_outcome(**{**args, "evidence": [OrganizationEvidence(paragraph_id=0, event_id=event_ids[0])]})


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
    case = OrganizationCase(db_session, chapters=5)
    db_session.commit()
    draft = identity_draft(db_session, case)
    select_event_lines(draft, case.declarations)
    draft.register_outcome(
        key="identity",
        title="身份",
        description="找回身份",
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
        "write_outcome",
        "read_metrics",
        "read_topics",
    } <= set(tools)
    assert not {"write_arc", "assign_book_events", "reference_book_event", "event", "submit_diagnosis"} & set(tools)
    schema = tools["write_event"].args_schema.model_json_schema()
    assert "operation" not in schema["$defs"]["EventItem"]["properties"]
    assert {"write_link", "retract_structure"} <= set(tools)
    for operation in ("review", "structure_review"):
        with pytest.raises(ValidationError):
            tools["write_event"].invoke({"items": [{"operation": operation, "event_ids": event_ids}]})


def test_declaration_rows_reads_evidence_in_one_batch(db_session, monkeypatch):
    case = OrganizationCase(db_session, chapters=6)
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


def test_event_line_names_require_full_coverage_and_valid_shape(organization_case):
    _case, _event_ids, draft = organization_case
    selected = sorted(draft.event_line_ids)
    with pytest.raises(ValueError, match="缺少"):
        draft.name_event_lines({})
    complete = dict.fromkeys(selected, "")
    with pytest.raises(ValueError, match="1–5"):
        draft.name_event_lines(complete)
    with pytest.raises(ValueError, match="不得重复"):
        draft.name_event_lines(dict.fromkeys(selected, "身份线"))
    named = {tree_id: f"事件{index}线" for index, tree_id in enumerate(selected, 1)}
    with pytest.raises(ValueError, match="多出"):
        draft.name_event_lines({**named, "extra": "多余线"})
    draft.line_names.clear()
    with pytest.raises(ValueError, match="尚未命名"):
        draft.finish()


def test_saved_event_line_names_follow_the_selected_lines(organization_case, db_session):
    case, event_ids, draft = organization_case
    organization = _organized(draft, event_ids)
    _save_report(db_session, case.run_id, organization)
    db_session.expire_all()
    executions = smap.run_execution_ids(storage_for(db_session), case.run_id)
    rows = {
        row.group_id: row.line_name
        for row in db_session.scalars(
            select(NarrativeGroup).where(NarrativeGroup.producer_agent_id.in_(executions))
        )
    }
    assert {tree_id: name for tree_id, name in rows.items() if name is not None} == organization.event_line_names
    payload = EventTreeQuery(storage_for(db_session), case.run_id).fetch()
    projected = {queue["tree_id"]: queue["line_name"] for queue in payload["queues"] if queue["line_name"]}
    assert projected == organization.event_line_names
