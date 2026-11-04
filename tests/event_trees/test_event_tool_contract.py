"""正式事件工具按一次调用保存完整有序队列"""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.agents.annotation.errors import AnnotationStageRejection
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.work_tools import build_work_tools
from src.agents.diagnosis.program_runtime import DiagnosisProgramRuntime
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import ChapterParagraphInfo
from tests.agents.test_event_write_operations import event_item
from tests.agents.test_event_write_operations import event_tools as event_tools
from tests.support.annotation_work_tools import _work_tools_context


@pytest.fixture(params=["annotation", "diagnosis"])
def event_writer(request, event_tools):
    if request.param == "diagnosis":
        draft, tools = event_tools
        return tools["write_event"], event_item, draft.queue_graph, lambda: dict(draft.events)
    return _annotation_writer()


def _annotation_writer():
    text = "顾霜开门后点灯。"
    ledger = AnnotationToolLedger(
        run_scope="event-tool-run",
        current_chapter_id=1,
        current_chapter_text=text,
        allow_future_context=False,
        graph=FactGraph(run_scope="event-tool-run"),
        paragraph_info=ChapterParagraphInfo(paragraph_ids=[0], char_spans=[(0, len(text))], texts=[text]),
        role="event",
    )
    agent, execution, query = _work_tools_context(SimpleNamespace(), ledger)
    tools = {candidate.name: candidate for candidate in build_work_tools(agent, execution, query)}

    def item(key):
        return {
            "el": key,
            "title": key,
            "problem": "能否照明",
            "summary": key,
            "event_type": "行动",
            "status": "ongoing",
            "evidence": 1,
        }

    return (
        tools["write_event"],
        item,
        lambda: agent.event_trees.graph(execution.invocation_id, require_complete=True),
        lambda: dict(agent.event_trees.nodes),
    )


def test_items_are_one_ordered_queue(event_writer):
    tool, item, graph, _events = event_writer
    values = [item("点灯"), item("开门")]
    first = json.loads(tool.invoke({"items": values}))
    actual = graph()
    assert len(actual.queues) == 1
    identifiers = actual.queues[first["tree_id"]]
    assert len(identifiers) == 2
    assert first["tree_id"] not in identifiers
    assert actual.event_parents(identifiers[1]) == [identifiers[0]]
    tool.invoke({"items": list(reversed(values))})
    assert graph().queues == actual.queues


def test_invalid_member_rolls_back_whole_queue_and_keeps_prior_queue(event_writer):
    tool, item, graph, events = event_writer
    tool.invoke({"items": [item("既有行动")]})
    previous_events, previous_queues = events(), dict(graph().queues)
    invalid = item("错误行动")
    invalid["evidence"] = 999 if isinstance(invalid["evidence"], int) else [{"paragraph_id": 999}]
    with pytest.raises((ValueError, AnnotationStageRejection)):
        tool.invoke({"items": [item("新增行动"), invalid]})
    assert events() == previous_events
    assert graph().queues == previous_queues


@pytest.mark.parametrize("items", [[], [{"operation": "queue", "event_ids": ["old"]}]])
def test_invalid_items_are_rejected_before_writing(event_writer, items):
    tool, _item, graph, events = event_writer
    with pytest.raises((ValidationError, ValueError)):
        tool.invoke({"items": items})
    assert not events()
    assert not graph().queues


def test_empty_tree_is_created_with_key_and_title(event_writer):
    tool, _item, graph, events = event_writer
    receipt = json.loads(tool.invoke({"items": [], "tree_key": "案例父树", "title": "案例父树"}))
    tree_id = receipt["tree_id"]
    assert tree_id
    assert not events()
    assert graph().queues[tree_id] == ()
    assert list(graph().unparented) == [tree_id]


async def test_diagnosis_program_preserves_whole_queue_in_one_call(event_tools):
    draft, tools = event_tools
    runtime = DiagnosisProgramRuntime(list(tools.values()))
    values = [event_item("点灯"), event_item("开门")]
    receipt = json.loads(await runtime.execute(f"created = write_event(items={values!r})"))
    assert receipt["status"] == "applied", receipt
    assert len(draft.queues) == 1
    assert list(draft.queues.values())[0].event_ids == [
        entry["event_id"] for entry in runtime.env["created"]["results"]
    ]
    assert len([op for op in runtime.ops if op["tool_name"] == "write_event"]) == 1


def test_unsaved_tree_takes_more_nodes_and_duplicate_fact_names_it():
    """本执行未保存的树可继续追加新事件；同一事实换新引用 id 重写被拒并点名已有事件"""
    tool, _item, graph, _events = _annotation_writer()

    def node(el: str, summary: str):
        return {
            "el": el,
            "title": summary,
            "problem": "能否照明",
            "summary": summary,
            "event_type": "行动",
            "status": "ongoing",
            "evidence": 1,
        }

    first = json.loads(tool.invoke({"items": [node("e1", "点灯"), node("e2", "开门")]}))
    tool.invoke({"items": [node("e1", "点灯"), node("e2", "开门"), node("e3", "进门")]})
    queues = graph().queues
    assert len(queues) == 1
    assert len(queues[first["tree_id"]]) == 3
    assert queues[first["tree_id"]][-1] == graph().queues[first["tree_id"]][-1]

    with pytest.raises((ValueError, AnnotationStageRejection)) as excinfo:
        tool.invoke({"items": [node("e4", "开门")]})
    assert "同源重复" in str(excinfo.value)
    assert "e2" in str(getattr(excinfo.value, "expected", ""))


