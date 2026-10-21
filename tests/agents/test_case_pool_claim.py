"案例领取的进程共享、原子性与作者隔离"

import gc
import json
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.agents.annotation.shared_tools import build_case_tools
from src.case_pool import CasePool
from src.storage import new_id


def test_threads_claim_each_case_once_across_pool_instances():
    run_id = new_id()
    pool = CasePool(run_id)
    pool.begin("producer")
    expected = {pool.push("event", f"检查事件{i}", "producer")["case_id"] for i in range(80)}
    barrier = threading.Barrier(8)

    def consume(index):
        local = CasePool(run_id)
        author = str(index)
        local.begin(author)
        barrier.wait()
        claimed = []
        while (case := local.claim_random(author))["status"] == "claimed":
            claimed.append(case["case_id"])
            local.submit(case["case_id"], author)
        return claimed

    with ThreadPoolExecutor(max_workers=8) as executor:
        claimed = [key for batch in executor.map(consume, range(8)) for key in batch]
    assert len(claimed) == len(set(claimed)) == 80
    assert set(claimed) == expected
    assert pool.counts() == (0, 80)
    assert CasePool(new_id()).counts() == (0, 0)


def test_explicit_promise_has_one_owner_and_same_owner_is_idempotent():
    pool = CasePool(new_id())
    pool.begin("producer")
    key = pool.push("relation", "检查人物关系", "producer")["case_id"]
    barrier = threading.Barrier(8)

    def promise(index):
        author = str(index)
        local = CasePool(pool.run_id)
        local.begin(author)
        barrier.wait()
        return author, local.claim(key, author)["status"]

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(promise, range(8)))
    winners = [author for author, status in results if status == "claimed"]
    assert len(winners) == 1
    assert pool.claim(key, winners[0])["status"] == "claimed"
    assert pool.submissions_for(winners[0]) == []
    assert pool.submit(key, winners[0])["status"] == "submitted"
    assert pool.submit(key, winners[0])["status"] == "submitted"
    assert pool.submissions_for(winners[0]) == [key]


def test_restore_and_reload_preserve_other_authors_claims():
    pool = CasePool(new_id())
    pool.begin("a")
    key = pool.push("event", "核对事件", "a")["case_id"]
    snapshot = pool.snapshot("a")
    pool.begin("b")
    pool.claim(key, "b")
    pool.submit(key, "b")
    other = pool.push("character", "核对人物", "b")["case_id"]
    pool.claim(other, "b")
    pool.push("dialogue", "撤销本次登记", "a")
    pool.restore(snapshot)
    row = SimpleNamespace(id=key, type="event", description="核对事件", status="pending", promised_agent_id=None)
    pool.load_storage(SimpleNamespace(cases=SimpleNamespace(rows=lambda _: [row])))
    assert pool.claims_for("b") == sorted([key, other])
    assert len(pool.search()) == 2
    pool.abandon("a")
    assert pool.claims_for("b") == sorted([key, other])


def test_failed_owner_releases_promises_but_keeps_registrations():
    pool = CasePool(new_id())
    pool.begin("a")
    key = pool.push("event", "核对事件", "a")["case_id"]
    pool.claim(key, "a")
    pool.abandon("a")
    assert pool.contribution("a")["registrations"][key]["description"] == "核对事件"
    pool.begin("b")
    assert pool.claim_random("b")["case_id"] == key
    pool.submit(key, "b")
    pool.confirm("b")
    pool.abandon("b")
    assert pool.submissions_for("b") == [key]


def test_case_tools_claim_without_arguments_and_do_not_repeat_claim_callback():
    pool = CasePool(new_id())
    pool.begin("a")
    pool.push("event", "核对事件", "a")
    callback = Mock()
    tools = {tool.name: tool for tool in build_case_tools(pool, "a", on_claim=callback)}
    assert not tools["claim_random_case"].args_schema.model_fields
    case = json.loads(tools["claim_random_case"].invoke({}))
    assert json.loads(tools["claim_case"].invoke({"case_id": case["case_id"]}))["status"] == "claimed"
    assert json.loads(tools["claim_random_case"].invoke({}))["case_id"] == case["case_id"]
    assert set(tools["claim_case"].args_schema.model_fields) == {"case_id"}
    assert set(tools["submit_case"].args_schema.model_fields) == {"case_id"}
    tools["submit_case"].invoke({"case_id": case["case_id"]})
    assert json.loads(tools["claim_random_case"].invoke({})) == {"status": "empty"}
    callback.assert_called_once()


def test_submit_candidates_are_bounded_copies_and_do_not_reserve_cases():
    pool = CasePool(new_id())
    pool.begin("a")
    pool.begin("b")
    keys = {pool.push("event", f"核对{i}", "a")["case_id"] for i in range(8)}
    claimed = pool.claim_random("a")["case_id"]
    occupied = pool.claim_random("b")["case_id"]
    before = pool.counts()[0]
    result = pool.submit(claimed, "a")
    assert len(result["candidates"]) == 3
    assert pool.counts()[0] == before
    offered = {row["case_id"] for row in result["candidates"]}
    assert len(offered) == 3 and offered <= keys - {claimed, occupied}
    assert all(set(row) == {"case_id", "case_type", "description"} for row in result["candidates"])
    result["candidates"][0]["description"] = "不能改写案例"
    assert all(row["description"] != "不能改写案例" for row in pool.search())
    pool.submit(occupied, "b")
    target = next(iter(offered))
    assert pool.claim(target, "b")["status"] == "claimed"
    assert pool.claim(target, "a")["status"] == "taken"
    assert pool.claim_random("a")["case_id"] != target


def test_unsubmitted_claim_requires_submission_and_is_not_frozen_as_completed():
    pool = CasePool(new_id())
    pool.begin("a")
    pool.begin("b")
    first = pool.push("event", "第一件", "a")["case_id"]
    second = pool.push("event", "第二件", "a")["case_id"]
    pool.claim(first, "a")
    with pytest.raises(ValueError, match="先 submit_case"):
        pool.claim(second, "a")
    with pytest.raises(ValueError, match="只能提交"):
        pool.submit(first, "b")
    assert pool.contribution("a")["submissions"] == []
    pool.confirm("a")
    assert pool.counts() == (2, 0)
    assert pool.claim(first, "b")["status"] == "claimed"


def test_registry_does_not_retain_finished_run_objects():
    pool = CasePool(new_id())
    reference = weakref.ref(pool)
    del pool
    gc.collect()
    assert reference() is None
