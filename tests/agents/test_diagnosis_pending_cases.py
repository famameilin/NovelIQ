"""诊断失败登记与正式交付分别保存，不用候选记录冒充正式产物

案例状态是支持条目 adopted 的读投影（CasePool.case_runtime）；未发布事件观察进
case_entries 候选观察行；正式交付绑定真实诊断报告，不伪造子报告。
"""

import asyncio
import json
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.agents.diagnosis.domain import DiagnosisDomain
from src.agents.diagnosis.runner import _run_diagnosis_agent
from src.agents.diagnosis.work_runtime import DiagnosisWorkScheduler
from src.audit.recorder import AgentAuditRecorder
from src.case_pool import CasePool
from src.case_pool.contributions import CaseContribution
from src.event_trees.storage_map import run_annotation_event_ids, run_events
from src.storage import new_id
from src.storage.models import Agent, Case, DiagnosisReport
from tests.agents.test_complete_event_invariants import draft_case as draft_case
from tests.support.storage_fixtures import fixture_id, storage_factory, storage_for


def domain_for(draft, *, agent_id: str | None = None):
    return DiagnosisDomain(
        session=storage_for(draft.fixture_session),
        run_id=draft.run_id,
        novel_id=fixture_id(__name__, "test-novel"),
        agent_id=agent_id or new_id(),
        novel_title=None,
        model_id="test-model",
    )


def real_author(session, run_id: str) -> str:
    """真实诊断执行身份（报告角色 invocation）：案例支持条目引用正式执行，不伪造执行外键"""
    agent_id = new_id()
    session.add(Agent(id=agent_id, run_id=run_id, type="report", status="running"))
    session.commit()
    return agent_id


def _reports(session, run_id: str) -> list[DiagnosisReport]:
    return list(
        session.scalars(
            select(DiagnosisReport).join(Agent, Agent.id == DiagnosisReport.agent_id).where(Agent.run_id == run_id)
        )
    )


@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_or_cancelled_run_retains_registration_without_candidate_delivery(
    draft_case, configured_model_pool, cancelled
):
    draft = draft_case
    domain = domain_for(draft)
    author = real_author(draft.fixture_session, draft.run_id)
    domain.case_pool.begin(author)
    case = domain.case_pool.push("relation", "核对寻路与照明的关联", author)
    domain.case_pool.claim(case["case_id"], author)
    error = asyncio.CancelledError("用户取消") if cancelled else RuntimeError("预算耗尽")

    async def fail(_scheduler):
        raise error

    recorder = AgentAuditRecorder(storage_factory(sessionmaker(bind=draft.fixture_session.get_bind())))
    with patch.object(DiagnosisWorkScheduler, "run", fail), pytest.raises(type(error), match=str(error)):
        await _run_diagnosis_agent(
            session=storage_for(draft.fixture_session),
            run_id=draft.run_id,
            novel_id=fixture_id(__name__, "test-novel"),
            agent_id=domain.agent_id,
            domain=domain,
            audit_recorder=recorder,
        )
    draft.fixture_session.expire_all()
    pool = CasePool(draft.run_id)
    pool.load_storage(storage_for(draft.fixture_session))
    # 承诺随会话保存落库：本会话未保存时，续跑重建后按未解决（未承诺）重办
    assert pool.case_runtime[case["case_id"]]["submitted"] is False
    row = draft.fixture_session.get(Case, case["case_id"])
    assert row.producer_agent_id == author and row.status == "pending"
    assert not hasattr(pool, "deliveries")
    assert author not in domain.case_pool.saved
    assert len(run_events(storage_for(draft.fixture_session), draft.run_id)) == 2
    assert _reports(draft.fixture_session, draft.run_id) == []
    assert len(run_annotation_event_ids(storage_for(draft.fixture_session), draft.run_id)) == 2


@pytest.mark.parametrize("cancelled", [False, True])
async def test_retention_failure_reports_both_errors(draft_case, configured_model_pool, cancelled):
    domain = domain_for(draft_case)
    original = asyncio.CancelledError("原始取消") if cancelled else RuntimeError("原始诊断失败")

    async def fail(_scheduler):
        raise original

    recorder = AgentAuditRecorder(storage_factory(sessionmaker(bind=draft_case.fixture_session.get_bind())))
    with (
        patch.object(DiagnosisWorkScheduler, "run", fail),
        patch.object(domain, "retain_pending_cases", side_effect=ConnectionError("案例存储断开")),
        pytest.raises(BaseExceptionGroup) as raised,
    ):
        await _run_diagnosis_agent(
            session=storage_for(draft_case.fixture_session),
            run_id=draft_case.run_id,
            novel_id=fixture_id(__name__, "test-novel"),
            agent_id=domain.agent_id,
            domain=domain,
            audit_recorder=recorder,
        )
    assert raised.value.exceptions[0] is original
    assert str(raised.value.exceptions[1]) == "案例存储断开"


