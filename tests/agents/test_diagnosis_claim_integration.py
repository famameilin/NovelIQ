"案例领取、结束检查与正式保存的集成行为"

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.agents.diagnosis.domain import DiagnosisDomain
from src.agents.diagnosis.session_loop import build_diagnosis_loop
from src.agents.messages import AssistantMessage
from src.case_pool.policy import CASE_SESSION_CLAIM_BATCH
from src.event_trees.organization_models import OrganizationEvidence
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
        session=storage_for(draft.fixture_session),
        run_id=draft.run_id,
        novel_id=new_id(),
        agent_id=author,
        novel_title=None,
        model_id="test",
    )
    return domain, author


def _parent_event_cases(draft, author: str) -> None:
    """事件案例必须归并到父树后才可提交"""
    draft.producer_agent_id = author
    parent = draft.queue(event_ids=[], tree_key=f"case-parent-{author}", title="案例父树")
    for tree_id in list(draft.queue_graph(producers={author}).unparented):
        if tree_id == parent:
            continue
        draft.reference(
            parent_tree_id=parent,
            child_tree_id=tree_id,
            reason="事件案例归并到同一父树",
            evidence=[OrganizationEvidence(paragraph_id=0)],
        )


def test_case_completion_blocks_unsubmitted_claims_and_report_cannot_start_early(draft_case):
    domain, author = domain_for(draft_case)
    context = domain.build_session_context("case", author, None)
    _parent_event_cases(domain.draft, author)
    assert context.completion_check()
    with pytest.raises(ValueError, match="待领案例"):
        domain.build_session_context("report", new_id(), None)
    claimed = list(domain.case_pool.claims_for(author))
    while (case := json.loads(context.program.tools["claim_random_case"].invoke({})))["status"] == "claimed":
        claimed.append(case["case_id"])
        assert context.completion_check()
        context.program.tools["submit_case"].invoke({"case_id": case["case_id"]})
    for case_id in domain.case_pool.claims_for(author):
        context.program.tools["submit_case"].invoke({"case_id": case_id})
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
    failed.program.tools["write_entity"].invoke(
        {
            "name": "失败尝试人物",
            "entity_type": "character",
            "el": "failed",
            "caseid": case["case_id"],
        }
    )
    assert author in domain.case_writers
    domain.abort_session(author)
    assert author not in domain.case_writers
    assert domain.case_pool.case_runtime[case["case_id"]]["owner"] is None

    replacement = new_id()
    draft_case.fixture_session.add(Agent(id=replacement, run_id=domain.run_id, type="case", status="running"))
    draft_case.fixture_session.commit()

    def drain(context) -> None:
        for case_id in domain.case_pool.claims_for(replacement):
            context.program.tools["submit_case"].invoke({"case_id": case_id})
        while (claimed := json.loads(context.program.tools["claim_random_case"].invoke({})))["status"] == "claimed":
            context.program.tools["submit_case"].invoke({"case_id": claimed["case_id"]})

    context = domain.build_session_context("case", replacement, None)
    drain(context)
    domain.save_session_progress(replacement, "case")
    # 办结后仍未归并的树补登一次
    assert domain.case_counts()[0] > 0
    drain(domain.build_session_context("case", replacement, None))
    domain.save_session_progress(replacement, "case")
    assert domain.case_counts()[0] == 0
    domain.build_session_context("report", new_id(), None)


def test_report_stage_connects_remaining_roots_under_book_line(draft_case):
    domain, author = domain_for(draft_case)
    domain.case_pool.begin(author)
    for case in domain.case_pool.search():
        domain.case_pool.claim(case["case_id"], author)
        domain.case_pool.submit(case["case_id"], author)
    domain.session_saved.add(author)
    domain.build_session_context("report", author, None)
    book_lines = [queue for queue in domain.draft.queues.values() if queue.tree_key == "book-line"]
    assert len(book_lines) == 1
    assert set(domain.draft.queue_graph(require_complete=True).unparented) == {book_lines[0].tree_id}


