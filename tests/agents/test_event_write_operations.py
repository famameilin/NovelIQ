"""事件操作契约、业务校验与保存恢复的无数据库验证"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from src.agents.diagnosis.program_runtime import DiagnosisProgramRuntime
from src.agents.diagnosis.prompts import build_diagnosis_system_prompt
from src.agents.diagnosis.tools import build_diagnosis_tools
from src.case_pool import CasePool
from src.event_trees import diagnosis_persistence, organization, storage_map
from src.event_trees.organization import EventOrganizationDraft, validate_organization
from src.event_trees.organization_models import NarrativeOrganization, OrganizationEvidence
from src.storage import new_id
from src.storage.models import CompleteEvent, NarrativeLink, OrganizationCheck, SourceEvidence
from src.storage.repositories import diagnosis_event_writes, diagnosis_publish
from src.utils.identity import text_digest


@pytest.fixture
def event_tools(monkeypatch):
    run_id, author = new_id(), new_id()
    paragraphs = {1: SimpleNamespace(paragraph_id=1, chapter_id=1, text="顾霜开门后点灯。")}
    storage = SimpleNamespace(
        reads=SimpleNamespace(
            events=SimpleNamespace(
                list_queue_links=lambda _: [],
                list_queue_references=lambda _: [],
                list_execution_trees=lambda _: [],
            )
        ),
        narrative=SimpleNamespace(validate_event_range=Mock()),
    )
    monkeypatch.setattr(storage_map, "run_events", lambda *_: {})
    monkeypatch.setattr(storage_map, "run_execution_ids", lambda *_: [])
    monkeypatch.setattr(organization, "_run_event_dicts", lambda *_: {})
    monkeypatch.setattr(
        storage_map,
        "paragraph_rows",
        lambda _s, _r, ids: {key: value for key, value in paragraphs.items() if key in ids},
    )
    monkeypatch.setattr(storage_map, "global_positions", lambda _s, _r, ids: dict.fromkeys(ids, 0))
    draft = EventOrganizationDraft(storage, run_id, author)
    draft.producer_agent_id = author
    tools = build_diagnosis_tools(
        storage,
        run_id,
        agent_id=author,
        organization_draft=draft,
        case_pool=CasePool(run_id),
    )
    return draft, {tool.name: tool for tool in tools}


def event_item(key):
    return {
        "key": key,
        "title": key,
        "problem": "能否照明",
        "summary": key,
        "event_type": "行动",
        "status": "ongoing",
        "from": 1,
        "to": 1,
        "reason": "正文中的实际行动",
        "evidence": [{"paragraph_id": 1}],
    }


def create_event(tool, key):
    receipt = json.loads(tool.invoke({"items": [event_item(key)]}))
    assert receipt["status"] == "written", receipt
    identifier = receipt["results"][0]["event_id"]
    return identifier


def read_events(tools, *identifiers):
    for identifier in identifiers:
        tools["read_event"].invoke({"node_id": identifier})


def local_organization(draft):
    draft.validate_events()
    return NarrativeOrganization(
        source_agent_id=draft.agent_id,
        events=list(draft.events.values()),
        queues=list(draft.queues.values()),
        queue_references=list(draft.queue_references.values()),
        relations=list(draft.relations.values()),
        content_snapshot=draft.content_digest(),
        structure_snapshot=draft.structure_digest(),
    )


@pytest.mark.parametrize("operation", ["review", "structure_review"])
def test_removed_operations_are_absent_from_catalog_and_rejected_before_writes(event_tools, operation):
    draft, tools = event_tools
    schema = tools["write_event"].args_schema.model_json_schema()
    assert "operation" not in schema["$defs"]["EventItem"]["properties"]
    assert operation not in DiagnosisProgramRuntime(list(tools.values())).build_tool().description
    assert operation not in build_diagnosis_system_prompt(None, "case")
    with pytest.raises(ValidationError):
        tools["write_event"].invoke({"items": [{"operation": operation, "event_ids": ["event"]}]})
    assert not draft.events and not draft.queue_references and not draft.relations


async def test_actual_event_containment_and_relation_operations_still_complete(event_tools):
    draft, tools = event_tools
    runtime = DiagnosisProgramRuntime(list(tools.values()))
    code = (
        f'parent_event = write_event(items={[event_item("行动")]!r})["results"][0]["event_id"]\n'
        f'parent_tree = write_event(items={[event_item("行动")]!r})["tree_id"]\n'
        f'child_event = write_event(items={[event_item("点灯")]!r})["results"][0]["event_id"]\n'
        f'child_tree = write_event(items={[event_item("点灯")]!r})["tree_id"]\n'
        "read_event(node_id=parent_event)\n"
        "read_event(node_id=child_event)\n"
        'write_link(items=[{"operation":"reference", "parent_tree_id":parent_tree, "child_tree_id":child_tree, '
        '"reason":"行动包含点灯", "evidence":[{"paragraph_id":1}]}])\n'
        'write_link(items=[{"operation":"relation", "key":"因果", "source_kind":"event", '
        '"source_id":parent_event, "target_kind":"event", "target_id":child_event, "relation_type":"causal", '
        '"reason":"开门后点灯", "evidence":[{"paragraph_id":1}]}])'
    )
    result = json.loads(await runtime.execute(code))
    assert not result.get("failed"), result
    saved = local_organization(draft)
    assert len(saved.events) == 2 and len(saved.queue_references) == len(saved.relations) == 1
    assert not {"reviewed_events", "structure_reviews"} & saved.model_dump().keys()
    assert draft.read_draft()["totals"]["events"] == 2


def test_queue_reference_accepts_multiple_parents_and_rejects_cycles(event_tools):
    draft, tools = event_tools
    parent, child, other = [create_event(tools["write_event"], key) for key in ("parent", "child", "other")]
    parent_tree, child_tree, other_tree = (
        draft.queue_graph().event_tree[identifier] for identifier in (parent, child, other)
    )
    for identifier in (parent, child, other):
        read_events(tools, identifier)
    evidence = [OrganizationEvidence(paragraph_id=1)]
    draft.reference(parent_tree_id=parent_tree, child_tree_id=child_tree, reason="first parent", evidence=evidence)
    draft.reference(parent_tree_id=other_tree, child_tree_id=child_tree, reason="second parent", evidence=evidence)
    with pytest.raises(ValueError):
        draft.reference(parent_tree_id=child_tree, child_tree_id=parent_tree, reason="cycle", evidence=evidence)
    assert len(draft.queue_references) == 2


async def test_reference_accepts_tree_without_member_reads_and_rejects_unknown_tree(event_tools):
    draft, tools = event_tools
    runtime = DiagnosisProgramRuntime(list(tools.values()))
    parent, child = [create_event(tools["write_event"], key) for key in ("parent", "child")]
    parent_tree = draft.queue_graph().event_tree[parent]
    child_tree = draft.queue_graph().event_tree[child]
    linked = json.loads(
        await runtime.execute(
            f'write_link(items=[{{"operation":"reference", "parent_tree_id":{parent_tree!r}, '
            f'"child_tree_id":{child_tree!r}, "reason":"行动包含点灯", "evidence":[{{"paragraph_id":1}}]}}])'
        )
    )
    assert linked["status"] == "applied", linked
    assert [
        (item.parent_tree_id, item.child_tree_id) for item in draft.queue_references.values()
    ] == [(parent_tree, child_tree)]
    unknown = json.loads(
        await runtime.execute(
            'write_link(items=[{"operation":"reference", "parent_tree_id":"missing-tree", '
            f'"child_tree_id":{child_tree!r}, "reason":"行动包含点灯", "evidence":[{{"paragraph_id":1}}]}}])'
        )
    )
    assert unknown["status"] == "partial", unknown
    message = unknown["failed"][0]["message"]
    assert "可用事件树" in message and parent_tree in message and child_tree in message


async def test_reference_to_empty_parent_needs_no_evidence(event_tools):
    draft, tools = event_tools
    runtime = DiagnosisProgramRuntime(list(tools.values()))
    child = create_event(tools["write_event"], "child")
    child_tree = draft.queue_graph().event_tree[child]
    parent = json.loads(
        tools["write_event"].invoke({"items": [], "tree_key": "case-parent", "title": "案例父树"})
    )
    linked = json.loads(
        await runtime.execute(
            f'write_link(items=[{{"operation":"reference", "parent_tree_id":{parent["tree_id"]!r}, '
            f'"child_tree_id":{child_tree!r}, "reason":"案例归并", "evidence":[]}}])'
        )
    )
    assert linked["status"] == "applied", linked
    saved = next(iter(draft.queue_references.values()))
    assert saved.parent_tree_id == parent["tree_id"]
    assert saved.evidence == []


def test_reference_conflict_names_previous_author_and_reason(event_tools):
    draft, tools = event_tools
    parent, child = [create_event(tools["write_event"], key) for key in ("parent", "child")]
    parent_tree = draft.queue_graph().event_tree[parent]
    child_tree = draft.queue_graph().event_tree[child]
    read_events(tools, parent, child)
    evidence = [OrganizationEvidence(paragraph_id=1)]
    draft.reference(parent_tree_id=parent_tree, child_tree_id=child_tree, reason="行动包含点灯", evidence=evidence)
    with pytest.raises(ValueError) as caught:
        draft.reference(parent_tree_id=parent_tree, child_tree_id=child_tree, reason="另一条理由", evidence=evidence)
    message = str(caught.value)
    assert draft.producer_agent_id in message and "行动包含点灯" in message


def test_quote_binding_and_saved_evidence_hash_are_still_checked(event_tools):
    draft, tools = event_tools
    invalid = event_item("照明")
    invalid["evidence"] = [{"paragraph_id": 1, "quote": "不存在的原文"}]
    with pytest.raises(ValueError, match="不匹配原文"):
        tools["write_event"].invoke({"items": [invalid]})
    assert not draft.events
    identifier = create_event(tools["write_event"], "点灯")
    read_events(tools, identifier)
    saved = local_organization(draft)
    assert saved.events[0].evidence[0].text_hash == text_digest("顾霜开门后点灯。")
    draft.session.narrative.validate_event_range.assert_called()
    evidence = saved.events[0].evidence[0].model_copy(update={"text_hash": "wrong"})
    changed = saved.events[0].model_copy(update={"evidence": [evidence]})
    changed_draft = EventOrganizationDraft(draft.session, draft.run_id, draft.agent_id)
    changed_draft.events[identifier] = changed
    changed_draft.queues = dict(draft.queues)
    invalid_saved = saved.model_copy(
        update={
            "events": [changed],
            "content_snapshot": changed_draft.content_digest(),
            "structure_snapshot": changed_draft.structure_digest(),
        }
    )
    with pytest.raises(ValueError, match="哈希"):
        validate_organization(draft.session, draft.run_id, invalid_saved)


def test_session_and_report_save_only_events_links_and_evidence(event_tools, monkeypatch):
    draft, tools = event_tools
    parent, child = [create_event(tools["write_event"], key) for key in ("行动", "点灯")]
    parent_tree = draft.queue_graph().event_tree[parent]
    child_tree = draft.queue_graph().event_tree[child]
    read_events(tools, parent)
    read_events(tools, child)
    draft.reference(
        parent_tree_id=parent_tree,
        child_tree_id=child_tree,
        reason="行动包含点灯",
        evidence=[OrganizationEvidence(paragraph_id=1)],
    )
    monkeypatch.setattr("src.storage.repositories.queue_writes.queue_graph", lambda *_args, **_kwargs: None)
    session = Mock()
    session.scalar.return_value = None
    session.scalars.return_value = []
    session.get.return_value = None
    monkeypatch.setattr(diagnosis_event_writes.smap, "fetch_evidence", lambda *_: {})
    monkeypatch.setattr(diagnosis_event_writes, "_require_report", lambda *_: None)
    diagnosis_event_writes.save_case_session_rows(session, draft.run_id, draft.producer_agent_id, draft)
    diagnosis_event_writes.save_diagnosis_events(session, draft.run_id, local_organization(draft), "report")
    rows = [call.args[0] for call in session.add.call_args_list]
    assert sum(isinstance(row, CompleteEvent) for row in rows) == 4
    assert sum(isinstance(row, NarrativeLink) for row in rows) == 6
    members = [row for row in rows if isinstance(row, NarrativeLink) and row.tree_id is not None]
    assert {(row.tree_id, row.member_event_id, row.position) for row in members} == {
        (parent_tree, parent, 0),
        (child_tree, child, 0),
    }
    assert len(members) == 4
    assert any(isinstance(row, SourceEvidence) for row in rows)
    assert not any(isinstance(row, OrganizationCheck) for row in rows)


@pytest.mark.parametrize("link_reason", ["点灯", ""])
def test_resume_preserves_saved_events_without_querying_checks(event_tools, monkeypatch, link_reason):
    draft, tools = event_tools
    identifier = create_event(tools["write_event"], "点灯")
    event = draft.events[identifier]
    tree_id = new_id()
    saved = SimpleNamespace(**event.model_dump())
    monkeypatch.setattr(diagnosis_persistence, "_run_events", lambda *_: {identifier: saved})
    monkeypatch.setattr(
        diagnosis_persistence,
        "_run_event_dicts",
        lambda *_: {identifier: {"first_text_position": 0, "participants": []}},
    )
    monkeypatch.setattr(diagnosis_persistence.smap, "fetch_evidence", lambda *_: {})
    monkeypatch.setattr(
        diagnosis_persistence, "_evidence_payloads", lambda *_: [ref.model_dump() for ref in event.evidence]
    )
    draft.session.diagnosis = SimpleNamespace(session_rows=lambda _: {"links": []})
    draft.session.reads.events.list_queue_links = lambda _: [
        SimpleNamespace(
            link_id=new_id(), tree_id=tree_id, member_event_id=identifier, position=0, reason=link_reason
        )
    ]
    draft.session.reads.events.list_execution_trees = lambda _: [
        SimpleNamespace(
            group_id=tree_id,
            tree_key=None,
            title="点灯",
            description="点灯",
            is_event_line=True,
            producer_agent_id=event.producer_agent_id,
        )
    ]
    recovered = EventOrganizationDraft(draft.session, draft.run_id, draft.agent_id)
    diagnosis_persistence.hydrate_draft_from_run(draft.session, draft.run_id, recovered)
    assert recovered.events[identifier] == event
    assert recovered.event_line_ids == {tree_id}
    assert not hasattr(recovered, "reviewed_events") and not hasattr(recovered, "structure_reviews")
    session = Mock()
    session.scalars.return_value = []
    rows = diagnosis_publish.session_rows(session, draft.run_id)
    assert set(rows) == {"agent", "links"}
    assert all("event_checks" not in str(call.args[0]) for call in session.scalars.call_args_list)
