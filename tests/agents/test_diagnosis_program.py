"""诊断程序依赖批量执行、真实保存与内外层逐操作审计"""

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.agent import AnnotationAgent
from src.agents.diagnosis.domain import DiagnosisDomain
from src.agents.diagnosis.evidence import DiagnosisEvidenceLedger
from src.agents.diagnosis.program_runtime import DiagnosisProgramDependencyError, DiagnosisProgramRuntime
from src.agents.diagnosis.runner import _run_diagnosis_agent
from src.agents.diagnosis.tools import build_diagnosis_tools
from src.agents.diagnosis.work_runtime import DiagnosisWorkContext
from src.audit.queries import fetch_agent_turns, fetch_run_tool_calls
from src.audit.recorder import AgentAuditRecorder
from src.event_bus import EventBus
from src.event_trees.organization import EventOrganizationDraft
from src.event_trees.storage_map import run_events
from src.storage.models import DiagnosisReport, Execution
from src.utils.cancellation import run_cancellable
from tests.agents.test_complete_event_work import execution_for, save_and_confirm
from tests.agents.test_diagnosis_agent import Replies, call, run_graph
from tests.support.chapter_annotation_helpers import create_run_with_chunks


@pytest.fixture
async def declaration_case(db_session):
    novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜寻路并点灯。"])
    agent = AnnotationAgent(EventBus(), run_id, lambda: db_session, novel_id=novel_id)
    execution, program = execution_for(agent, db_session, 1)
    receipt = json.loads(await program.execute(
        'event(el="a", title="寻路", problem="能否找到路", summary="顾霜寻路", '
        'event_type="寻路", status="ongoing", evidence=1)\n'
        'event(el="b", title="点灯", problem="能否照明", summary="顾霜点灯", '
        'event_type="照明", status="resolved", evidence=1)'
    ))
    assert not receipt.get("failed"), receipt
    await save_and_confirm(agent, db_session, execution)
    draft = EventOrganizationDraft(db_session, run_id, "program-fixture")
    draft.work_id, draft.producer_invocation_id = "program-fixture", "program-fixture"
    yield draft
    agent.close()


def _program_graph(model, runtime, *, observer=None, completion_check=lambda: [], maximum=10):
    """按生产会话图装配（程序面 execute_code + finish），图外不再有派发机制"""
    from src.agents.annotation.ledger import AnnotationToolLedger
    from src.agents.annotation.shared_tools import build_finish_tool
    from src.agents.annotation.subagent_graph import build_subagent_graph
    from src.agents.annotation.subagent_ir import SubagentAnnotation
    from src.agents.diagnosis.program_runtime import bind_finish_ledger

    if "finish" not in runtime.tools:
        finish_tool = build_finish_tool(lambda: {"status": "end_requested"})
        runtime.tools["finish"] = finish_tool
        runtime.tool_list.append(finish_tool)
    ledger = AnnotationToolLedger(
        run_scope="run", current_chapter_id=0, current_chapter_text="", allow_future_context=False
    )
    return build_subagent_graph(
        model,
        runtime.build_tool(),
        bind_finish_ledger(runtime.tools["finish"], ledger),
        ledger=ledger,
        subagent=SubagentAnnotation(role="event"),
        max_iterations=maximum,
        observer=observer,
        completion_check=completion_check,
    )


def identity_item(key, index, *, invalid=False):
    reference = '"not-declared"' if invalid else f'page["events"][{index}]["declaration_id"]'
    return ('{"operation":"identity", "key":' + json.dumps(key) + ', "title":' + json.dumps(key) +
            ', "problem":"能否找到路", "summary":"寻路与点灯", "event_type":"寻路", "status":"ongoing", '
            '"declaration_ids":[' + reference + '], "stage_order":[' + reference + '], '
            '"current_declaration_id":' + reference + ', "reason":"依据本章原文声明核对", '
            '"evidence":[{"paragraph_id":0}]}')


