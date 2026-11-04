"""诊断程序依赖批量执行、真实保存与内外层逐操作审计"""

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.agent import AnnotationAgent
from src.agents.diagnosis.domain import DiagnosisDomain
from src.agents.diagnosis.evidence import DiagnosisEvidenceLedger
from src.agents.diagnosis.program_runtime import DiagnosisProgramDependencyError, DiagnosisProgramRuntime
from src.agents.diagnosis.runner import _run_diagnosis_agent
from src.agents.diagnosis.tools import build_diagnosis_tools
from src.agents.messages import AssistantMessage
from src.agents.tools import tool
from src.audit.queries import fetch_agent_turns, fetch_run_tool_calls
from src.audit.recorder import AgentAuditRecorder
from src.event_bus import EventBus
from src.event_trees.organization import EventOrganizationDraft
from src.event_trees.storage_map import run_annotation_event_ids, run_events
from src.storage.models import Agent, DiagnosisReport
from src.utils.cancellation import run_cancellable
from tests.agents.test_complete_event_work import execution_for, save_and_confirm
from tests.agents.test_diagnosis_agent import Replies, call, run_graph
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.storage_fixtures import fixture_id, storage_factory, storage_for


@pytest.fixture
async def declaration_case(db_session):
    novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜寻路，点亮灯火，打开旧信，核对地图，通知同伴。"])
    agent = AnnotationAgent(EventBus(), run_id, storage_factory(lambda: db_session), novel_id=novel_id)
    execution, program = execution_for(agent, db_session, 1)
    receipt = json.loads(
        await program.execute(
            "\n".join(
                f'created_{key} = write_event(items=[dict(el="{key}", title="{title}", problem="能否{title}", '
                f'summary="顾霜{title}", event_type="行动", status="ongoing", evidence=1)])\n'
                for key, title in (
                    ("a", "寻路"),
                    ("b", "点灯"),
                    ("c", "读信"),
                    ("d", "核对地图"),
                    ("e", "通知同伴"),
                )
            )
        )
    )
    assert not receipt.get("failed"), receipt
    await save_and_confirm(agent, db_session, execution)
    draft = EventOrganizationDraft(storage_for(db_session), run_id, "program-fixture")
    draft.fixture_session = db_session
    draft.case_id, draft.producer_agent_id = "program-fixture-case", "program-fixture"
    yield draft
    agent.close()


def _program_graph(model, runtime, *, observer=None, completion_check=lambda: [], maximum=10):
    """按生产会话图装配（程序面 execute_code + finish），图外不再有派发机制"""
    from src.agents.annotation.shared_tools import build_finish_tool
    from src.agents.diagnosis.session_loop import build_diagnosis_loop

    if "finish" not in runtime.tools:
        finish_tool = build_finish_tool(lambda: {"status": "end_requested"})
        runtime.tools["finish"] = finish_tool
        runtime.tool_list.append(finish_tool)
    return build_diagnosis_loop(
        model,
        runtime,
        max_iterations=maximum,
        observer=observer,
        completion_check=completion_check,
    )


def identity_item(key, index, *, invalid=False):
    return json.dumps(
        {
            "key": key,
            "title": key,
            "problem": "能否找到路",
            "summary": "寻路与点灯",
            "event_type": "寻路",
            "status": "ongoing",
            "from": 1,
            "to": 1,
            "reason": "原文中的整体事件",
            "evidence": [{"paragraph_id": 999 if invalid else 0}],
        },
        ensure_ascii=False,
    )


def case_identity_item(key, reference):
    """案例会话的身份项：认领所办案例自身的声明，不引用页面序号"""
    return (
        '{"operation":"identity", "key":'
        + json.dumps(key)
        + ', "title":'
        + json.dumps(key)
        + ', "problem":"能否找到路", "summary":"寻路与点灯", "event_type":"寻路", "status":"ongoing", '
        '"source_event_ids":[' + reference + '], "reason":"依据原文核对身份", '
        '"evidence":[{"paragraph_id":0}]}'
    )


