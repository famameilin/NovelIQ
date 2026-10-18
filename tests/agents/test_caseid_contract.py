"""案例是显式可选关联，业务成功与关联失败必须能够独立确认"""

import json
from unittest.mock import patch

import pytest
from sqlalchemy import select

from src.agents.annotation.agent import AnnotationAgent
from src.case_pool import CasePool
from src.case_pool.contributions import CaseContribution
from src.event_bus import EventBus
from src.storage.models import BookCase, CaseEntry, EventDeclaration, Execution, WorkItem, naive_utcnow
from tests.agents.test_complete_event_work import execution_for, save_and_confirm
from tests.support.chapter_annotation_helpers import create_run_with_chunks


@pytest.mark.parametrize("caseid", ["not-in-run", 123, [], {}])
async def test_invalid_caseid_keeps_written_declaration(db_session, caseid):
    novel, run = create_run_with_chunks(db_session, texts=["原文行动。"])
    agent = AnnotationAgent(EventBus(), run, lambda: db_session, novel_id=novel)
    execution, runtime = execution_for(agent, db_session, 1)
    try:
        receipt = json.loads(
            await runtime.execute(
                'event(el="t", title="行动", problem="行动目标", '  # 同一程序文本
                'summary="行动", event_type="行动", status="ongoing", evidence=1)',
                caseid,
            )
        )
        assert not receipt.get("failed")
        assert receipt["warnings"][0]["code"] == "case_association_failed"
        record_id = await save_and_confirm(agent, db_session, execution)
        assert (
            db_session.scalar(select(EventDeclaration).where(EventDeclaration.record_id == record_id))
            is not None
        )
    finally:
        agent.close()


async def test_program_default_explicit_none_and_unpromised_warning(db_session):
    novel, run = create_run_with_chunks(db_session, texts=["开门点灯。"])
    agent = AnnotationAgent(EventBus(), run, lambda: db_session, novel_id=novel)
    execution, runtime = execution_for(agent, db_session, 1)
    author = execution.invocation_id
    caseid = agent.case_pool.push("character", "核查点灯", author)["case_id"]
    try:
        unpromised = json.loads(
            await runtime.execute(
                'event(el="a", title="开门", problem="行动目标", '  # 同一程序文本
                'summary="开门", event_type="行动", status="ongoing", evidence=1)',
                caseid,
            )
        )
        assert unpromised["warnings"] and not agent.case_pool.deliveries[author]
        agent.case_pool.promise(caseid, author)
        result = json.loads(
            await runtime.execute(
                'search_cases(caseid=None)\nevent(el="b", title="点灯", problem="行动目标", '  # 同一程序文本
                'summary="点灯", event_type="行动", status="ongoing", evidence=1)',
                caseid,
            )
        )
        assert not result.get("failed")
        writes = [item for item in agent.case_pool.deliveries[author] if item["tool_name"] != "promise_case"]
        assert len(writes) == 1
        fact = writes[0]
        assert fact["tool_name"] == "write_event" and fact["call_id"].endswith("-op2")
        assert next(item for item in agent.case_pool.search() if item["case_id"] == caseid)["promised"] is True
        await runtime.execute(
            'event(el="c", title="收拾", problem="行动目标", '  # 同一程序文本
            'summary="收拾", event_type="行动", status="ongoing", evidence=1)'
        )
        assert len([item for item in agent.case_pool.deliveries[author] if item["tool_name"] != "promise_case"]) == 1
        await save_and_confirm(agent, db_session, execution)
        # 采纳是正式成功事务的真实决定：支持条目 adopted=True 即该案例已解决
        adopted = db_session.scalar(
            select(CaseEntry).where(CaseEntry.case_id == caseid, CaseEntry.adopted.is_(True))
        )
        assert adopted is not None and adopted.producer_execution_id == execution.invocation_id
    finally:
        agent.close()