IDENTITY_CHILD = (
    'page = search_events(limit=20)\n'
    'child = write_event(items=[' + identity_item("寻路", 0) + '])\n'
    'write_event(items=[{"operation":"declaration_review", '
    '"declaration_ids":[page["events"][0]["declaration_id"]], "reason":"按本章原文逐段核对"}])\n'
    'write_event(items=[{"operation":"compare", "source_declaration_id":'
    'page["events"][0]["declaration_id"], "target_declaration_ids":'
    '[page["events"][1]["declaration_id"]], "disposition":"independent", '
    '"reason":"寻路和照明各有独立问题", "evidence":[{"paragraph_id":0}]}])\nfinish()'
)
IDENTITY_PARENT = (
    'page = search_events(limit=20)\n'
    'parent = write_event(items=[' + identity_item("寻路与照明", 1) + '])\n'
    'write_event(items=[{"operation":"declaration_review", '
    '"declaration_ids":[page["events"][1]["declaration_id"]], "reason":"按本章原文逐段核对"}])\nfinish()'
)
STRUCTURE_CHILD = (
    'page = search_events(limit=20)\n'
    'events = search_events(kind="event", query="寻路", limit=20)\n'
    'own = None\n'
    'parent = None\n'
    'for item in events["events"]:\n'
    '    if item["title"] == "寻路":\n'
    '        own = item\n'
    'for item in events["events"]:\n'
    '    if item["title"] == "寻路与照明":\n'
    '        parent = item\n'
    'write_event(items=[{"operation":"review", "event_ids":[own["event_id"]], "reason":"核对本事件实际版本"}])\n'
    'write_event(items=[{"operation":"contain", "parent_event_id":parent["event_id"], '
    '"child_event_id":own["event_id"], "reason":"寻路与照明行动包含寻路子问题", '
    '"evidence":[{"paragraph_id":0}]}, {"operation":"structure_review", '
    '"source_event_id":parent["event_id"], "target_event_id":own["event_id"], '
    '"disposition":"contains", "reason":"按原文明确两事件的包含而非同一身份", '
    '"evidence":[{"paragraph_id":0}]}])\n'
    'write_event(items=[{"operation":"review", "event_ids":[own["event_id"], parent["event_id"]], '
    '"reason":"按冻结身份核对包含与原文"}])\nfinish()'
)
STRUCTURE_PARENT = (
    'page = search_events(limit=20)\n'
    'events = search_events(kind="event", query="寻路", limit=20)\n'
    'own = None\n'
    'child = None\n'
    'for item in events["events"]:\n'
    '    if item["title"] == "寻路与照明":\n'
    '        own = item\n'
    'for item in events["events"]:\n'
    '    if item["title"] == "寻路":\n'
    '        child = item\n'
    'write_event(items=[{"operation":"review", "event_ids":[own["event_id"]], "reason":"核对本事件实际版本"}])\n'
    'write_event(items=[{"operation":"contain", "parent_event_id":own["event_id"], '
    '"child_event_id":child["event_id"], "reason":"寻路与照明行动包含寻路子问题", '
    '"evidence":[{"paragraph_id":0}]}, {"operation":"structure_review", '
    '"source_event_id":own["event_id"], "target_event_id":child["event_id"], '
    '"disposition":"contains", "reason":"按原文明确两事件的包含而非同一身份", '
    '"evidence":[{"paragraph_id":0}]}])\n'
    'write_event(items=[{"operation":"review", "event_ids":[own["event_id"], child["event_id"]], '
    '"reason":"按冻结身份核对包含与原文"}])\nfinish()'
)
REPORT_PROGRAM = '''
read_topics()
parents = search_events(kind="event", query="寻路与照明", limit=20)
case = push_case(case_type="relation", description="核对寻路与照明的关联")
promise_case(case_id=case["case_id"])
arc = write_arc(items=[{"operation":"arc", "key":"journey", "kind":"main", "title":"寻路线", "objective":"找到路",
    "role":"主线", "reason":"围绕寻路持续推进", "evidence":[{"paragraph_id":0}]}], caseid=case["case_id"])
outcome = write_outcome(items=[{"operation":"outcome", "key":"light", "title":"获得照明", "description":"点灯带来照明",
    "evidence":[{"paragraph_id":0}]}])
write_arc(items=[{"operation":"link", "event_id":parents["events"][0]["event_id"], "arc_id":arc["results"][0],
    "role":"推进", "reason":"寻路推进目标", "evidence":[{"paragraph_id":0}]}], caseid=case["case_id"])
write_outcome(items=[{"operation":"link", "event_id":parents["events"][0]["event_id"],
    "outcome_id":outcome["results"][0], "reason":"寻路中点灯形成照明", "evidence":[{"paragraph_id":0}]}])
write_diagnosis(analysis={"diagnosis":"寻路与照明相互关联", "topic_labels":{}})
finish()
'''