#: 案例会话第一件案例：自取未承诺案例，确认无真实父树后直接办结
FIRST_CASE_PROGRAM = """
cases = search_cases(unresolved_only=True)
case = cases[0]
claim_case(case_id=case["case_id"])
search_events(tree_id=case["tree_id"], limit=20)
submit_case(case_id=case["case_id"])
"""
SECOND_CASE_PROGRAM = (
    "\ncases = search_cases(unresolved_only=True)\ncase = cases"
    '[0]\nclaim_case(case_id=case["case_id"])\npage = search_ev'
    'ents(limit=20)\nreceipt = write_event(items=[{\n    "key":"整体"'
    ', "title":"寻路与照明", "problem":"能否寻路",\n    "summary":"寻路与照'
    '明", "event_type":"行动", "status":"ongoing", "from":1, "to'
    '":1,\n    "reason":"整体行动", "evidence":[{"paragraph_id":0}'
    ']}],\n    caseid=case["case_id"])\nown = receipt["results"][0]["event_id'
    '"]\nown_tree = receipt["tree_id"]\nread_event(node_id=own, kind="event")\n'
    'search_events(tree_id=case["tree_id"], limit=20)\nwrite_link(item'
    's=[{\n    "operation":"reference", "parent_tree_id":own_tree,'
    ' "child_tree_id":case["tree_id"],\n    "re'
    'ason":"整体行动包含案例事件树", "evidence":[{"paragraph_id":0}]}], c'
    'aseid=case["case_id"])\nsubmit_case(case_id=case["case_id'
    '"])\n'
)
CLOSE_PROGRAM = """
cases = search_cases(unresolved_only=True)
first = cases[0]
if len(cases) >= 2:
    claim_case(case_id=first["case_id"])
    parent = write_event(items=[], tree_key="case-parent-" + first["case_id"],
        title="案例归并父树", caseid=first["case_id"])["tree_id"]
    for case in cases:
        if case["case_id"] != first["case_id"]:
            claim_case(case_id=case["case_id"])
        search_events(tree_id=case["tree_id"], limit=20)
        write_link(items=[{"operation":"reference", "parent_tree_id":parent, "child_tree_id":case["tree_id"],
            "reason":"事件案例归并到父树", "evidence":[{"paragraph_id":0}]}], caseid=case["case_id"])
    for case in cases:
        submit_case(case_id=case["case_id"])
else:
    claim_case(case_id=first["case_id"])
    search_events(tree_id=first["tree_id"], limit=20)
    submit_case(case_id=first["case_id"])
finish()
"""
REPORT_PROGRAM = """
read_topics()
name_event_lines(names=__NAMES__)
parents = search_events(kind="event", query="寻路与照明", limit=20)
for entry in search_events(limit=20)["events"]:
    read_event(node_id=entry["event_id"])
outcome = write_outcome(items=[{"operation":"outcome", "key":"light", "title":"获得照明", "description":"点灯带来照明",
    "evidence":[{"paragraph_id":0}]}])
write_diagnosis(analysis={"diagnosis":"寻路与照明相互关联", "topic_labels":{}})
finish()
"""


