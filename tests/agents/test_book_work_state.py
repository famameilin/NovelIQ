"""全书共享域与消息隔离的并发不变量"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.fact_graph.schema import EntityInput
from src.event_trees.models import BoundEvent
from src.agents.annotation.work import annotation_work_id, completed_chapters, required_roles
from src.case_pool import CasePool
from src.event_bus import EventBus, Message, MissingSubscriber
from src.event_trees.trees import EventTrees
from src.fact_graph.graph import FactGraph


def node(description: str = "事件") -> BoundEvent:
    return BoundEvent(
        node_id="node",
        tree_id="tree",
        parent_node_id=None,
        cause_role="root",
        description=description,
        evidence_paragraph_id=1,
    )


@pytest.mark.asyncio
async def test_message_request_deduplicates_and_isolates_work() -> None:
    bus = EventBus()
    calls = []

    async def receiver(message):
        calls.append(message.work_id)
        return message.work_id

    bus.handle("save", "agent", receiver)
    a = Message("save", "queue", "agent", "run", "a", "invocation", request_id="same")
    b = Message("save", "queue", "agent", "run", "b", "invocation", request_id="same")
    assert await bus.request(a) == "a"
    assert await bus.request(a) == "a"
    assert await bus.request(b) == "b"
    assert calls == ["a", "b"]
    with pytest.raises(MissingSubscriber):
        await bus.request(Message("missing", "queue", "agent", "run"))


def test_work_identity_and_incomplete_lane_group() -> None:
    assert required_roles("一二", 2) == ("solo",)
    assert required_roles("一二三", 2) == ("structure", "event", "evidence")
    assert annotation_work_id("r", 1, "event") == annotation_work_id("r", 1, "event")
    records = [
        SimpleNamespace(chapter_id=1, role="structure", state="saved"),
        SimpleNamespace(chapter_id=1, role="event", state="saved"),
    ]
    assert completed_chapters(records) == set()
    records.append(SimpleNamespace(chapter_id=1, role="evidence", state="completed"))
    assert completed_chapters(records) == set()
    records[-1].state = "saved"
    assert completed_chapters(records) == {1}


def test_fact_rollback_preserves_other_work_and_cross_chapter_entity_id() -> None:
    graph = FactGraph(run_scope="run")
    entity = EntityInput(name=" 张三 ", entity_type="character")
    graph.begin("a", "a1", 1, "structure")
    graph.begin("b", "b1", 2, "structure")
    with graph.author("a", "a1"):
        graph.register_entities([entity])
        graph.record_entity_ops([entity], chapter_id=1)
    identifier = graph.entity_id("张三")
    with graph.author("b", "b1"):
        graph.register_entities([entity])
        graph.record_entity_ops([entity], chapter_id=2)
    graph.confirm("b", "b1")
    graph.rollback("a", "a1")
    assert graph.entity_id("张三") == identifier
    assert graph.drain_ops("b", "b1")["entity_ops"][0]["chapter_id"] == 2


def test_old_node_read_rejected_after_same_id_rebuilt() -> None:
    trees = EventTrees("run")
    trees.begin("a", "a1")
    trees.sync(("a", "a1"), 1, [node()])
    stale = trees.read("node")
    trees.rollback("a", "a1")
    trees.begin("a", "a2")
    trees.sync(("a", "a2"), 1, [node()])
    trees.confirm("a", "a2")
    trees.begin("b", "b1")
    child = node("子事件").model_copy(update={"node_id": "child", "tree_id": "child_tree"})
    trees.sync(("b", "b1"), 2, [child])
    reads = {"node": stale, "child": trees.read("child")}
    with pytest.raises(ValueError, match="读取生产者=a1 当前生产者=a2"):
        trees.connect(("b", "b1"), "child", "node", "main", reads, {1})
    reads["node"] = trees.read("node")
    trees.connect(("b", "b1"), "child", "node", "main", reads, {1})
    assert trees.read("child")["content"]["tree_id"] == "tree"


def test_changed_content_and_unsaved_foreign_endpoints_rejected() -> None:
    trees = EventTrees("run")
    trees.begin("a", "a1")
    trees.sync(("a", "a1"), 1, [node()])
    read = trees.read("node")
    trees.sync(("a", "a1"), 1, [node().model_copy(update={"is_foreshadow_setup": True})])
    trees.begin("b", "b1")
    child = node().model_copy(update={"node_id": "child"})
    trees.sync(("b", "b1"), 2, [child])
    reads = {"node": read, "child": trees.read("child")}
    with pytest.raises(ValueError, match="内容已变化"):
        trees.connect(("b", "b1"), "child", "node", "main", reads, {1})
    reads["node"] = trees.read("node")
    with pytest.raises(ValueError, match="未成功保存"):
        trees.connect(("b", "b1"), "child", "node", "main", reads, {1})


def test_case_exclusion_lasts_until_own_work_confirmed() -> None:
    pool = CasePool("run")
    a, b = ("a", "a1"), ("b", "b1")
    pool.begin(*a)
    pool.begin(*b)
    case = pool.push("核查关联", a)
    assert set(case) == {"case_id", "description"}
    pool.push("核查关联", b)
    assert pool.promise(case["case_id"], a)["status"] == "claimed"
    assert pool.promise(case["case_id"], b)["status"] == "busy"
    pool.deliver(
        {"case_id": case["case_id"], "state": "resolved", "reason": "原文已核查，无需连接"},
        a,
        call_id="finish",
        connections=[],
        reads=[{"actual": "read"}],
    )
    assert pool.promise(case["case_id"], b)["status"] == "busy"
    pool.confirm(*a)
    assert pool.promise(case["case_id"], b)["status"] == "resolved"
    pool.rollback(*b)
    assert pool.search()[0]["state"] == "resolved"


def test_role_finish_never_fills_metrics_or_skips_dialogue_candidates():
    from src.agents.annotation.agent import WorkExecution
    from src.agents.annotation.ledger import AnnotationToolLedger
    from src.fact_graph.schema import ChapterMetricsInput
    from src.agents.annotation.subagent_ir import SubagentAnnotation
    from src.agents.annotation.work import WorkReceipt

    for role in ("structure", "event", "solo", "evidence"):
        ledger = AnnotationToolLedger(
            run_scope="r",
            current_chapter_id=1,
            current_chapter_text="张三说：“走吧。”",
            allow_future_context=False,
            graph=FactGraph(run_scope="r"),
            role=role,
        )
        execution = WorkExecution(WorkReceipt(role, "r", "annotation", {}), "i", ledger, SubagentAnnotation(role=role))
        if role in {"structure", "event"}:
            execution.validate()
            assert execution.output()["metrics"] is None
        else:
            with pytest.raises(ValueError, match="metrics=None"):
                execution.validate()
            ledger.apply_metrics(ChapterMetricsInput(summary="出发", emotional_valence=0, narrative_function="铺垫"))
            with pytest.raises(ValueError, match="未判候选"):
                execution.validate()


def test_duplicate_node_conflict_does_not_overwrite_original_content():
    trees = EventTrees("run")
    trees.begin("a", "a1")
    trees.sync(("a", "a1"), 1, [node()])
    with pytest.raises(ValueError, match="业务内容冲突"):
        trees.sync(("a", "a1"), 1, [node("改写")])
    assert trees.read("node")["content"]["description"] == "事件"
