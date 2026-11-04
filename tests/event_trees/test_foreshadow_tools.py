"""伏笔程序入口、显式动作与冻结贡献的无数据库验证"""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.agents.annotation.agent import AnnotationAgent
from src.agents.annotation.agent_runtime import AgentProgramRuntime
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.work_tools import build_work_tools
from src.event_trees.trees import EventTrees
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import ChapterParagraphInfo
from src.storage import new_id
from src.storage.models import EventForeshadowingAction
from src.storage.records.events import EventSave
from src.storage.repositories.event_writes import EventWriter
from src.text_processing.evidence import EvidenceParagraph
from tests.support.annotation_work_tools import _work_tools_context


@pytest.mark.asyncio
async def test_program_can_set_up_reinforce_pay_off_and_link_foreshadowing():
    run_id = new_id()
    text = "旧信提及一枚印章，后来众人找到了印章。"
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=1,
        current_chapter_text=text,
        allow_future_context=False,
        graph=FactGraph(run_scope=run_id),
        paragraph_info=ChapterParagraphInfo(paragraph_ids=[0], char_spans=[(0, len(text))], texts=[text]),
        role="event",
    )
    agent, execution, query = _work_tools_context(SimpleNamespace(), ledger)
    execution.receipt.payload["paragraphs"] = [SimpleNamespace(paragraph_id=0, chapter_id=1, text=text)]
    agent.fact_graph.begin(execution.invocation_id, 1, "event")
    agent.lock = asyncio.Lock()

    async def invoke(tool_map, call):
        return await AnnotationAgent.invoke_tool(agent, execution, tool_map, call)

    ledger.invoke_tool = invoke
    tools = build_work_tools(agent, execution, query)
    runtime = AgentProgramRuntime({tool.name: tool for tool in tools}, ledger, execution.agent)
    catalog = runtime.build_tool().description
    assert all(
        name + "(" in catalog
        for name in (
            "event",
            "foreshadow_action",
            "write_link",
            "write_event",
            "retract_structure",
        )
    )
    assert "write_event" in runtime.execution_tools
    assert "write_queue" not in runtime.execution_tools
    assert "write_queue" not in catalog
    assert "write_foreshadowing_action" in runtime.execution_tools
    receipt = json.loads(
        await runtime.execute(
            "created = write_event(items=["
            "{'el':'journey', 'title':'众人启程', 'problem':'如何寻印', 'summary':'众人出发寻找印章', "
            "'event_type':'行动', 'status':'ongoing', 'evidence':1},"
            "{'el':'hint', 'title':'旧信', 'problem':'印章何在', 'summary':'旧信提及印章', "
            "'event_type':'线索', 'status':'ongoing', 'evidence':1, 'isforeshadowing':True, 'confidence':'high'},"
            "{'el':'found', 'title':'找到印章', 'problem':'印章何在', 'summary':'众人找到印章', "
            "'event_type':'发现', 'status':'resolved', 'evidence':1}])\n"
            "source = created['results'][1]['content']['event_id']\n"
            "target_id = created['results'][2]['content']['event_id']\n"
            "read_event(node_id=source)\nread_event(node_id=target_id)\n"
            "foreshadow_action(source_event_id=source, action_type='reinforce', evidence=1)\n"
            "foreshadow_action(source_event_id=source, action_type='payoff', target_event_id=target_id, evidence=1)\n"
            "write_link(source_id=source, target_id=target_id, kind='foreshadowing', "
            "reason='找到印章回应旧信', evidence=1)"
        )
    )
    assert receipt.get("status") not in {"runtime_error", "rejected"}, receipt
    assert not receipt.get("failed"), receipt
    assert all(operation["status"] == "success" for operation in runtime.ops)
    actions = agent.event_trees.freeze_actions(execution.invocation_id, execution.receipt.payload["paragraphs"])
    assert sorted(action["action_type"] for action in actions.values()) == ["payoff", "reinforce", "setup"]
    assert all("source_event_id" in action and "root_event_id" not in action for action in actions.values())
    assert len({action["source_event_id"] for action in actions.values()}) == 1
    assert len(ledger.events.relations) == 1
    assert ledger.events.relations[0]["relation_type"] == "foreshadowing"
    graph = agent.event_trees.graph(execution.invocation_id, require_complete=True)
    assert list(graph.queues.values()) == [tuple(agent.event_trees.nodes)]


def action(operation="operation", *, order=1):
    return {
        "source_operation_id": operation,
        "source_event_id": "hint",
        "target_event_id": None,
        "action_type": "reinforce",
        "chapter_id": 1,
        "operation_order": order,
        "evidence": [{"paragraph_id": 0}],
    }