def test_promise_is_the_only_resolution_signal_and_deliveries_require_it():
    """承诺是唯一解决信号；未承诺的交付被拒，读与写的痕迹都不改变承诺状态"""
    pool = CasePool("run")
    author = "inv"
    pool.begin(author)
    caseid = pool.push("dialogue", "核对", author)["case_id"]
    unpromised = pool.associate(caseid, author, tool_name="read_event", call_id="r0", receipt={}, is_write=False)
    assert unpromised["status"] == "warning" and not pool.deliveries[author]
    pool.promise(caseid, author)
    pool.associate(caseid, author, tool_name="read_event", call_id="r", receipt={}, is_write=False)
    assert pool.search()[0]["promised"] is True
    pool.associate(caseid, author, tool_name="write_event", call_id="w", receipt={}, is_write=True)
    pool.associate(caseid, author, tool_name="read_event", call_id="r2", receipt={}, is_write=False)
    pool.confirm(author)
    pool.begin("i2")
    pool.rollback("i2")
    assert pool.search()[0]["promised"] is True


def test_same_call_cannot_silently_deliver_another_case():
    pool = CasePool("run")
    author = "inv"
    pool.begin(author)
    first = pool.push("character", "核对第一项", author)["case_id"]
    second = pool.push("character", "核对第二项", author)["case_id"]
    pool.promise(first, author)
    args = {"tool_name": "write_event", "call_id": "same", "receipt": {"id": "p1"}, "is_write": True}
    assert pool.associate(first, author, **args)["status"] == "success"
    assert pool.associate(first, author, **args)["status"] == "success"
    pool.promise(second, author)
    assert pool.associate(second, author, **args)["status"] == "warning"
    assert [item["call_id"] for item in pool.deliveries[author] if item["tool_name"] != "promise_case"] == ["same"]


async def test_diagnosis_caseid_uses_actual_call_and_warning_preserves_report(db_session):
    from src.agents.annotation.tool_batch import _invoke_tool
    from src.agents.diagnosis.tools import build_diagnosis_tools
    from src.case_pool.tool_binding import current_case_call_id
    from tests.agents.test_diagnosis_agent import _analysis_payload, call

    _, run = create_run_with_chunks(db_session, texts=["核对原文。"])
    pool = CasePool(run)
    report = {}
    author = "diag"
    tools = {
        tool.name: tool
        for tool in build_diagnosis_tools(
            db_session, run, role="report", execution_id="diag", case_pool=pool, report_draft=report
        )
    }
    assert all("caseid" in tool.args_schema.model_fields for tool in tools.values())
    created = json.loads(
        await _invoke_tool(tools, call("push_case", {"case_type": "event", "description": "核对诊断"}, id="push"))
    )
    caseid = created["case_id"]
    args = {"analysis": _analysis_payload(), "caseid": caseid}
    warning = json.loads(await _invoke_tool(tools, call("write_diagnosis", args, id="unpromised")))
    assert warning["status"] == "written" and warning["case_link"]["status"] == "warning"
    assert report["analysis"]["diagnosis"] == args["analysis"]["diagnosis"]
    assert not pool.deliveries[author]
    await _invoke_tool(tools, call("promise_case", {"case_id": caseid}, id="promise"))
    await _invoke_tool(tools, call("search_cases", {"caseid": caseid}, id="read"))
    success = json.loads(await _invoke_tool(tools, call("write_diagnosis", args, id="actual-write")))
    assert success["case_link"]["delivery"] is True
    assert [
        (item["call_id"], item["is_write"])
        for item in pool.deliveries[author]
        if item["tool_name"] != "promise_case"
    ] == [("read", False), ("actual-write", True)]
    assert current_case_call_id.get() == ""
    assert pool.search()[0]["promised"] is True