IDENTITY_CHILD = (
    'page = search_events(limit=20)\n'
    'child = write_event(items=[' + identity_item("寻路", 0) + '])\n'
    'write_event(items=[{"operation":"declaration_review", '
    '"declaration_ids":[page["events"][0]["declaration_id"]], "reason":"按本章原文逐段核对"}])\n'
    'write_event(items=[{"operation":"compare", "source_declaration_id":'
    'page["events"][0]["declaration_id"], "target_declaration_ids":'
    '[page["events"][1]["declaration_id"]], "disposition":"independent", '
    '"reason":"寻路和照明各有独立问题", "evidence":[{"paragraph_id":0}]}])\nfinish()'
)
IDENTITY_PARENT = (
    'page = search_events(limit=20)\n'
    'parent = write_event(items=[' + identity_item("寻路与照明", 1) + '])\n'
    'write_event(items=[{"operation":"declaration_review", '
    '"declaration_ids":[page["events"][1]["declaration_id"]], "reason":"按本章原文逐段核对"}])\nfinish()'
)


async def test_real_runner_preserves_dependent_ids_across_barrier_and_publishes_once(
    declaration_case, configured_model_pool,
):
    draft = declaration_case
    recorder = AgentAuditRecorder(sessionmaker(bind=draft.session.get_bind(), expire_on_commit=False))
    model = Replies([AIMessage(content="", tool_calls=[call("execute_code", {"code": code})])
                     for code in (IDENTITY_CHILD, IDENTITY_PARENT, STRUCTURE_CHILD, STRUCTURE_PARENT,
                                  REPORT_PROGRAM)])
    domain = DiagnosisDomain(session=draft.session, run_id=draft.run_id, novel_id="test-novel",
        execution_id="diag-program-save", novel_title=None, model_id="test-model")
    order = {identifier: position for position, identifier in enumerate(domain.sources)}
    async def trace_ainvoke(messages):
        # 每轮按责任声明序取对应程序段：声明序 == 声明来源序（search_events 同源顺序）
        model.requests.append(list(messages))
        human = next(
            str(m.content) for m in reversed(messages)
            if type(m).__name__ == "HumanMessage" and str(m.content).lstrip().startswith("{")
        )
        payload = json.loads(human)
        # 阶段按角色与结构材料键判别：identity 阶段 material 同样带 catalog，不能按键名猜
        role = payload["role"]
        materials = payload.get("materials", {})
        phase = "report" if role == "report" else ("structure" if "identity_snapshot" in materials else "identity")
        position = order[payload["responsible_ids"][0]] if phase != "report" else -1
        if phase == "report":
            code = REPORT_PROGRAM
        elif phase == "identity":
            code = IDENTITY_CHILD if position == 0 else IDENTITY_PARENT
        else:
            code = STRUCTURE_CHILD if position == 0 else STRUCTURE_PARENT
        return AIMessage(content="", tool_calls=[{"name": "execute_code", "args": {"code": code},
                                                  "id": f"c{len(model.requests)}", "type": "tool_call"}])
    model.ainvoke = trace_ainvoke
    real_build_context = domain.build_context

    def tracked_build(work, phase, observer, corrections):
        context = real_build_context(work, phase, observer, corrections)
        check = context.completion_check

        def tracked():
            missing = check()
            if missing:
                print(f"GAP {phase} work={work.work_id[:8]} :: {missing}")
            return missing

        return DiagnosisWorkContext(context.program, context.initial_messages, tracked)

    domain.build_context = tracked_build
    result = await _run_diagnosis_agent(
        session=draft.session, run_id=draft.run_id, novel_id="test-novel", execution_id="diag-program-save",
        llm=model, audit_recorder=recorder, domain=domain,
    )
    assert model.bound == ["execute_code", "finish"]
    assert len(model.requests) == 5
    assert result.diagnosis == "寻路与照明相互关联"
    assert len(result.narrative_organization.events) == 2
    report = draft.session.scalars(
        select(DiagnosisReport)
        .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
        .where(Execution.session_run_id == draft.run_id)
    ).one()
    assert report.session_id == "diag-program-save"
    assert len(run_events(draft.session, draft.run_id)) == 2
    turns = fetch_agent_turns(draft.session, draft.run_id)
    assert len(turns) == 5
    assert len({turn.execution_id for turn in turns}) == 3
    assert all(turn.task_type == "diagnosis" for turn in turns)
    assert all(turn.status == "success" and turn.turn_ms is not None for turn in turns)
    operations = fetch_run_tool_calls(draft.session, draft.run_id)
    allowed_refusals = ("结构写入端点不是本 work", "结构比较不属于本 work", "事件核对端点不是本 work")
    assert all(
        operation.status == "success" or any(text in str(operation.error or "") for text in allowed_refusals)
        for operation in operations
    )
    refused = [operation for operation in operations if operation.status != "success"]
    assert all(operation.tool_name in {"write_event", "execute_code"} for operation in refused)
    outer = [str(operation.response_observed.get("result", ""))
             for operation in operations if operation.tool_name == "execute_code"]
    assert len(outer) == 5
    assert all('"progress"' not in value and '"remaining"' not in value for value in outer)


