"案例仅保存登记与承诺，业务结果独立保存"

import json

import pytest
from sqlalchemy import select

from src.agents.annotation.agent import AnnotationAgent
from src.case_pool import CasePool
from src.event_bus import EventBus
from src.storage.models import Case, EventDeclaration
from tests.agents.test_complete_event_work import execution_for, save_and_confirm
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.storage_fixtures import storage_factory, storage_for


@pytest.mark.parametrize("caseid", ["not-in-run", 123, [], {}])
async def test_invalid_caseid_keeps_written_declaration(db_session, caseid):
    novel, run = create_run_with_chunks(db_session, texts=["原文行动。"])
    agent = AnnotationAgent(EventBus(), run, storage_factory(lambda: db_session), novel_id=novel)
    execution, runtime = execution_for(agent, db_session, 1)
    try:
        receipt = json.loads(
            await runtime.execute(
                'event(el="t", title="行动", problem="行动目标", '  # 同一程序文本
                'summary="行动", '
                'event_type="行动", status="ongoing", evidence=1)',
                caseid,
            )
        )
        assert not receipt.get("failed")
        assert not receipt.get("warnings")
        assert "case_link" not in str(receipt)
        record_id = await save_and_confirm(agent, db_session, execution)
        assert db_session.scalar(select(EventDeclaration).where(EventDeclaration.record_id == record_id)) is not None
    finally:
        agent.close()


async def test_promised_case_keeps_business_output_without_child_entries(db_session):
    novel, run = create_run_with_chunks(db_session, texts=["开门点灯。"])
    agent = AnnotationAgent(EventBus(), run, storage_factory(lambda: db_session), novel_id=novel)
    execution, runtime = execution_for(agent, db_session, 1)
    author = execution.invocation_id
    caseid = agent.case_pool.push("character", "核查点灯", author)["case_id"]
    try:
        result = json.loads(
            await runtime.execute(
                'event(el="a", title="开门", problem="行动目标", summary="开门", '
                'event_type="行动", status="ongoing", evidence=1)',
                caseid,
            )
        )
        assert not result.get("warnings")
        agent.case_pool.promise(caseid, author)
        result = json.loads(
            await runtime.execute(
                'event(el="b", title="点灯", problem="行动目标", summary="点灯", '
                'event_type="行动", status="ongoing", evidence=1)',
                caseid,
            )
        )
        assert not result.get("failed")
        await save_and_confirm(agent, db_session, execution)
        row = db_session.get(Case, caseid)
        assert row.status == "resolved" and row.promised_agent_id == author
        assert row.producer_agent_id == author
        assert not hasattr(agent.case_pool, "deliveries")
    finally:
        agent.close()


def test_promise_tracks_owner_without_business_association():
    pool = CasePool("run")
    pool.begin("a")
    pool.begin("b")
    caseid = pool.push("dialogue", "核对说话人", "a")["case_id"]
    assert not hasattr(pool, "associate")
    assert pool.promise(caseid, "a")["status"] == "promised"
    pool.rollback("a")
    assert caseid not in pool.cases
    pool.begin("a")
    caseid = pool.push("dialogue", "重新核对", "a")["case_id"]
    pool.promise(caseid, "a")
    pool.confirm("a")
    pool.rollback("a")
    assert pool.case_runtime[caseid]["owner"] == "a"


async def test_declared_event_registers_plain_case_and_restores(db_session):
    novel, run = create_run_with_chunks(db_session, texts=["原文行动。"])
    agent = AnnotationAgent(EventBus(), run, storage_factory(lambda: db_session), novel_id=novel)
    execution, runtime = execution_for(agent, db_session, 1)
    try:
        result = json.loads(
            await runtime.execute(
                'event(el="t", title="行动", problem="行动目标", summary="行动", '
                'event_type="行动", status="ongoing", evidence=1)'
            )
        )
        assert not result.get("failed")
        case = agent.case_pool.search("event")[0]
        assert set(case) == {"case_id", "case_type", "description", "promised"}
        again = agent.case_pool.register_event_case(title="行动", summary="行动", author=execution.invocation_id)
        assert again["case_id"] == case["case_id"]
        await save_and_confirm(agent, db_session, execution)
        pool = CasePool(run)
        pool.load_storage(storage_for(db_session))
        assert pool.search("event")[0]["description"] == "行动：行动"
    finally:
        agent.close()


def test_program_cases_need_no_work_identity(db_session):
    _, run = create_run_with_chunks(db_session, texts=["原文。"])
    pool = CasePool(run)
    ids = pool.save_pending(
        storage_for(db_session),
        [(kind, f"核查{kind}") for kind in ("character", "relation", "dialogue", "event")],
        author="program",
    )
    db_session.expire_all()
    for caseid in ids:
        row = db_session.get(Case, caseid)
        assert row.producer_agent_id is None and row.status == "pending"
    with pytest.raises(ValueError):
        pool.push("note", "无效类型", "program")
    with pytest.raises(ValueError):
        pool.push("event", "长" * 101, "program")
