"""诊断失败登记与正式交付分别保存，不用候选记录冒充正式产物（2026-10-16 全库 3NF 改造）

案例状态是支持条目 adopted 的读投影（CasePool.case_runtime）；未发布事件观察进
case_entries 候选观察行；正式交付绑定真实诊断报告，不伪造子报告。
"""

import asyncio
import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.agents.diagnosis.domain import DiagnosisDomain
from src.agents.diagnosis.runner import _run_diagnosis_agent
from src.agents.diagnosis.work_runtime import DiagnosisWorkCorrections, DiagnosisWorkScheduler
from src.audit.recorder import AgentAuditRecorder
from src.case_pool import CasePool
from src.case_pool.contributions import CaseContribution
from src.event_trees.organization import (
    CandidateConflict,
    register_diagnosis_execution,
    register_diagnosis_work,
)
from src.event_trees.storage_map import run_declaration_ids, run_events
from src.storage.models import BookCase, CaseEntry, DiagnosisReport, Execution
from tests.agents.test_complete_event_invariants import draft_case as draft_case
from tests.agents.test_complete_event_invariants import event


def domain_for(draft, *, execution_id: str | None = None):
    return DiagnosisDomain(
        session=draft.session,
        run_id=draft.run_id,
        novel_id="test-novel",
        execution_id=execution_id or f"pending-cases-{uuid4().hex[:8]}",
        novel_title=None,
        model_id="test-model",
    )


def real_author(session, session_id: str) -> tuple[str, str]:
    """真实诊断执行身份：案例支持条目引用正式 invocation，不伪造执行外键"""
    work_id, execution_id = f"pending-work-{uuid4().hex[:8]}", uuid4().hex
    register_diagnosis_work(session, session_id=session_id, work_id=work_id, role="event")
    register_diagnosis_execution(session, work_id=work_id, execution_id=execution_id, attempt_number=1)
    session.commit()
    return work_id, execution_id


def _reports(session, run_id: str) -> list[DiagnosisReport]:
    return list(
        session.scalars(
            select(DiagnosisReport)
            .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
            .where(Execution.session_run_id == run_id)
        )
    )


@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_or_cancelled_run_retains_registration_without_candidate_delivery(
    draft_case, configured_model_pool, cancelled
):
    draft = draft_case
    domain = domain_for(draft)
    author = real_author(draft.session, domain.execution_id)
    domain.case_pool.begin(*author)
    case = domain.case_pool.push("relation", "核对寻路与照明的关联", author)
    domain.case_pool.promise(case["case_id"], author)
    domain.case_pool.associate(
        case["case_id"],
        author,
        tool_name="write_event",
        call_id="candidate-operation",
        receipt={"candidate": True},
        is_write=True,
    )
    error = asyncio.CancelledError("用户取消") if cancelled else RuntimeError("预算耗尽")

    async def fail(_scheduler):
        raise error

    recorder = AgentAuditRecorder(sessionmaker(bind=draft.session.get_bind()))
    with patch.object(DiagnosisWorkScheduler, "run", fail), pytest.raises(type(error), match=str(error)):
        await _run_diagnosis_agent(
            session=draft.session,
            run_id=draft.run_id,
            novel_id="test-novel",
            execution_id=domain.execution_id,
            domain=domain,
            audit_recorder=recorder,
        )
    draft.session.expire_all()
    pool = CasePool(draft.run_id)
    pool.load_storage(draft.session)
    assert pool.case_runtime[case["case_id"]]["state"] == "pending"
    support = draft.session.scalars(
        select(CaseEntry).where(
            CaseEntry.case_id == case["case_id"],
            CaseEntry.producer_execution_id == author[1],
        )
    ).one()
    # 候选交付未被采用：支持条目 adopted=False，且没有交付子行
    assert support.adopted is False
    assert not list(
        draft.session.scalars(select(CaseEntry).where(CaseEntry.parent_entry_id == support.entry_id))
    )
    assert any(case["case_id"] in items for items in pool.registrations.values())
    assert not any(
        item["case_id"] == case["case_id"] for items in pool.deliveries.values() for item in items
    )
    assert author not in domain.case_pool.saved
    assert run_events(draft.session, draft.run_id) == {}
    assert _reports(draft.session, draft.run_id) == []
    assert len(run_declaration_ids(draft.session, draft.run_id)) == 2


def test_unresolved_conflict_keeps_full_node_name_and_source_in_pending_cases(draft_case):
    domain = domain_for(draft_case)
    domain.draft.work_id, domain.draft.producer_invocation_id = "conflict-work", "conflict-invocation"
    title = "寻路与照明" * 30
    identifier = event(domain.draft, title, [next(iter(domain.sources))])
    conflict = CandidateConflict("结构比较存在矛盾", ["conflict-work"])
    with pytest.raises(DiagnosisWorkCorrections) as raised:
        domain._correct("structure", conflict)
    domain.retain_pending_cases(raised.value)
    draft_case.session.expire_all()
    observation = draft_case.session.scalars(
        select(CaseEntry).where(CaseEntry.candidate_producer_execution_id == domain.execution_id)
    ).one()
    assert observation.pending_event_reference == identifier
    assert observation.pending_event_title == title
    rows = list(
        draft_case.session.scalars(
            select(BookCase).where(BookCase.pending_event_entry_id == observation.entry_id)
        )
    )
    assert len(rows) > 1
    assert all(
        len(row.description) <= 100
        and f"{identifier}|event|structure_conflict|段0|名" in row.description
        for row in rows
    )
    names = sorted(
        (int(row.description.rsplit("|名", 1)[1].split("/", 1)[0]), row.description.rsplit(":", 1)[1])
        for row in rows
    )
    assert "".join(value for _, value in names) == title
    pool = CasePool(draft_case.run_id)
    pool.load_storage(draft_case.session)
    assert all(pool.case_runtime[row.case_id]["state"] == "pending" for row in rows)
    assert identifier in domain.draft.events
    assert run_events(draft_case.session, draft_case.run_id) == {}