def test_appending_refreshes_reads_of_existing_members():
    """追加后既有成员的事件读取快照按新队列整体刷新，后续引用不会判成未读"""
    text = "顾霜开门后点灯。"
    ledger = AnnotationToolLedger(
        run_scope="event-tool-run",
        current_chapter_id=1,
        current_chapter_text=text,
        allow_future_context=False,
        graph=FactGraph(run_scope="event-tool-run"),
        paragraph_info=ChapterParagraphInfo(paragraph_ids=[0], char_spans=[(0, len(text))], texts=[text]),
        role="event",
    )
    agent, execution, query = _work_tools_context(SimpleNamespace(), ledger)
    tool = {candidate.name: candidate for candidate in build_work_tools(agent, execution, query)}["write_event"]

    def node(el: str, summary: str):
        return {
            "el": el,
            "title": summary,
            "problem": "能否照明",
            "summary": summary,
            "event_type": "行动",
            "status": "ongoing",
            "evidence": 1,
        }

    first = json.loads(tool.invoke({"items": [node("t1", "点灯")]}))
    root, entry = first["tree_id"], first["results"][0]["content"]["event_id"]
    assert len(execution.event_reads[entry]["tree_event_ids"]) == 1
    tool.invoke({"items": [node("t1", "点灯"), node("e1", "开门")]})
    assert len(execution.event_reads[entry]["tree_event_ids"]) == 2
    second = json.loads(tool.invoke({"items": [node("t2", "锁门")]}))["tree_id"]
    tools = {candidate.name: candidate for candidate in build_work_tools(agent, execution, query)}
    linked = json.loads(
        tools["write_link"].invoke(
            {
                "source_id": root,
                "target_id": second,
                "kind": "parent_child",
                "reason": "点灯后才能看见门",
                "evidence": 1,
            }
        )
    )
    assert linked["status"] == "written"


def test_parent_child_link_needs_no_evidence():
    """父子引用只要求理由，空父树连接时不取子树成员证据"""
    text = "顾霜开门后点灯。"
    ledger = AnnotationToolLedger(
        run_scope="event-tool-run",
        current_chapter_id=1,
        current_chapter_text=text,
        allow_future_context=False,
        graph=FactGraph(run_scope="event-tool-run"),
        paragraph_info=ChapterParagraphInfo(paragraph_ids=[0], char_spans=[(0, len(text))], texts=[text]),
        role="event",
    )
    agent, execution, query = _work_tools_context(SimpleNamespace(), ledger)
    tools = {candidate.name: candidate for candidate in build_work_tools(agent, execution, query)}
    parent = json.loads(
        tools["write_event"].invoke({"items": [], "tree_key": "case-parent", "title": "案例父树"})
    )["tree_id"]
    child = json.loads(tools["write_event"].invoke({"items": [{
        "el": "e1",
        "title": "点灯",
        "problem": "能否照明",
        "summary": "点灯",
        "event_type": "行动",
        "status": "ongoing",
        "evidence": 1,
    }]}))["tree_id"]
    linked = json.loads(
        tools["write_link"].invoke(
            {"source_id": parent, "target_id": child, "kind": "parent_child", "reason": "案例归并"}
        )
    )
    assert linked["status"] == "written"
    (reference,) = ledger.events.queue_references.values()
    assert reference["evidence"] == []


def test_unknown_event_reference_names_written_els():
    """引用解析失败时回执点名输入并列出本执行已写的 el，模型不必靠猜"""
    text = "顾霜开门后点灯。"
    ledger = AnnotationToolLedger(
        run_scope="event-tool-run",
        current_chapter_id=1,
        current_chapter_text=text,
        allow_future_context=False,
        graph=FactGraph(run_scope="event-tool-run"),
        paragraph_info=ChapterParagraphInfo(paragraph_ids=[0], char_spans=[(0, len(text))], texts=[text]),
        role="event",
    )
    agent, execution, query = _work_tools_context(SimpleNamespace(), ledger)
    tools = {candidate.name: candidate for candidate in build_work_tools(agent, execution, query)}
    tools["write_event"].invoke(
        {
            "items": [
                {
                    "el": "t1",
                    "title": "点灯",
                    "problem": "能否照明",
                    "summary": "点灯",
                    "event_type": "行动",
                    "status": "ongoing",
                    "evidence": 1,
                }
            ]
        }
    )
    with pytest.raises(ValueError) as excinfo:
        tools["write_plotline"].invoke(
            {
                "subject_title": "照明",
                "description": "点灯",
                "after": "有光",
                "evidence": 1,
                "event_id": "e9",
            }
        )
    message = str(excinfo.value)
    assert "e9" in message
    assert "t1" in message.split("本执行已写的 el：")[1]
