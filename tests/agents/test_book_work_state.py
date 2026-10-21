"""全书共享域与消息隔离的并发不变量"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.case_pool import CasePool
from src.event_bus import EventBus, Message, MissingSubscriber
from src.event_trees.models import BoundEvent
from src.event_trees.trees import EventTrees
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import EntityInput
from src.work.annotation_work import annotation_work_id, required_roles
from src.work.policy import completed_chapters
from tests.support.storage_fixtures import fixture_id


def node(description: str = "事件") -> BoundEvent:
    return BoundEvent(
        node_id="node",
        tree_id="tree",
        parent_node_id=None,
        cause_role="root",
        description=description,
        evidence_paragraph_id=1,
        title=description,
        problem="明确事件问题",
        summary=description,
        event_type="行动",
        status="ongoing",
        event_id="node",
        from_chapter_id=1,
        to_chapter_id=1,
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
    assert required_roles("一二", 2) == ("annotation",)
    assert required_roles("一二三", 2) == ("entity", "event", "metric")
    assert annotation_work_id(fixture_id(__name__, "r"), 1, "event") == annotation_work_id(
        fixture_id(__name__, "r"), 1, "event"
    )
    records = [
        SimpleNamespace(chapter_id=1, role="entity", state="saved"),
        SimpleNamespace(chapter_id=1, role="event", state="saved"),
    ]
    assert completed_chapters(records) == set()
    records.append(SimpleNamespace(chapter_id=1, role="metric", state="completed"))
    assert completed_chapters(records) == set()
    records[-1].state = "saved"
    assert completed_chapters(records) == {1}


def test_fact_rollback_preserves_other_execution_and_cross_chapter_entity_id() -> None:
    graph = FactGraph(run_scope="run")
    entity = EntityInput(name=" 张三 ", entity_type="character")
    graph.begin(fixture_id(__name__, "a1"), 1, "entity")
    graph.begin(fixture_id(__name__, "b1"), 2, "entity")
    with graph.author(fixture_id(__name__, "a1")):
        graph.register_entities([entity])
        graph.record_entity_ops([entity], chapter_id=1)
    identifier = graph.entity_id("张三", "character")
    with graph.author(fixture_id(__name__, "b1")):
        graph.register_entities([entity])
        graph.record_entity_ops([entity], chapter_id=2)
    graph.confirm(fixture_id(__name__, "b1"))
    graph.rollback(fixture_id(__name__, "a1"))
    assert graph.entity_id("张三", "character") == identifier
    assert graph.drain_ops(fixture_id(__name__, "b1"))["entity_ops"][0]["chapter_id"] == 2


def test_old_node_read_rejected_after_same_id_rebuilt() -> None:
    trees = EventTrees("run")
    trees.begin(fixture_id(__name__, "a1"))
    trees.sync(fixture_id(__name__, "a1"), 1, [node()])
    stale = trees.read("node")
    trees.rollback(fixture_id(__name__, "a1"))
    trees.begin(fixture_id(__name__, "a2"))
    trees.sync(fixture_id(__name__, "a2"), 1, [node()])
    trees.confirm(fixture_id(__name__, "a2"))
    trees.begin(fixture_id(__name__, "b1"))
    child = node("子事件").model_copy(update={"node_id": "child", "tree_id": "child_tree"})
    trees.sync(fixture_id(__name__, "b1"), 2, [child])
    reads = {"node": stale, "child": trees.read("child")}
    with pytest.raises(
        ValueError, match=f"读取生产者={fixture_id(__name__, 'a1')} 当前生产者={fixture_id(__name__, 'a2')}"
    ):
        trees.connect(fixture_id(__name__, "b1"), "child", "node", "main", reads, {1})
    reads["node"] = trees.read("node")
    trees.connect(fixture_id(__name__, "b1"), "child", "node", "main", reads, {1})
    assert trees.read("child")["content"]["tree_id"] == "child_tree"
    assert trees.read("child")["content"]["parent_node_id"] is None


def test_changed_content_and_unsaved_foreign_endpoints_rejected() -> None:
    trees = EventTrees("run")
    trees.begin(fixture_id(__name__, "a1"))
    trees.sync(fixture_id(__name__, "a1"), 1, [node()])
    read = trees.read("node")
    with pytest.raises(ValueError, match="业务内容冲突"):
        trees.sync(fixture_id(__name__, "a1"), 1, [node().model_copy(update={"is_foreshadow_setup": True})])
    read["content"]["summary"] = "已过期内容"
    trees.begin(fixture_id(__name__, "b1"))
    child = node().model_copy(update={"node_id": "child"})
    trees.sync(fixture_id(__name__, "b1"), 2, [child])
    reads = {"node": read, "child": trees.read("child")}
    with pytest.raises(ValueError, match="内容已变化"):
        trees.connect(fixture_id(__name__, "b1"), "child", "node", "main", reads, {1})
    reads["node"] = trees.read("node")
    with pytest.raises(ValueError, match="未成功保存"):
        trees.connect(fixture_id(__name__, "b1"), "child", "node", "main", reads, {1})


def test_case_exclusion_is_a_one_time_promise() -> None:
    """承诺二值一次性：接手后他方只能得到 taken，确认或回滚都不退回"""
    pool = CasePool("run")
    a, b = fixture_id(__name__, "a1"), fixture_id(__name__, "b1")
    pool.begin(a)
    pool.begin(b)
    case = pool.push("dialogue", "核查关联", a)
    assert set(case) == {"case_id", "case_type", "description"}
    pool.push("dialogue", "核查关联", b)
    assert pool.claim(case["case_id"], a)["status"] == "claimed"
    assert pool.claim(case["case_id"], b)["status"] == "taken"
    assert pool.claim(case["case_id"], b)["status"] == "taken"
    pool.submit(case["case_id"], a)
    pool.confirm(a)
    assert pool.claim(case["case_id"], b)["status"] == "taken"
    pool.rollback(b)
    assert pool.search()[0]["submitted"] is True


def test_role_finish_never_fills_metrics_or_skips_dialogue_candidates():
    from src.agents.annotation.agent import WorkExecution
    from src.agents.annotation.agent_ir import AgentAnnotation
    from src.agents.annotation.ledger import AnnotationToolLedger
    from src.fact_graph.inputs import ChapterMetricsInput
    from src.work.annotation_work import WorkReceipt

    for role in ("entity", "event", "annotation", "metric"):
        ledger = AnnotationToolLedger(
            run_scope=fixture_id(__name__, "r"),
            current_chapter_id=1,
            current_chapter_text="张三说：“走吧。”",
            allow_future_context=False,
            graph=FactGraph(run_scope=fixture_id(__name__, "r")),
            role=role,
        )
        execution = WorkExecution(
            WorkReceipt(role, fixture_id(__name__, "r"), "annotation", {}), "i", ledger, AgentAnnotation(role=role)
        )
        if role in {"entity", "event"}:
            execution.validate()
            assert execution.output()["metrics"] is None
        else:
            assert "metrics" in execution.validate()
            ledger.apply_metrics(ChapterMetricsInput(summary="出发", emotional_valence=0, narrative_function="铺垫"))
            assert any("dialogue_candidates" in item for item in execution.validate())


def test_duplicate_node_conflict_does_not_overwrite_original_content():
    trees = EventTrees("run")
    trees.begin(fixture_id(__name__, "a1"))
    trees.sync(fixture_id(__name__, "a1"), 1, [node()])
    with pytest.raises(ValueError, match="业务内容冲突"):
        trees.sync(fixture_id(__name__, "a1"), 1, [node("改写")])
    assert trees.read("node")["content"]["description"] == "事件"