def test_action_replay_keeps_identity_and_order_but_rejects_changed_content():
    trees = EventTrees("run")
    trees.begin("author")
    value = action()
    identifier = trees.write_action("author", value)
    assert trees.write_action("author", action(order=99)) == identifier
    assert trees.actions[identifier]["operation_order"] == 1
    value["evidence"][0]["paragraph_id"] = 99
    assert trees.actions[identifier]["evidence"] == [{"paragraph_id": 0}]
    before = deepcopy(trees.actions)
    with pytest.raises(ValueError, match="业务内容冲突"):
        trees.write_action("author", {**action(), "action_type": "payoff"})
    assert trees.actions == before


def test_confirmed_action_is_immutable_and_not_removed_by_rollback():
    trees = EventTrees("run")
    trees.begin("author")
    identifier = trees.write_action("author", action())
    trees.confirm("author")
    with pytest.raises(ValueError, match="执行已停止"):
        trees.write_action("author", action("later"))
    trees.rollback("author")
    assert identifier in trees.actions


def test_rollback_and_snapshot_preserve_other_authors_actions():
    trees = EventTrees("run")
    for author in ("first", "second"):
        trees.begin(author)
        trees.write_action(author, action())
    before = trees.snapshot("second")
    trees.rollback("second")
    assert {value["author"] for value in trees.actions.values()} == {"first"}
    trees.restore(before)
    assert {value["author"] for value in trees.actions.values()} == {"first", "second"}


def test_frozen_action_save_preserves_source_identity_and_independent_evidence(monkeypatch):
    from src.storage.repositories import event_contributions, narrative_records
    from src.storage.repositories.queries import event_write_rows

    session = Mock()
    source = SimpleNamespace(annotation_record_id="annotation", is_foreshadowing_root=True)
    context = SimpleNamespace(agent_id="author", run_id="run", chapter_order=1)
    monkeypatch.setattr(event_write_rows, "lock_run", lambda *_args: None)
    monkeypatch.setattr(event_write_rows, "get_output", lambda *_args: context)
    monkeypatch.setattr(event_write_rows, "get_action_source", lambda *_args: source)
    monkeypatch.setattr(event_write_rows, "get_endpoint", lambda *_args: source)
    monkeypatch.setattr(narrative_records, "annotation_record_source", lambda *_args: context)
    written_evidence = []
    monkeypatch.setattr(
        narrative_records, "write_evidence_rows",
        lambda _session, owner, refs: written_evidence.append((owner, refs)),
    )
    monkeypatch.setattr(event_contributions, "save_annotation_event_contribution", lambda *_args: None)
    value = {**action(), "evidence": [{"paragraph_id": 0, "char_start": 0, "char_end": 2}]}
    frozen = EventSave(
        "run", "author", 1, (EvidenceParagraph(1, 0, "线索", 0, 2),),
        json.dumps({"nodes": {}, "actions": {"action-id": value}}), "{}",
    )
    EventWriter("run").save_work(session, frozen, "annotation")
    rows = [call.args[0] for call in session.add.call_args_list]
    assert len(rows) == 1 and isinstance(rows[0], EventForeshadowingAction)
    assert rows[0].source_event_id == "hint" and rows[0].target_event_id is None
    assert written_evidence == [({"foreshadow_action_id": "action-id"}, value["evidence"])]


def test_saved_action_recovery_keeps_identity_source_and_original_evidence(monkeypatch):
    from src.event_trees import storage_map

    evidence = [{"chapter_id": 29, "paragraph_id": 7, "char_start": 0, "char_end": 2, "text": "照应"}]
    saved = SimpleNamespace(
        action_id="saved-action", source_event_id="hint", target_event_id=None, action_type="reinforce",
        source_operation_local_key="saved-operation", operation_order=3,
    )
    session = SimpleNamespace(reads=SimpleNamespace(
        annotations=SimpleNamespace(get_output=lambda _identifier: SimpleNamespace(agent_id="author")),
        events=SimpleNamespace(
            list_output_events=lambda _identifier: [], list_execution_actions=lambda _identifier: [saved],
            list_producer_links=lambda _identifier: [], list_queue_links=lambda _identifier: [],
            list_execution_trees=lambda _identifier: [],
        ),
    ))
    monkeypatch.setattr(storage_map, "fetch_evidence", lambda *_args: {"saved-action": evidence})
    monkeypatch.setattr(storage_map, "evidence_payloads", lambda _session, _run, rows: rows)
    monkeypatch.setattr(storage_map, "annotation_record_source", lambda *_args: SimpleNamespace(chapter_id=29))
    trees = EventTrees("run")
    restored = trees.load_saved_work(session, "author", "annotation")
    trees.recover_work(restored)
    actual = trees.actions["saved-action"]
    assert actual["source_event_id"] == "hint" and "root_event_id" not in actual
    assert actual["source_operation_id"] == "saved-operation" and actual["operation_order"] == 3
    assert actual["chapter_id"] == 29 and actual["evidence"] == evidence
    trees.rollback("author")
    assert trees.actions["saved-action"] == actual