@pytest.mark.parametrize("cancelled", [False, True])
async def test_retention_failure_reports_both_errors(draft_case, configured_model_pool, cancelled):
    domain = domain_for(draft_case)
    original = asyncio.CancelledError("原始取消") if cancelled else RuntimeError("原始诊断失败")

    async def fail(_scheduler):
        raise original

    recorder = AgentAuditRecorder(sessionmaker(bind=draft_case.session.get_bind()))
    with (
        patch.object(DiagnosisWorkScheduler, "run", fail),
        patch.object(domain, "retain_pending_cases", side_effect=ConnectionError("案例存储断开")),
        pytest.raises(BaseExceptionGroup) as raised,
    ):
        await _run_diagnosis_agent(
            session=draft_case.session,
            run_id=draft_case.run_id,
            novel_id="test-novel",
            execution_id=domain.execution_id,
            domain=domain,
            audit_recorder=recorder,
        )
    assert raised.value.exceptions[0] is original
    assert str(raised.value.exceptions[1]) == "案例存储断开"


def test_pending_registration_transaction_rolls_back_all_cases_on_storage_failure(draft_case):
    domain = domain_for(draft_case)
    authors = [real_author(draft_case.session, domain.execution_id) for _ in range(2)]
    for index, author in enumerate(authors):
        domain.case_pool.begin(*author)
        domain.case_pool.push("event", f"核查第{index}个节点", author)
    save = domain.case_pool.save_work
    attempts = 0

    def interrupted(session, contribution):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise ConnectionError("第二份案例存储失败")
        return save(session, contribution)

    with patch.object(domain.case_pool, "save_work", interrupted), pytest.raises(ConnectionError):
        domain.retain_pending_cases(RuntimeError("原始诊断失败"))
    assert attempts == 2
    # retain 的短事务整体回滚：登记行与支持条目都不残留，只保留真实执行身份
    draft_case.session.expire_all()
    assert not list(
        draft_case.session.scalars(
            select(BookCase).where(
                BookCase.description.in_(["核查第0个节点", "核查第1个节点"])
            )
        )
    )
    assert not list(
        draft_case.session.scalars(
            select(CaseEntry).where(CaseEntry.producer_execution_id.in_([author[1] for author in authors]))
        )
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
    session_id, work_id, execution_id = add_diagnosis_context(db_session, run_id)
    record_id, _source_work, _source_execution = add_annotation_source(db_session, run_id, 1, role="event")
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
    draft, _meta = identity_every_declaration(
        db_session, run_id, context=(session_id, work_id, execution_id)
    )
    close_structure(db_session, draft, evidence_paragraph_id=int(paragraph.paragraph_id))
    publish_draft(db_session, run_id, draft)
    db_session.commit()
    report_id = _reports(db_session, run_id)[0].report_id
    domain = DiagnosisDomain(
        session=db_session,
        run_id=run_id,
        novel_id="test-novel",
        execution_id=session_id,
        novel_title=None,
        model_id="test-model",
    )

    author = real_author(db_session, session_id)
    pool = CasePool(run_id)
    domain.case_pool = pool
    pool.begin(*author)
    case = pool.push("relation", "检查寻路与照明", author)
    pool.promise(case["case_id"], author)
    pool.associate(
        case["case_id"],
        author,
        tool_name="write_arc",
        call_id="real-child-call",
        receipt={"status": "written"},
        is_write=True,
    )
    frozen = CaseContribution(
        run_id,
        *author,
        json.dumps(
            {
                "created_case_ids": [case["case_id"]],
                "registrations": {case["case_id"]: case},
                "deliveries": pool.deliveries[author],
            },
            ensure_ascii=False,
        ),
    )
    assert pool.save_work(db_session, frozen, adopted_output_id=report_id) == []
    db_session.commit()
    domain.retain_pending_cases(RuntimeError("提交后的内存确认失败"))
    db_session.expire_all()
    support = db_session.scalars(
        select(CaseEntry).where(
            CaseEntry.case_id == case["case_id"],
            CaseEntry.producer_execution_id == author[1],
        )
    ).one()
    delivery = db_session.scalars(
        select(CaseEntry).where(CaseEntry.parent_entry_id == support.entry_id)
    ).one()
    assert support.adopted is True
    assert delivery.business_call_id == "real-child-call" and delivery.tool_name == "write_arc"
    loaded = CasePool(run_id)
    loaded.load_storage(db_session)
    assert loaded.case_runtime[case["case_id"]]["state"] == "resolved"
    loaded_deliveries = [
        item
        for items in loaded.deliveries.values()
        for item in items
        if item["case_id"] == case["case_id"]
    ]
    assert [item["call_id"] for item in loaded_deliveries] == ["real-child-call"]
    assert loaded_deliveries[0]["is_write"] is True
    # 只有真实诊断报告被采纳，不伪造子报告
    reports = _reports(db_session, run_id)
    assert [row.report_id for row in reports] == [report_id]
    assert db_session.get(DiagnosisReport, report_id).session_id == session_id