def test_report_stage_reuses_covering_root_instead_of_new_book_line(draft_case):
    domain, author = domain_for(draft_case)
    draft = domain.draft
    draft.producer_agent_id = author
    extra = []
    for index in range(5):
        created = draft.event(
            key=f"extra-{index}",
            title=f"额外事件{index}",
            problem="待解决",
            summary="额外事件",
            event_type="探寻",
            status="ongoing",
            reason="原文中的整体行动",
            from_chapter_id=1,
            to_chapter_id=1,
            evidence=[OrganizationEvidence(paragraph_id=0)],
        )
        extra.append(
            draft.queue(
                event_ids=[created["event_id"]],
                reason="独立行动",
                evidence=[OrganizationEvidence(paragraph_id=0)],
            )
        )
    covering = draft.queue(event_ids=[], tree_key="covering", title="全书覆盖树")
    outside = extra[0]
    for tree_id in list(draft.queue_graph().unparented):
        if tree_id not in (covering, outside):
            draft.reference(
                parent_tree_id=covering,
                child_tree_id=tree_id,
                reason="案例归并到覆盖全书的根树",
                evidence=[],
            )
    domain.case_pool.begin(author)
    for case in domain.case_pool.search():
        domain.case_pool.claim(case["case_id"], author)
        domain.case_pool.submit(case["case_id"], author)
    domain.session_saved.add(author)
    domain.build_session_context("report", author, None)
    graph = draft.queue_graph(require_complete=True)
    assert not [queue for queue in draft.queues.values() if queue.tree_key == "book-line"]
    assert set(graph.unparented) == {covering}
    assert outside in graph.children[covering]