async def test_real_runner_preserves_dependent_ids_across_barrier_and_publishes_once(
    declaration_case,
    configured_model_pool,
    monkeypatch,
):
    from src.case_pool import CasePool
    from src.config import settings
    from src.config.schemas.model import WeightedModelSettings

    draft = declaration_case
    # 案例会话数=池条目并发位；固定为 1 使会话自取顺序确定（同一会话连办两件案例）
    monkeypatch.setattr(
        settings.models,
        "model_pool",
        [
            WeightedModelSettings(
                "test-model", "https://test.example/v1", "test-key", context_window_tokens=128000, max_in_flight=1
            ),
        ],
    )
    recorder = AgentAuditRecorder(
        storage_factory(sessionmaker(bind=draft.fixture_session.get_bind(), expire_on_commit=False))
    )
    model = Replies(
        [
            AssistantMessage(content="", tool_calls=[call("execute_code", {"code": code})])
            for code in (FIRST_CASE_PROGRAM, SECOND_CASE_PROGRAM, CLOSE_PROGRAM, REPORT_PROGRAM)
        ]
    )
    domain = DiagnosisDomain(
        session=storage_for(draft.fixture_session),
        run_id=draft.run_id,
        novel_id=fixture_id(__name__, "test-novel"),
        agent_id=fixture_id(__name__, "diag-program-save"),
        novel_title=None,
        model_id="test-model",
    )

    async def trace_ainvoke(messages):
        # 会话按角色与已发生的模型回合数取程序段：案例会话自取连办两件再收尾，报告会话一次收口
        model.requests.append(list(messages))
        human = next(
            str(m.content)
            for m in reversed(messages)
            if type(m).__name__ == "UserMessage" and str(m.content).lstrip().startswith("{")
        )
        payload = json.loads(human)
        turns = sum(1 for message in messages if isinstance(message, AssistantMessage))
        if payload["role"] == "report":
            names = {
                row["tree_id"]: f"事件{index}线"
                for index, row in enumerate(payload["materials"]["event_lines"], start=1)
            }
            code = REPORT_PROGRAM.replace("__NAMES__", json.dumps(names, ensure_ascii=False))
        elif len(model.requests) >= 4:
            code = CLOSE_PROGRAM
        elif turns == 0:
            code = FIRST_CASE_PROGRAM
        elif turns == 1:
            code = SECOND_CASE_PROGRAM
        else:
            code = CLOSE_PROGRAM
        return AssistantMessage(
            content="",
            tool_calls=[
                {"name": "execute_code", "args": {"code": code}, "id": f"c{len(model.requests)}", "type": "tool_call"}
            ],
        )

    model.ainvoke = trace_ainvoke
    result = await _run_diagnosis_agent(
        session=storage_for(draft.fixture_session),
        run_id=draft.run_id,
        novel_id=fixture_id(__name__, "test-novel"),
        agent_id=fixture_id(__name__, "diag-program-save"),
        llm=model,
        audit_recorder=recorder,
        domain=domain,
    )
    assert model.bound == ["execute_code", "finish"]
    assert result.diagnosis == "寻路与照明相互关联"
    organization = result.narrative_organization
    assert len(organization.events) == 6
    children = {reference.child_tree_id for reference in organization.queue_references}
    roots = {queue.tree_id for queue in organization.queues} - children
    assert len(roots) == 1
    assert run_annotation_event_ids(storage_for(draft.fixture_session), draft.run_id) < {
        event.event_id for event in organization.events
    }
    report = draft.fixture_session.scalars(
        select(DiagnosisReport).join(Agent, Agent.id == DiagnosisReport.agent_id).where(Agent.run_id == draft.run_id)
    ).one()
    turns = fetch_agent_turns(storage_for(draft.fixture_session), draft.run_id)
    assert report.agent_id in {turn.agent_id for turn in turns}
    assert len(run_events(storage_for(draft.fixture_session), draft.run_id)) == 6
    # 案例写入按案例登记真实执行；事件案例均已接手承诺
    event_cases = {case["case_id"] for case in domain.case_pool.search() if case["case_type"] == "event"}
    assert event_cases
    reloaded = CasePool(draft.run_id)
    reloaded.load_storage(storage_for(draft.fixture_session))
    assert {case["case_id"] for case in reloaded.search() if case["submitted"]} >= event_cases
    turns = fetch_agent_turns(storage_for(draft.fixture_session), draft.run_id)
    assert len(turns) == len(model.requests)
    assert all(turn.task_type == "diagnosis" for turn in turns)
    assert all(turn.error is None and turn.turn_ms is not None for turn in turns)
    # 成功会话的执行行同样写终态：执行行不能停在 running
    settled = list(
        draft.fixture_session.scalars(
            select(Agent).where(Agent.run_id == draft.run_id, Agent.type.in_(("case", "report")))
        )
    )
    assert settled and all(row.status == "success" for row in settled)
    assert {turn.agent_id for turn in turns} == {row.id for row in settled}
    for row in settled:
        final_turn = max((turn for turn in turns if turn.agent_id == row.id), key=lambda turn: turn.turn_index)
        assert any(note.startswith("runtime:queue_wait_ms=") for note in final_turn.timing_notes)
        assert any(note.startswith("runtime:save_ms=") for note in final_turn.timing_notes)
    operations = fetch_run_tool_calls(storage_for(draft.fixture_session), draft.run_id)
    promises = [operation for operation in operations if operation.tool_name == "claim_case"]
    assert promises and all(
        {"lock_wait_ms", "execution_ms"} <= operation.executed_args["_timing"].keys() for operation in promises
    )
    refused = [operation for operation in operations if operation.error is not None]
    assert refused == [], [(operation.tool_name, operation.error) for operation in refused]
    outer = [
        str(operation.response_observed.get("result", ""))
        for operation in operations
        if operation.tool_name == "execute_code"
    ]
    assert len(outer) == len(model.requests)
    assert all('"progress"' not in value and '"remaining"' not in value for value in outer)


