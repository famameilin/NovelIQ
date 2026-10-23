"案例领取、结束检查与正式保存的集成行为"

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from langchain_core.messages import AIMessage

from src.agents.annotation.agent_graph import build_agent_graph
from src.agents.annotation.agent_ir import AgentAnnotation
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.diagnosis.domain import DiagnosisDomain
from src.agents.diagnosis.program_runtime import bind_finish_ledger
from src.storage import new_id
from src.storage.models import Agent, Case
from tests.agents.test_complete_event_invariants import draft_case as draft_case
from tests.agents.test_diagnosis_agent import Replies, call, run_graph
from tests.support.storage_fixtures import storage_for


def domain_for(draft):
    author = new_id()
    draft.fixture_session.add(Agent(id=author, run_id=draft.run_id, type="case", status="running"))
    draft.fixture_session.commit()
    domain = DiagnosisDomain(
        session=storage_for(draft.fixture_session), run_id=draft.run_id, novel_id=new_id(),
        agent_id=author, novel_title=None, model_id="test",
    )
    return domain, author


def test_case_completion_blocks_unsubmitted_claims_and_report_cannot_start_early(draft_case):
    domain, author = domain_for(draft_case)
    context = domain.build_session_context("case", author, None)
    assert context.completion_check()
    with pytest.raises(ValueError, match="待领案例"):
        domain.build_session_context("report", new_id(), None)
    claimed = []
    while (case := json.loads(context.program.tools["claim_random_case"].invoke({})))["status"] == "claimed":
        claimed.append(case["case_id"])
        assert context.completion_check()
        context.program.tools["submit_case"].invoke({"case_id": case["case_id"]})
    assert context.completion_check() == []
    assert context.claimed_count() == len(claimed) > 0
    context.program.tools["claim_case"].invoke({"case_id": claimed[0]})
    assert context.claimed_count() == len(claimed)
    with pytest.raises(ValueError, match="尚未全部保存"):
        domain.build_session_context("report", new_id(), None)


def test_aborted_attempt_releases_own_case_without_blocking_later_report(draft_case):
    domain, author = domain_for(draft_case)
    failed = domain.build_session_context("case", author, None)
    case = json.loads(failed.program.tools["claim_random_case"].invoke({}))
    failed.program.tools["write_entity"].invoke({
        "name": "失败尝试人物", "entity_type": "character", "el": "failed", "caseid": case["case_id"],
    })
    assert author in domain.case_writers
    domain.abort_session(author)
    assert author not in domain.case_writers
    assert domain.case_pool.case_runtime[case["case_id"]]["owner"] is None

    replacement = new_id()
    draft_case.fixture_session.add(Agent(id=replacement, run_id=domain.run_id, type="case", status="running"))
    draft_case.fixture_session.commit()
    context = domain.build_session_context("case", replacement, None)
    while (claimed := json.loads(context.program.tools["claim_random_case"].invoke({})))["status"] == "claimed":
        context.program.tools["submit_case"].invoke({"case_id": claimed["case_id"]})
    domain.save_session_progress(replacement, "case")
    assert domain.case_counts()[0] == 0
    domain.build_session_context("report", new_id(), None)