async def test_partial_program_keeps_success_and_rejected_operation_has_no_candidate(declaration_case):
    draft = declaration_case
    runtime = DiagnosisProgramRuntime(build_diagnosis_tools(
        draft.session, draft.run_id, organization_draft=draft, execution_id="partial-program"))
    first = ('page = search_events(limit=20)\nresult = write_event(items=[' + identity_item("first", 0) + ',' +
             identity_item("bad", 0, invalid=True) + '])')
    receipt = json.loads(await runtime.execute(first))
    assert receipt["status"] == "partial" and len(receipt["failed"]) == 1
    assert runtime.env["result"]["results"][1] is None and len(draft.events) == 1
    assert receipt["reads"][0]["result"]["total"] == 2
    assert set(receipt) <= {"status", "failed", "reads", "written", "variables"}
    second = await runtime.execute('page2 = read_event(node_id=page["events"][1]["declaration_id"])')
    assert json.loads(second)["status"] == "applied"
    assert runtime.env["page2"]["declaration_id"] == runtime.env["page"]["events"][1]["declaration_id"]


async def test_case_warning_preserves_original_id_return_type(declaration_case):
    draft = declaration_case
    runtime = DiagnosisProgramRuntime(build_diagnosis_tools(
        draft.session, draft.run_id, organization_draft=draft, execution_id="case-warning"))
    receipt = json.loads(await runtime.execute('arc = write_arc(items=[{"operation":"arc", "key":"journey", '
        '"kind":"main", "title":"寻路线", "objective":"找到路", "role":"主线", "reason":"围绕寻路", '
        '"evidence":[{"paragraph_id":0}]}], caseid="not-promised")'))
    assert receipt["status"] == "applied" and isinstance(runtime.env["arc"]["results"][0], str)
    assert receipt["written"][0]["result"]["case_link"]["status"] == "warning"
    assert runtime.env["arc"]["results"][0] in draft.arcs


async def test_partial_program_outer_audit_is_error_and_keeps_full_receipt_in_same_session():
    @tool
    def bad(value: int) -> str:
        """明确的模型参数校验失败"""
        raise ValueError("参数不满足业务约束")

    observer = MagicMock()
    runtime = DiagnosisProgramRuntime([bad], observer=observer)
    model = Replies(
        [
            AIMessage(content="", tool_calls=[call("execute_code", {"code": "bad(value=1)"})]),
            AIMessage(content="请求结束"),
        ]
    )
    graph = _program_graph(model, runtime, observer=observer, completion_check=lambda: [])
    result = await run_graph(graph)
    assert result.get("completion_ok") is True
    rows = [call.kwargs for call in observer.record_tool_call.call_args_list]
    assert [row["tool_name"] for row in rows] == ["bad", "execute_code"]
    assert all(row["status"] == "error" for row in rows)
    prior = model.requests[1][-1]
    receipt = json.loads(prior.content)
    assert receipt["status"] == "partial" and receipt["failed"][0]["line"] == 1


@pytest.mark.parametrize("code", ["import os", "print(value=1)", "value = (1).__class__"])
async def test_program_reuses_restricted_syntax_and_does_not_expose_process_access(code):
    runtime = DiagnosisProgramRuntime([])
    receipt = json.loads(await runtime.execute(code))
    assert receipt["status"] == "runtime_error" and receipt["error"]
    assert runtime.take_end_request() is False