async def test_case_write_tool_lands_in_case_ledger_of_promised_case(declaration_case):
    """案例处置写入经真实绑定落在所办案例自己的账本与执行贡献上，来源不是账本元组"""
    from src.agents.diagnosis.domain import DiagnosisDomain

    draft = declaration_case
    domain = DiagnosisDomain(
        session=storage_for(draft.fixture_session),
        run_id=draft.run_id,
        novel_id=fixture_id(__name__, "test-novel"),
        agent_id=fixture_id(__name__, "case-ledger-chain"),
        novel_title=None,
        model_id="test-model",
    )
    context = domain.build_session_context("case", fixture_id(__name__, "case-session-a"), MagicMock())
    case = domain.case_pool.push("character", "核实顾霜的人物记录", fixture_id(__name__, "case-session-a"))
    other = domain.case_pool.push("character", "核实他人记录", fixture_id(__name__, "case-session-a"))
    missing = json.loads(await context.program.execute('write_entity(name="顾霜", entity_type="character", el="p1")'))
    assert missing["status"] == "partial" and "缺少 caseid" in missing["failed"][0]["message"]
    unpromised = json.loads(
        await context.program.execute(
            f'write_entity(name="顾霜", entity_type="character", el="p1", caseid={other["case_id"]!r})'
        )
    )
    assert unpromised["status"] == "partial" and "尚未 claim" in unpromised["failed"][0]["message"]
    domain.case_pool.claim(case["case_id"], fixture_id(__name__, "case-session-a"))
    applied = json.loads(
        await context.program.execute(
            f'write_entity(name="顾霜", entity_type="character", el="p1", caseid={case["case_id"]!r})'
        )
    )
    assert applied["status"] == "applied"
    assert "case_link" not in applied["written"][0]["result"]
    ledger, invocation = domain.case_writers[fixture_id(__name__, "case-session-a")]
    assert [op["name"] for op in ledger.graph.contributions[invocation]["entity_ops"]] == ["顾霜"]
    assert case["case_id"] in domain.case_pool.claims_for(fixture_id(__name__, "case-session-a"))
    assert domain.case_pool.submissions_for(fixture_id(__name__, "case-session-a")) == []
    assert not hasattr(domain.case_pool, "deliveries")


