"""案例持有、提交与同会话结束条件的无数据库验证"""

import json
import threading
from types import SimpleNamespace

import pytest

from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.shared_tools import build_case_tools, build_finish_tool
from src.agents.annotation.work_tools import build_work_tools
from src.agents.diagnosis import domain as domain_module
from src.agents.diagnosis.session_loop import build_diagnosis_loop
from src.agents.messages import AssistantMessage
from src.case_pool.policy import CASE_SESSION_CLAIM_BATCH
from src.fact_graph.graph import FactGraph
from src.storage import new_id
from tests.agents.test_diagnosis_agent import Replies, call, run_graph
from tests.support.annotation_work_tools import _work_tools_context


@pytest.fixture
def case_domain(monkeypatch):
    draft = SimpleNamespace(
        lock=threading.RLock(),
        publication_lock=threading.RLock(),
        queue_graph=lambda **_kwargs: SimpleNamespace(),
    )
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
        run_id=new_id(),
        novel_id=new_id(),
        agent_id=new_id(),
        novel_title=None,
        model_id="test",
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
    assert domain.case_counts()[0] > 0


def test_case_session_needs_no_minimum_submissions(case_domain):
    domain, author, context = case_domain
    for index in range(20):
        domain.case_pool.push("event", f"批量核查{index}", author)
    first = domain.case_pool.claim_random(author)["case_id"]
    domain.case_pool.submit(first, author)
    assert len(domain.case_pool.submissions_for(author)) == 1
    assert domain.case_counts()[0] > 0
    assert context.completion_check() == []


def test_case_session_claims_initial_batch(case_domain):
    domain, owner, _ = case_domain
    for index in range(20):
        domain.case_pool.push("event", f"预领取核查{index}", owner)
    author = new_id()
    context = domain.build_session_context("case", author, None)
    assert context.claimed_count() == CASE_SESSION_CLAIM_BATCH
    for case_id in domain.case_pool.claims_for(author):
        domain.case_pool.submit(case_id, author)
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


@pytest.mark.parametrize("signal", ["finish", "text"])
async def test_end_signal_allowed_while_pool_still_has_cases(case_domain, signal):
    domain, author, context = case_domain
    first = (
        AssistantMessage(content="完成")
        if signal == "text"
        else AssistantMessage(content="", tool_calls=[call("finish")])
    )
    model = Replies([first])
    graph = build_diagnosis_loop(
        model,
        context.program,
        max_iterations=context.max_rounds,
        completion_check=context.completion_check,
    )
    result = await run_graph(graph)
    assert result["completion_ok"] and len(model.requests) == 1
    assert domain.case_counts()[0] > 0
    assert context.unsubmitted_count() == 0


async def test_unsubmitted_claim_blocks_end_signal(case_domain):
    domain, author, context = case_domain
    case = domain.case_pool.claim_random(author)
    code = f'submit_case(case_id="{case["case_id"]}")\nfinish()'
    model = Replies(
        [
            AssistantMessage(content="", tool_calls=[call("finish")]),
            AssistantMessage(content="", tool_calls=[call("execute_code", {"code": code})]),
        ]
    )
    graph = build_diagnosis_loop(
        model,
        context.program,
        max_iterations=context.max_rounds,
        completion_check=context.completion_check,
    )
    result = await run_graph(graph)
    assert result["completion_ok"] and len(model.requests) == 2
    assert any("仍有未提交案例" in str(message.content) for message in model.requests[1])
    assert context.unsubmitted_count() == 0


def test_annotation_finish_keeps_existing_validation_when_cases_are_unsubmitted():
    run_id = new_id()
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=1,
        current_chapter_text="原文",
        allow_future_context=False,
        graph=FactGraph(run_scope=run_id),
        role="entity",
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