def test_claim_does_not_wait_for_draft_or_publication_lock(draft_case):
    domain, author = domain_for(draft_case)
    context = domain.build_session_context("case", author, None)
    entered, release = threading.Event(), threading.Event()

    def slow_read():
        with domain.draft.publication_lock, domain.lock:
            entered.set()
            assert release.wait(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        reading = executor.submit(slow_read)
        assert entered.wait(1)
        try:
            claiming = executor.submit(context.program.tools["claim_random_case"].invoke, {})
            assert json.loads(claiming.result(timeout=1))["status"] == "claimed"
        finally:
            release.set()
        reading.result(timeout=1)


def test_formal_save_refreshes_event_and_graph_reads(draft_case):
    domain, author = domain_for(draft_case)
    context = domain.build_session_context("case", author, None)
    domain.draft.read_view()
    assert domain.draft._stored_view is not None
    source = domain.graph_sources[0]
    assert "顾霜" not in source.entity_names.values()
    boundary = domain.session.graph.resolve_persisted_boundary(domain.run_id)
    historical = {row.entity_id for row in domain.session.graph.fetch_entity_snapshots(boundary)}
    case = domain.case_pool.push("character", "核对顾霜的身份", author)
    domain.case_pool.claim(case["case_id"], author)
    for name in ("顾霜", "林渡"):
        receipt = json.loads(context.program.tools["write_entity"].invoke({
            "name": name, "entity_type": "character", "el": name,
            "description": "同行的寻路者", "caseid": case["case_id"],
        }))
        assert receipt["status"] == "written"
    context.program.tools["write_relation"].invoke({
        "from_entity": {"name": "顾霜", "entity_type": "character"},
        "to_entity": {"name": "林渡", "entity_type": "character"},
        "relation_type": "盟友", "caseid": case["case_id"],
    })
    context.program.tools["submit_case"].invoke({"case_id": case["case_id"]})
    with pytest.raises(ValueError, match="已经 submit"):
        domain._resolve_case(author, case["case_id"])
    domain.save_session_progress(author, "case")
    assert domain.draft._stored_view is None
    assert source._view is None
    assert author in domain.session_saved
    assert "顾霜" in source.entity_names.values()
    assert len(source.active_relations) == 1
    assert all(row["attributes"]["description"] == "同行的寻路者" for row in source.entity_attributes.values())
    assert {row.entity_id for row in domain.session.graph.fetch_entity_snapshots(boundary)} == historical


def test_save_keeps_valid_outputs_but_releases_unsubmitted_case(draft_case):
    domain, author = domain_for(draft_case)
    context = domain.build_session_context("case", author, None)
    case = domain.case_pool.push("character", "核对顾霜", author)
    domain.case_pool.claim(case["case_id"], author)
    context.program.tools["write_entity"].invoke({
        "name": "顾霜", "entity_type": "character", "el": "顾霜", "caseid": case["case_id"],
    })
    assert context.unsubmitted_count() == 1
    domain.save_session_progress(author, "case")
    draft_case.fixture_session.expire_all()
    row = draft_case.fixture_session.get(Case, case["case_id"])
    assert row.status == "pending" and row.promised_agent_id is None
    assert domain.case_pool.case_runtime[case["case_id"]]["owner"] is None
    assert "顾霜" in domain.graph_sources[0].entity_names.values()


@pytest.mark.parametrize("candidate_taken", [False, True])
async def test_candidates_support_next_normal_turn_and_taken_falls_back(draft_case, candidate_taken):
    domain, author = domain_for(draft_case)
    context = domain.build_session_context("case", author, None)
    pending = domain.case_counts()[0]
    first_code = 'case = claim_random_case()\nsubmitted = submit_case(case_id=case["case_id"])'
    second_code = (
        'chosen = claim_case(case_id=submitted["candidates"][0]["case_id"])\n'
        'if chosen["status"] == "taken":\n'
        '    chosen = claim_random_case()\n'
        'if chosen["status"] == "claimed":\n'
        '    submit_case(case_id=chosen["case_id"])\n'
        'for i in range(10):\n'
        '    remaining = claim_random_case()\n'
        '    if remaining["status"] == "claimed":\n'
        '        submit_case(case_id=remaining["case_id"])\n'
        'finish()'
    )

    class CandidateReplies(Replies):
        async def ainvoke(self, messages):
            if self.requests:
                assert any('"candidates"' in str(message.content) for message in messages)
                if candidate_taken:
                    other = new_id()
                    domain.case_pool.begin(other)
                    target = context.program.env["submitted"]["candidates"][0]["case_id"]
                    domain.case_pool.claim(target, other)
                    domain.case_pool.submit(target, other)
            return await super().ainvoke(messages)

    model = CandidateReplies([
        AIMessage(content="", tool_calls=[call("execute_code", {"code": code})])
        for code in (first_code, second_code)
    ])
    ledger = AnnotationToolLedger(
        run_scope=domain.run_id, current_chapter_id=0, current_chapter_text="", allow_future_context=False,
    )
    graph = build_agent_graph(
        model, context.program.build_tool(), bind_finish_ledger(context.program.tools["finish"], ledger),
        ledger=ledger, agent=AgentAnnotation(role="case"), max_iterations=context.max_rounds,
        completion_check=context.completion_check,
    )
    result = await run_graph(graph)
    assert result["completion_ok"] and len(model.requests) == 2
    assert domain.case_counts() == (0, pending)
    assert context.unsubmitted_count() == 0
    assert not any(op["tool_name"] == "search_cases" for op in context.program.ops)


@pytest.mark.parametrize("first", [AIMessage(content="完成"), AIMessage(content="", tool_calls=[call("finish")])])
async def test_early_end_before_any_claim_is_rejected_while_cases_remain(draft_case, first):
    domain, author = domain_for(draft_case)
    context = domain.build_session_context("case", author, None)
    pending = domain.case_counts()[0]
    code = "\n".join(['case = claim_random_case()\nsubmit_case(case_id=case["case_id"])'] * pending)
    code += "\nclaim_random_case()\nfinish()"
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
    assert result["completion_ok"] and len(model.requests) == 2
    assert context.claimed_count() == pending
    assert any("仍有可领案例" in str(message.content) for message in model.requests[1])


def test_case_session_may_end_after_its_claims_are_submitted(draft_case):
    domain, author = domain_for(draft_case)
    context = domain.build_session_context("case", author, None)
    domain.case_pool.push("character", "核对顾霜的身份", author)
    assert context.completion_check()
    claimed = json.loads(context.program.tools["claim_random_case"].invoke({}))
    assert claimed["status"] == "claimed"
    assert context.completion_check()
    context.program.tools["submit_case"].invoke({"case_id": claimed["case_id"]})
    assert domain.case_counts()[0] > 0
    assert context.completion_check() == []