async def test_invalid_queue_member_leaves_no_candidate_and_program_can_continue(declaration_case):
    draft = declaration_case
    runtime = DiagnosisProgramRuntime(
        build_diagnosis_tools(
            storage_for(draft.fixture_session),
            draft.run_id,
            organization_draft=draft,
            agent_id=fixture_id(__name__, "partial-program"),
        )
    )
    first = (
        "page = search_events(limit=20)\nresult = write_event(items=["
        + identity_item("first", 0)
        + ","
        + identity_item("bad", 0, invalid=True)
        + "])"
    )
    receipt = json.loads(await runtime.execute(first))
    assert receipt["status"] == "partial" and len(receipt["failed"]) == 1
    assert runtime.env["result"] is None and not draft.events and not draft.queues
    assert receipt["reads"][0]["result"]["total"] == 5
    assert set(receipt) <= {"status", "failed", "reads", "written", "variables"}
    second = await runtime.execute('page2 = read_event(node_id=page["events"][1]["event_id"])')
    assert json.loads(second)["status"] == "applied"
    assert runtime.env["page2"]["event_id"] == runtime.env["page"]["events"][1]["event_id"]


async def test_case_warning_preserves_original_id_return_type(declaration_case):
    draft = declaration_case
    runtime = DiagnosisProgramRuntime(
        build_diagnosis_tools(
            storage_for(draft.fixture_session),
            draft.run_id,
            role="report",
            organization_draft=draft,
            agent_id=fixture_id(__name__, "case-warning"),
        )
    )
    receipt = json.loads(
        await runtime.execute(
            'outcome = write_outcome(items=[{"operation":"outcome", "key":"journey", '
            '"title":"找到路", "description":"寻路成功", '
            '"evidence":[{"paragraph_id":0}]}], caseid="not-promised")'
        )
    )
    assert receipt["status"] == "applied" and isinstance(runtime.env["outcome"]["results"][0], str)
    assert "case_link" not in receipt["written"][0]["result"]
    assert runtime.env["outcome"]["results"][0] in draft.outcomes


async def test_report_event_index_compact_page_allows_one_hundred(declaration_case):
    """诊断对象索引与声明面同一契约：compact 索引每页可到 100，详情预览仍限 20"""
    draft = declaration_case
    runtime = DiagnosisProgramRuntime(
        build_diagnosis_tools(
            storage_for(draft.fixture_session),
            draft.run_id,
            role="report",
            organization_draft=draft,
            agent_id=fixture_id(__name__, "report-index"),
        )
    )
    receipt = json.loads(
        await runtime.execute(
            'page = search_events(kind="event", limit=100, compact=True)\n'
            'plain = search_events(kind="event", limit=100)'
        )
    )
    assert receipt["status"] == "partial"
    assert [item["message"] for item in receipt["failed"]] == [
        "limit=100 越界：详情预览每页最多 20 条，精简一页请用 compact=True（最多 100 条）"
    ]
    assert runtime.env["page"]["total"] == 5 and len(runtime.env["page"]["events"]) == 5


async def test_partial_program_outer_audit_is_error_and_keeps_full_receipt_in_same_session():
    @tool
    def bad(value: int) -> str:
        """明确的模型参数校验失败"""
        raise ValueError("参数不满足业务约束")

    observer = MagicMock()
    runtime = DiagnosisProgramRuntime([bad], observer=observer)
    model = Replies(
        [
            AssistantMessage(content="", tool_calls=[call("execute_code", {"code": "bad(value=1)"})]),
            AssistantMessage(content="请求结束"),
        ]
    )
    graph = _program_graph(model, runtime, observer=observer, completion_check=lambda: [])
    result = await run_graph(graph)
    assert result.get("completion_ok") is True
    rows = [call.kwargs for call in observer.record_tool_call.call_args_list]
    assert [row["tool_name"] for row in rows] == ["bad", "execute_code"]
    assert all(row["error"] is not None for row in rows)
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
    model = Replies([AssistantMessage(content="", tool_calls=[call("execute_code", {"code": "broken()\nlater()"})])])
    graph = _program_graph(model, runtime, observer=observer, completion_check=lambda: [])
    with pytest.raises(DiagnosisProgramDependencyError, match="dependency unavailable"):
        await run_graph(graph)
    assert len(model.requests) == 1
    audited = [call.kwargs for call in observer.record_tool_call.call_args_list]
    assert [row["tool_name"] for row in audited] == ["broken", "execute_code"]
    assert all(row["error"] is not None for row in audited)
    assert audited[0]["request_args"]["_program"]["source_line"] == 1
    observer.close_turn.assert_called()


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
    model = Replies([AssistantMessage(content="", tool_calls=[call("execute_code", {"code": "wait()"})])])
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
            storage_for(draft.fixture_session),
            draft.run_id,
            organization_draft=draft,
            evidence_ledger=DiagnosisEvidenceLedger(),
        )
    )
    receipt = json.loads(await runtime.execute("finish()\nimport os"))
    assert receipt["status"] == "runtime_error" and runtime.take_end_request() is False