def test_report_stage_selects_event_lines_by_maximum_coverage(draft_case):
    domain, author = domain_for(draft_case)
    draft = domain.draft
    draft.producer_agent_id = author
    for index, quote in enumerate(("顾", "霜", "寻", "找", "山", "门", "点", "燃", "灯")):
        created = draft.event(
            key=f"dp-{index}",
            title=f"分段事件{index}",
            problem="待解决",
            summary="分段事件",
            event_type="探寻",
            status="ongoing",
            reason="原文中的整体行动",
            from_chapter_id=1,
            to_chapter_id=1,
            evidence=[OrganizationEvidence(paragraph_id=0, quote=quote)],
        )
        draft.queue(
            event_ids=[created["event_id"]],
            reason="独立行动",
            evidence=[OrganizationEvidence(paragraph_id=0, quote=quote)],
        )
    domain.case_pool.begin(author)
    for case in domain.case_pool.search():
        domain.case_pool.claim(case["case_id"], author)
        domain.case_pool.submit(case["case_id"], author)
    domain.session_saved.add(author)
    domain.build_session_context("report", author, None)
    graph = draft.queue_graph(require_complete=True)
    assert len(draft.event_line_ids) == 10
    covered = set().union(*(graph.tree_events(tree_id) for tree_id in draft.event_line_ids))
    assert len(covered) == 10
    sizes = [len(graph.tree_events(tree_id)) for tree_id in draft.event_line_ids]
    assert sum(sizes) == len(covered)


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
        receipt = json.loads(
            context.program.tools["write_entity"].invoke(
                {
                    "name": name,
                    "entity_type": "character",
                    "el": name,
                    "description": "同行的寻路者",
                    "caseid": case["case_id"],
                }
            )
        )
        assert receipt["status"] == "written"
    context.program.tools["write_relation"].invoke(
        {
            "from_entity": {"name": "顾霜", "entity_type": "character"},
            "to_entity": {"name": "林渡", "entity_type": "character"},
            "relation_type": "盟友",
            "caseid": case["case_id"],
        }
    )
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
    for case_id in domain.case_pool.claims_for(author):
        domain.case_pool.submit(case_id, author)
    case = domain.case_pool.push("character", "核对顾霜", author)
    domain.case_pool.claim(case["case_id"], author)
    context.program.tools["write_entity"].invoke(
        {
            "name": "顾霜",
            "entity_type": "character",
            "el": "顾霜",
            "caseid": case["case_id"],
        }
    )
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
    for case_id in domain.case_pool.claims_for(author):
        domain.case_pool.submit(case_id, author)
    _parent_event_cases(domain.draft, author)
    for index in range(3):
        domain.case_pool.push("character", f"核对同行者{index}", author)
    first_code = 'case = claim_random_case()\nsubmitted = submit_case(case_id=case["case_id"])'
    second_code = (
        'chosen = claim_case(case_id=submitted["candidates"][0]["case_id"])\n'
        'if chosen["status"] == "taken":\n'
        "    chosen = claim_random_case()\n"
        'if chosen["status"] == "claimed":\n'
        '    submit_case(case_id=chosen["case_id"])\n'
        "for i in range(10):\n"
        "    remaining = claim_random_case()\n"
        '    if remaining["status"] == "claimed":\n'
        '        submit_case(case_id=remaining["case_id"])\n'
        "finish()"
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

    model = CandidateReplies(
        [
            AssistantMessage(content="", tool_calls=[call("execute_code", {"code": code})])
            for code in (first_code, second_code)
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
    assert domain.case_counts()[0] == 0
    assert context.unsubmitted_count() == 0
    assert not any(op["tool_name"] == "search_cases" for op in context.program.ops)


@pytest.mark.parametrize(
    "first", [AssistantMessage(content="完成"), AssistantMessage(content="", tool_calls=[call("finish")])]
)
async def test_end_signal_accepted_before_pool_is_drained(draft_case, first):
    domain, author = domain_for(draft_case)
    context = domain.build_session_context("case", author, None)
    _parent_event_cases(domain.draft, author)
    if not domain.case_pool.claims_for(author):
        domain.case_pool.claim_random(author)
    claims = domain.case_pool.claims_for(author)
    assert claims
    pending = domain.case_counts()[0]
    code = "\n".join(f'submit_case(case_id="{case_id}")' for case_id in claims)
    code += "\nfinish()"
    model = Replies([first, AssistantMessage(content="", tool_calls=[call("execute_code", {"code": code})])])
    graph = build_diagnosis_loop(
        model,
        context.program,
        max_iterations=context.max_rounds,
        completion_check=context.completion_check,
    )
    result = await run_graph(graph)
    assert result["completion_ok"] and len(model.requests) == 2
    assert any("仍有未提交案例" in str(message.content) for message in model.requests[1])
    assert domain.case_counts()[0] == pending > 0
    assert context.unsubmitted_count() == 0


@pytest.mark.asyncio()
async def test_batch_read_then_batch_link_all_claimed_cases_within_turn_limit(draft_case):
    domain, author = domain_for(draft_case)
    context = domain.build_session_context("case", author, None)
    claimed = json.loads(context.program.tools["search_cases"].invoke({"claimed_only": True}))
    assert len(claimed) == CASE_SESSION_CLAIM_BATCH
    assert all(case["case_type"] == "event" for case in claimed)
    remaining = domain.case_counts()[0]
    read_code = (
        'cases = search_cases(claimed_only=True)\n'
        "for case in cases:\n"
        '    if case["case_type"] == "event":\n'
        '        page = search_events(tree_id=case["tree_id"], limit=20)\n'
        '        print(case["case_id"], len(page["events"]))\n'
    )
    write_code = (
        'cases = search_cases(claimed_only=True)\n'
        "parent = None\n"
        "for case in cases:\n"
        '    if case["case_type"] == "event":\n'
        '        parent = write_event(items=[], tree_key="case-parent", title="案例父树",\n'
        '                             caseid=case["case_id"])["tree_id"]\n'
        "        break\n"
        "for case in cases:\n"
        '    if case["case_type"] == "event":\n'
        '        write_link(items=[{"operation": "reference", "parent_tree_id": parent,\n'
        '                          "child_tree_id": case["tree_id"], "reason": "事件案例归并",\n'
        '                          "evidence": [{"paragraph_id": 0}]}], caseid=case["case_id"])\n'
        "for case in cases:\n"
        '    submit_case(case_id=case["case_id"])\n'
        "finish()"
    )
    model = Replies(
        [
            AssistantMessage(content="", tool_calls=[call("execute_code", {"code": read_code})]),
            AssistantMessage(content="", tool_calls=[call("execute_code", {"code": write_code})]),
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
    assert domain.case_counts() == (remaining, len(claimed))
    assert sum(op["tool_name"] == "search_events" for op in context.program.ops) == len(claimed)


def test_case_session_needs_no_minimum_submissions(draft_case):
    domain, author = domain_for(draft_case)
    context = domain.build_session_context("case", author, None)
    _parent_event_cases(domain.draft, author)
    domain.case_pool.push("character", "核对顾霜的身份", author)
    if not domain.case_pool.claims_for(author):
        domain.case_pool.claim_random(author)
    assert context.completion_check()
    for case_id in domain.case_pool.claims_for(author):
        context.program.tools["submit_case"].invoke({"case_id": case_id})
    assert domain.case_counts()[0] > 0
    assert context.completion_check() == []
