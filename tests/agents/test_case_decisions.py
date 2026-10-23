"""案例持有、提交与同会话结束条件的无数据库验证"""

import json
import threading
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from src.agents.annotation.agent_graph import build_agent_graph
from src.agents.annotation.agent_ir import AgentAnnotation
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.shared_tools import build_case_tools, build_finish_tool
from src.agents.annotation.work_tools import build_work_tools
from src.agents.diagnosis import domain as domain_module
from src.agents.diagnosis.program_runtime import bind_finish_ledger
from src.fact_graph.graph import FactGraph
from src.storage import new_id
from tests.agents.test_diagnosis_agent import Replies, call, run_graph
from tests.support.annotation_work_tools import _work_tools_context


@pytest.fixture
def case_domain(monkeypatch):
    draft = SimpleNamespace(lock=threading.RLock(), publication_lock=threading.RLock())
    monkeypatch.setattr(domain_module, "EventOrganizationDraft", lambda *_: draft)
    monkeypatch.setattr(domain_module, "hydrate_draft_from_run", lambda *_: None)
    monkeypatch.setattr(domain_module.DiagnosisDomain, "_case_graph", lambda _: None)

    def tools(*args, **kwargs):
        kwargs["case_pool"].begin(kwargs["agent_id"])
        return [
            *build_case_tools(kwargs["case_pool"], kwargs["agent_id"]),
            build_finish_tool(lambda: {"status": "end_requested"}),
        ]

    monkeypatch.setattr(domain_module, "build_diagnosis_tools", tools)
    domain = domain_module.DiagnosisDomain(
        session=SimpleNamespace(cases=SimpleNamespace(rows=lambda _: [])),
        run_id=new_id(), novel_id=new_id(), agent_id=new_id(), novel_title=None, model_id="test",
    )
    author = new_id()
    context = domain.build_session_context("case", author, None)
    for index in range(3):
        domain.case_pool.push("event", f"核查事件{index}", author)
    return domain, author, context


def test_multiple_claims_must_all_submit_then_session_may_end(case_domain):
    domain, author, context = case_domain
    first = domain.case_pool.claim_random(author)["case_id"]
    second = domain.case_pool.claim_random(author)["case_id"]
    assert first != second and context.unsubmitted_count() == 2
    domain.case_pool.submit(first, author)
    assert any(second in message for message in context.completion_check())
    domain.case_pool.submit(second, author)
    assert context.completion_check() == []
    third = domain.case_pool.claim_random(author)["case_id"]
    assert context.completion_check()
    domain.case_pool.submit(third, author)
    assert context.completion_check() == []


def test_submit_without_changes_blocks_later_writes_and_preserves_case_reads(case_domain, monkeypatch):
    domain, author, context = case_domain
    writer = object()
    monkeypatch.setattr(domain, "_case_writer", lambda _: writer)
    case = domain.case_pool.claim_random(author)
    assert domain._resolve_case(author, case["case_id"]) == (writer, author)
    result = json.loads(context.program.tools["submit_case"].invoke({"case_id": case["case_id"]}))
    assert result["status"] == "submitted"
    with pytest.raises(ValueError, match="已经 submit"):
        domain._resolve_case(author, case["case_id"])
    assert domain.case_pool.claim(case["case_id"], author)["status"] == "submitted"
    rows = json.loads(context.program.tools["search_cases"].invoke({}))
    assert any(row["case_id"] == case["case_id"] and row["submitted"] for row in rows)


@pytest.mark.parametrize("already_submitted", [False, True])
@pytest.mark.parametrize("signal", ["finish", "text"])
async def test_end_signals_refused_before_any_claim_accepted_after_submission(
    case_domain, already_submitted, signal
):
    domain, author, context = case_domain
    if already_submitted:
        case = domain.case_pool.claim_random(author)
        domain.case_pool.submit(case["case_id"], author)
    pending = domain.case_counts()[0]
    first = AIMessage(content="完成") if signal == "text" else AIMessage(content="", tool_calls=[call("finish")])
    code = "\n".join([
        'case = claim_random_case()\nsubmit_case(case_id=case["case_id"])'
    ] * pending) + "\nfinish()"
    model = Replies([first, AIMessage(content="", tool_calls=[call("execute_code", {"code": code})])])
    ledger = AnnotationToolLedger(
        run_scope=domain.run_id, current_chapter_id=0, current_chapter_text="", allow_future_context=False,
    )
    graph = build_agent_graph(
        model, context.program.build_tool(), bind_finish_ledger(context.program.tools["finish"], ledger),
        ledger=ledger, agent=AgentAnnotation(role="case"), max_iterations=context.max_rounds,
        completion_check=context.completion_check,
    )
    result = await run_graph(graph)
    assert result["completion_ok"] and len(model.requests) == (1 if already_submitted else 2)
    if already_submitted:
        assert domain.case_counts() == (pending, 1)
    else:
        assert any("仍有可领案例" in str(message.content) for message in model.requests[1])
        assert domain.case_counts() == (0, 3)
    assert context.unsubmitted_count() == 0


def test_annotation_finish_keeps_existing_validation_when_cases_are_unsubmitted():
    run_id = new_id()
    ledger = AnnotationToolLedger(
        run_scope=run_id, current_chapter_id=1, current_chapter_text="原文", allow_future_context=False,
        graph=FactGraph(run_scope=run_id), role="entity",
    )
    agent, execution, query = _work_tools_context(SimpleNamespace(), ledger)
    tools = {tool.name: tool for tool in build_work_tools(agent, execution, query)}
    original = execution.validate()
    assert original == []
    for index in range(2):
        case = agent.case_pool.push("event", f"待核查{index}", execution.invocation_id)
        tools["claim_case"].invoke({"case_id": case["case_id"]})
    assert len(agent.case_pool.unsubmitted_for(execution.invocation_id)) == 2
    assert execution.validate() == original
    tools["finish"].invoke({})
    assert execution.end_requested and execution.validate() == original