async def test_case_program_dialogue_uses_real_tool_validation():
    seen: list[int] = []

    @tool
    def write_dialogue(candidate_index: int, verdict: str) -> str:
        """记录合法范围内的对话候选判定"""
        if not 1 <= candidate_index <= 3:
            raise ValueError("candidate_index 超出候选范围")
        seen.append(candidate_index)
        return json.dumps({"status": "written", "candidate_index": candidate_index}, ensure_ascii=False)

    runtime = DiagnosisProgramRuntime([write_dialogue])
    receipt = json.loads(await runtime.execute('write_dialogue(candidate_index=2, verdict="dialogue")'))
    assert receipt["status"] == "applied" and seen == [2]
    beyond = json.loads(await runtime.execute('write_dialogue(candidate_index=9, verdict="dialogue")'))
    assert beyond["status"] == "partial" and beyond["failed"][0]["tool"] == "write_dialogue"
    assert "超出候选范围" in beyond["failed"][0]["message"] and seen == [2]


async def test_queue_has_one_atomic_audit_call_and_rejected_case_has_no_submission(declaration_case):
    from src.case_pool import CasePool

    draft = declaration_case
    pool, observer = CasePool(draft.run_id), MagicMock()
    author = fixture_id(__name__, "batch-audit")
    runtime = DiagnosisProgramRuntime(
        build_diagnosis_tools(
            storage_for(draft.fixture_session),
            draft.run_id,
            organization_draft=draft,
            case_pool=pool,
            agent_id=author,
        ),
        observer=observer,
    )
    program = (
        'page = search_events(limit=2)\ncase = push_case(case_type="event", description="核对事件身份")\n'
        'claim_case(case_id=case["case_id"])\nresult = write_event(items=['
        + identity_item("a", 0)
        + ","
        + identity_item("bad", 0, invalid=True)
        + ","
        + identity_item("b", 1)
        + '], caseid=case["case_id"])'
    )
    receipt = json.loads(await runtime.execute(program))
    assert receipt["status"] == "partial" and len(receipt["failed"]) == 1
    rows = [
        item.kwargs for item in observer.record_tool_call.call_args_list if item.kwargs["tool_name"] == "write_event"
    ]
    assert [bool(row["error"]) for row in rows] == [True]
    assert rows[0]["request_args"]["_program"]["item_index"] is None
    assert len(rows[0]["request_args"]["items"]) == 3
    assert pool.claims_for(author) == [runtime.env["case"]["case_id"]]
    assert pool.submissions_for(author) == []
    assert not hasattr(pool, "deliveries")
    assert "case_link" not in rows[0]["receipt"]
    assert runtime.env["result"] is None and not draft.events and not draft.queues


@pytest.mark.asyncio
async def test_invalid_arguments_name_fields_in_chinese_without_english_envelope():
    @tool
    def write_probe(items: list[int]) -> str:
        "测试用写入工具，供参数校验回执断言"
        return json.dumps({"status": "written"}, ensure_ascii=False)

    receipt = json.loads(await DiagnosisProgramRuntime([write_probe]).execute("result = write_probe()"))
    assert receipt["status"] == "partial"
    message = receipt["failed"][0]["message"]
    assert "缺少必填字段" in message
    assert "items" in message
    assert "write_probe" in message
    assert "validation error" not in message.lower()