def test_optional_case_savepoint_failure_preserves_business_output(db_session):
    _, run = create_run_with_chunks(db_session, texts=["原文。"])
    pool = CasePool(run)
    author = "inv"
    pool.begin(author)
    caseid = pool.push("relation", "核查", author)["case_id"]
    db_session.add(
        BookCase(
            case_id=caseid,
            registration_run_id=run,
            case_type="relation",
            description="核查",
        )
    )
    # 业务行（真实尝试）与案例关联相互独立：关联失败不得撤销业务事实
    db_session.add(
        Execution(
            execution_id="business",
            run_id=run,
            chapter_id=1,
            role="annotation",
            attempt_number=1,
            started_at=naive_utcnow(),
            status="success",
        )
    )
    db_session.flush()
    pool.promise(caseid, author)
    pool.associate(caseid, author, tool_name="event", call_id="real-call", receipt={}, is_write=True)
    frozen = CaseContribution(
        run,
        author,
        json.dumps(
            {
                "created_case_ids": [],
                "registrations": {caseid: pool.cases[caseid]},
                "deliveries": pool.deliveries[author],
            }
        ),
    )
    original = db_session.get

    def reject_case(model, *args, **kwargs):
        if model is BookCase:
            raise ValueError("关联约束失败")
        return original(model, *args, **kwargs)

    with patch.object(db_session, "get", side_effect=reject_case):
        warnings = pool.save_work(db_session, frozen)
    db_session.commit()
    pool.confirm(author)
    assert warnings[0]["code"] == "case_save_failed"
    assert db_session.get(Execution, "business") is not None
    # 落库失败只体现为告警：承诺在内存中保持，不因保存失败退回
    assert pool.search()[0]["promised"] is True
    with patch.object(db_session, "get", side_effect=ConnectionError("连接断开")):
        with pytest.raises(ConnectionError):
            pool.save_work(db_session, frozen)


async def test_missing_optional_case_does_not_block_work_confirmation(db_session):
    novel, run = create_run_with_chunks(db_session, texts=["原文行动。"])
    agent = AnnotationAgent(EventBus(), run, lambda: db_session, novel_id=novel)
    execution, runtime = execution_for(agent, db_session, 1)
    author = execution.invocation_id
    caseid = agent.case_pool.push("event", "核查行动", author)["case_id"]
    agent.case_pool.promise(caseid, author)
    original_get = db_session.get

    def missing_case(model, *args, **kwargs):
        return None if model is BookCase else original_get(model, *args, **kwargs)

    try:
        await runtime.execute(
            'event(el="t", title="行动", problem="行动目标", '  # 同一程序文本
            'summary="行动", event_type="行动", status="ongoing", evidence=1)',
            caseid,
        )
        with patch.object(db_session, "get", side_effect=missing_case):
            record_id = await save_and_confirm(agent, db_session, execution)
        assert execution.saved
        # 保存告警落案例条目告警形状（归属当次标注记录），不伪造成成功交付
        warnings = list(
            db_session.scalars(select(CaseEntry).where(CaseEntry.warning_record_id == record_id))
        )
        assert any(row.attempted_case_reference == caseid for row in warnings)
        # 四类化后 note 删除：未落库的占用案例保持承诺状态，不阻塞确认
        assert (
            next(item for item in agent.case_pool.search() if item["case_id"] == caseid)["promised"] is True
        )
    finally:
        agent.close()