def test_pending_registration_transaction_rolls_back_all_cases_on_storage_failure(draft_case):
    domain = domain_for(draft_case)
    authors = [real_author(draft_case.fixture_session, draft_case.run_id) for _ in range(2)]
    for index, author in enumerate(authors):
        domain.case_pool.begin(author)
        domain.case_pool.push("event", f"核查第{index}个节点", author)
    from src.storage.repositories.case_writes import CaseWritesRepository

    save = CaseWritesRepository.save_work
    attempts = 0

    def interrupted(repository, session, contribution):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise ConnectionError("第二份案例存储失败")
        return save(repository, session, contribution)

    with patch.object(CaseWritesRepository, "save_work", interrupted), pytest.raises(ConnectionError):
        domain.retain_pending_cases(RuntimeError("原始诊断失败"))
    assert attempts == 2
    # retain 的短事务整体回滚：登记行与支持条目都不残留，只保留真实执行身份
    draft_case.fixture_session.expire_all()
    assert not list(
        draft_case.fixture_session.scalars(select(Case).where(Case.description.in_(["核查第0个节点", "核查第1个节点"])))
    )


def test_formal_output_adopts_real_child_delivery_without_fabricated_child_report(db_session):
    from tests.support.chapter_annotation_helpers import create_run_with_chunks
    from tests.support.event_tree_fixtures import (
        add_annotation_source,
        add_declaration,
        add_diagnosis_context,
        close_structure,
        first_paragraph,
        identity_every_declaration,
        publish_draft,
    )

    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜找回了身份。"])
    session_id, agent_id = add_diagnosis_context(db_session, run_id)
    record_id, _source_execution = add_annotation_source(db_session, run_id, 1, role="event")
    paragraph = first_paragraph(db_session, run_id)
    add_declaration(
        db_session,
        record_id=record_id,
        paragraph=paragraph,
        phrase="找回了身份",
        title="身份问题",
        problem="能否确认身份",
        summary="顾霜找回身份",
        event_type="身份确认",
    )
    db_session.commit()
    draft, _meta = identity_every_declaration(db_session, run_id, context=(session_id, agent_id))
    close_structure(db_session, draft, evidence_paragraph_id=int(paragraph.paragraph_id))
    publish_draft(db_session, run_id, draft)
    db_session.commit()
    report_id = _reports(db_session, run_id)[0].report_id
    domain = DiagnosisDomain(
        session=storage_for(db_session),
        run_id=run_id,
        novel_id=fixture_id(__name__, "test-novel"),
        agent_id=session_id,
        novel_title=None,
        model_id="test-model",
    )

    author = real_author(db_session, run_id)
    pool = CasePool(run_id)
    domain.case_pool = pool
    pool.begin(author)
    case = pool.push("relation", "检查寻路与照明", author)
    pool.claim(case["case_id"], author)
    pool.submit(case["case_id"], author)
    frozen = CaseContribution(
        run_id,
        author,
        json.dumps(
            {
                "created_case_ids": [case["case_id"]],
                "registrations": {case["case_id"]: case},
                "submissions": pool.submissions_for(author),
            },
            ensure_ascii=False,
        ),
    )
    assert pool.save_work(storage_for(db_session), frozen, adopted_output_id=report_id) == []
    db_session.commit()
    domain.retain_pending_cases(RuntimeError("提交后的内存确认失败"))
    db_session.expire_all()
    row = db_session.get(Case, case["case_id"])
    assert row.status == "resolved" and row.promised_agent_id == author
    loaded = CasePool(run_id)
    loaded.load_storage(storage_for(db_session))
    assert loaded.case_runtime[case["case_id"]]["submitted"] is True
    # 只有真实诊断报告被采纳，不伪造子报告
    reports = _reports(db_session, run_id)
    assert [row.report_id for row in reports] == [report_id]
    assert db_session.get(DiagnosisReport, report_id).agent_id == session_id