async def test_dependency_failure_audits_inner_and_outer_then_stops_without_next_operation():
    @tool
    async def broken() -> str:
        """模拟系统依赖失败"""
        raise ConnectionError("dependency unavailable")

    @tool
    async def later() -> str:
        """后续写入不应执行"""
        raise AssertionError("late operation executed")

    observer = MagicMock()
    runtime = DiagnosisProgramRuntime([broken, later], observer=observer)
    model = Replies([AIMessage(content="", tool_calls=[call("execute_code", {"code": "broken()\nlater()"})])])
    graph = _program_graph(model, runtime, observer=observer, completion_check=lambda: [])
    with pytest.raises(DiagnosisProgramDependencyError, match="dependency unavailable"):
        await run_graph(graph)
    assert len(model.requests) == 1
    audited = [call.kwargs for call in observer.record_tool_call.call_args_list]
    assert [row["tool_name"] for row in audited] == ["broken", "execute_code"]
    assert all(row["status"] == "error" for row in audited)
    assert audited[0]["request_args"]["_program"]["source_line"] == 1
    observer.close_turn.assert_called_once()


async def test_cancel_interrupts_program_and_records_both_levels():
    started = asyncio.Event()
    cancelled = False

    @tool
    async def wait() -> str:
        """模拟可中断的长工具调用"""
        started.set()
        await asyncio.sleep(60)
        return "unexpected completion"

    observer = MagicMock()
    runtime = DiagnosisProgramRuntime([wait], observer=observer)
    model = Replies([AIMessage(content="", tool_calls=[call("execute_code", {"code": "wait()"})])])
    graph = _program_graph(model, runtime, observer=observer, completion_check=lambda: [])
    task = asyncio.create_task(run_cancellable(run_graph(graph), lambda: cancelled, poll_seconds=0.001))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        cancelled = True
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        # 取消发生在 wait 工具内部：逐操作审计先落库，批次级 execute_code 行随中断不再补写
        assert [call.kwargs["tool_name"] for call in observer.record_tool_call.call_args_list] == ["wait"]
        assert runtime.take_end_request() is False and len(model.requests) == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_interpreter_error_after_finish_does_not_request_premature_completion(declaration_case):
    draft = declaration_case
    runtime = DiagnosisProgramRuntime(
        build_diagnosis_tools(
            draft.session,
            draft.run_id,
            organization_draft=draft,
            evidence_ledger=DiagnosisEvidenceLedger(),
        )
    )
    receipt = json.loads(await runtime.execute("finish()\nimport os"))
    assert receipt["status"] == "runtime_error" and runtime.take_end_request() is False


async def test_batch_items_have_distinct_audit_ids_and_rejected_case_has_no_delivery(declaration_case):
    from src.case_pool import CasePool

    draft = declaration_case
    pool, observer = CasePool(draft.run_id), MagicMock()
    author = ("diagnosis:batch-audit", "batch-audit")
    runtime = DiagnosisProgramRuntime(build_diagnosis_tools(
        draft.session, draft.run_id, organization_draft=draft, case_pool=pool, execution_id=author[1]),
        observer=observer)
    program = ('page = search_events(limit=2)\ncase = push_case(case_type="event", description="核对事件身份")\n'
               'promise_case(case_id=case["case_id"])\nresult = write_event(items=[' +
               identity_item("a", 0) + ',' + identity_item("bad", 0, invalid=True) + ',' +
               identity_item("b", 1) + '], caseid=case["case_id"])')
    receipt = json.loads(await runtime.execute(program))
    assert receipt["status"] == "partial" and receipt["failed"][0]["item_index"] == 1
    rows = [item.kwargs for item in observer.record_tool_call.call_args_list
            if item.kwargs["tool_name"] == "write_event"]
    assert [row["status"] for row in rows] == ["success", "error", "success"]
    assert [row["request_args"]["_program"]["item_index"] for row in rows] == [0, 1, 2]
    assert len({row["request_args"]["_tool_call_id"] for row in rows}) == 3
    assert len(pool.deliveries[author]) == 2
    assert all(fact["is_write"] for fact in pool.deliveries[author])
    assert rows[1]["receipt"]["case_link"]["code"] == "case_association_failed"
    assert runtime.env["result"]["results"][1] is None