async def test_declared_event_is_registered_into_book_case_pool(db_session):
    """write_event 落地即登记事件案例"""
    novel, run = create_run_with_chunks(db_session, texts=["原文行动。"])
    agent = AnnotationAgent(EventBus(), run, lambda: db_session, novel_id=novel)
    execution, runtime = execution_for(agent, db_session, 1)
    try:
        receipt = json.loads(
            await runtime.execute(
                'event(el="t", title="行动", problem="行动目标", '  # 同一程序文本
                'summary="行动", event_type="行动", status="ongoing", evidence=1)'
            )
        )
        assert not receipt.get("failed")
        declaration_id = receipt["written_refs"][0]["ref"]["declaration_id"]
        cases = agent.case_pool.search(case_type="event")
        assert len(cases) == 1
        record = cases[0]
        assert record["payload"]["event_id"] == declaration_id
        assert record["payload"]["title"] == "行动" and record["payload"]["summary"] == "行动"
        assert record["payload"]["status"] == "ongoing" and record["payload"]["chapter_id"] == 1
        # 幂等：同一事件只登记一次，重复登记不改写案例
        again = agent.case_pool.register_event_case(
            declaration_id=declaration_id, title="行动", summary="行动", status="ongoing", chapter_id=1,
            author=execution.invocation_id,
        )
        assert again["case_id"] == record["case_id"]
        assert len(agent.case_pool.search(case_type="event")) == 1
        await save_and_confirm(agent, db_session, execution)
        row = db_session.get(BookCase, record["case_id"])
        assert row is not None
        assert row.case_type == "event" and row.automatic_declaration_id == declaration_id
        assert row.description == "行动" and row.review_state is None
        # 诊断侧启动加载 session 后仍能按 case_type 过滤
        pool = CasePool(run)
        pool.load_storage(db_session)
        assert [item["payload"]["event_id"] for item in pool.search(case_type="event")] == [declaration_id]
    finally:
        agent.close()


async def test_typed_cases_cover_four_types_and_required_payloads(db_session):
    """note 删除、四类归档、程序链各凭定位键"""
    _, run = create_run_with_chunks(db_session, texts=["原文。"])
    pool = CasePool(run)
    author = "inv"
    pool.begin(author)
    ids = [pool.push(t, f"核查{t}案例", author)["case_id"] for t in ("character", "relation", "dialogue", "event")]
    assert len(set(ids)) == 4
    assert all(record["payload"] == {} for record in pool.search())
    with pytest.raises(ValueError):
        pool.push("note", "注销类型残留", author)
    spec = {
        "character": {"node_id": "n", "name": "张三", "entity_type": "character"},
        "relation": {"node_id": "n"},
        "dialogue": {"candidate_key": "k", "chapter_id": 1},
        "event": {"event_id": "e"},
    }
    registered = {
        case_type: pool.register_case(
            case_type=case_type, description=f"定位{case_type}", payload=payload, author=author
        )["case_id"]
        for case_type, payload in spec.items()
    }
    assert len(set(registered.values())) == 4
    for record in pool.search():
        if record["case_id"] in registered.values():
            assert record["payload"] == spec[record["case_type"]]


async def test_save_pending_persists_payload_and_enforces_required_keys(db_session):
    """程序链登记走类型化 payload 落库；缺定位键直接拒绝，不降级"""
    from tests.support.event_tree_fixtures import ensure_character

    _, run = create_run_with_chunks(db_session, texts=["原文。"])
    entity_id = ensure_character(db_session, run_id=run, name="张三")
    author = "chapter:1:abc"
    db_session.add(
        WorkItem(
            work_id=author,
            program_run_id=run,
            program_chapter_id=1,
            program_code="chapter_consolidation",
            program_invocation_key="chapter:1:abc",
        )
    )
    db_session.flush()
    pool = CasePool(run)
    case_ids = pool.save_pending(
        db_session,
        [
            (
                "character",
                "核查张三身份",
                {
                    "node_id": entity_id,
                    "name": "张三",
                    "entity_type": "character",
                    "reason": "unreferenced_entity",
                },
            )
        ],
        author=author,
    )
    db_session.commit()
    row = db_session.get(BookCase, case_ids[0])
    assert row.case_type == "character" and row.entity_target_id == entity_id
    assert row.registration_reason == "unreferenced_entity" and row.review_state is None
    # 程序登记支持：无模型调用、无伪造交付
    support = db_session.scalar(
        select(CaseEntry).where(CaseEntry.case_id == case_ids[0], CaseEntry.program_work_id == author)
    )
    assert support is not None
    with pytest.raises(ValueError):
        pool.save_pending(db_session, [("character", "缺定位键", {})], author="chapter")
