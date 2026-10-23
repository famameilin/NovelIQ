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
from src.event_trees import diagnosis_persistence, organization
from src.event_trees.organization import EventOrganizationDraft, OrganizationEvidence, validate_organization
from src.storage import new_id
from src.storage.models import CompleteEvent, NarrativeLink, OrganizationCheck, SourceEvidence
from src.storage.repositories import diagnosis_event_writes, diagnosis_publish
from src.utils.identity import text_digest


@pytest.fixture
def event_tools(monkeypatch):
    run_id, author = new_id(), new_id()
    paragraphs = {1: SimpleNamespace(paragraph_id=1, chapter_id=1, text="顾霜开门后点灯。")}
    storage = SimpleNamespace(
        reads=SimpleNamespace(event_trees_organization_parents_1=lambda _: []),
        narrative=SimpleNamespace(validate_event_range=Mock()),
    )
    monkeypatch.setattr(organization, "_run_events", lambda *_: {})
    monkeypatch.setattr(organization, "_run_event_dicts", lambda *_: {})
    monkeypatch.setattr(organization, "_paragraph_rows", lambda _s, _r, ids: {
        key: value for key, value in paragraphs.items() if key in ids
    })
    monkeypatch.setattr(organization, "_global_positions", lambda _s, _r, ids: dict.fromkeys(ids, 0))
    draft = EventOrganizationDraft(storage, run_id, author)
    draft.producer_agent_id = author
    tools = build_diagnosis_tools(
        storage, run_id, agent_id=author, organization_draft=draft, case_pool=CasePool(run_id),
    )
    return draft, {tool.name: tool for tool in tools}


def event_item(key):
    return {
        "operation": "event", "key": key, "title": key, "problem": "能否照明", "summary": key,
        "event_type": "行动", "status": "ongoing", "from": 1, "to": 1,
        "reason": "正文中的实际行动", "evidence": [{"paragraph_id": 1}],
    }


def create_event(tool, key):
    receipt = json.loads(tool.invoke({"items": [event_item(key)]}))
    assert receipt["status"] == "written", receipt
    return receipt["results"][0]["event_id"]


@pytest.mark.parametrize("operation", ["review", "structure_review"])
def test_removed_operations_are_absent_from_catalog_and_rejected_before_writes(event_tools, operation):
    draft, tools = event_tools
    schema = tools["write_event"].args_schema.model_json_schema()
    mapping = schema["properties"]["items"]["items"]["discriminator"]["mapping"]
    assert set(mapping) == {"event", "contain", "relation", "retract"}
    assert operation not in DiagnosisProgramRuntime(list(tools.values())).build_tool().description
    assert operation not in build_diagnosis_system_prompt(None, "case")
    with pytest.raises(ValidationError):
        tools["write_event"].invoke({"items": [{"operation": operation, "event_ids": ["event"]}]})
    assert not draft.events and not draft.containments and not draft.relations


async def test_actual_event_containment_and_relation_operations_still_complete(event_tools):
    draft, tools = event_tools
    runtime = DiagnosisProgramRuntime(list(tools.values()))
    code = (
        f'parent = write_event(items={[event_item("行动")]!r})["results"][0]["event_id"]\n'
        f'child = write_event(items={[event_item("点灯")]!r})["results"][0]["event_id"]\n'
        'write_event(items=[{"operation":"contain", "parent_event_id":parent, "child_event_id":child, '
        '"reason":"行动包含点灯", "evidence":[{"paragraph_id":1}]}])\n'
        'write_event(items=[{"operation":"relation", "key":"因果", "source_kind":"event", '
        '"source_id":parent, "target_kind":"event", "target_id":child, "relation_type":"causal", '
        '"reason":"开门后点灯", "evidence":[{"paragraph_id":1}]}])'
    )
    result = json.loads(await runtime.execute(code))
    assert not result.get("failed"), result
    saved = draft.finish()
    assert len(saved.events) == 2 and len(saved.containments) == len(saved.relations) == 1
    assert not {"reviewed_events", "structure_reviews"} & saved.model_dump().keys()
    assert draft.read_draft()["totals"]["events"] == 2


def test_containment_cycle_and_second_parent_are_still_rejected(event_tools):
    draft, tools = event_tools
    parent, child, other = [create_event(tools["write_event"], key) for key in ("行动", "点灯", "寻路")]
    evidence = [OrganizationEvidence(paragraph_id=1)]
    draft.contain(parent_event_id=parent, child_event_id=child, reason="行动包含点灯", evidence=evidence)
    with pytest.raises(ValueError, match="直接父"):
        draft.contain(parent_event_id=other, child_event_id=child, reason="重复挂接", evidence=evidence)
    with pytest.raises(ValueError, match="成环"):
        draft.contain(parent_event_id=child, child_event_id=parent, reason="反向挂接", evidence=evidence)
    assert len(draft.containments) == 1


def test_quote_binding_and_saved_evidence_hash_are_still_checked(event_tools):
    draft, tools = event_tools
    invalid = event_item("照明")
    invalid["evidence"] = [{"paragraph_id": 1, "quote": "不存在的原文"}]
    receipt = json.loads(tools["write_event"].invoke({"items": [invalid]}))
    assert receipt["status"] == "partial" and "不匹配原文" in receipt["failed"][0]["message"]
    assert not draft.events
    identifier = create_event(tools["write_event"], "点灯")
    saved = draft.finish()
    assert saved.events[0].evidence[0].text_hash == text_digest("顾霜开门后点灯。")
    draft.session.narrative.validate_event_range.assert_called()
    evidence = saved.events[0].evidence[0].model_copy(update={"text_hash": "wrong"})
    changed = saved.events[0].model_copy(update={"evidence": [evidence]})
    changed_draft = EventOrganizationDraft(draft.session, draft.run_id, draft.agent_id)
    changed_draft.events[identifier] = changed
    invalid_saved = saved.model_copy(update={
        "events": [changed], "content_snapshot": changed_draft.content_digest(),
        "structure_snapshot": changed_draft.structure_digest(),
    })
    with pytest.raises(ValueError, match="哈希"):
        validate_organization(draft.session, draft.run_id, invalid_saved)


def test_session_and_report_save_only_events_links_and_evidence(event_tools, monkeypatch):
    draft, tools = event_tools
    parent, child = [create_event(tools["write_event"], key) for key in ("行动", "点灯")]
    draft.contain(
        parent_event_id=parent, child_event_id=child, reason="行动包含点灯",
        evidence=[OrganizationEvidence(paragraph_id=1)],
    )
    session = Mock()
    session.scalar.return_value = None
    session.scalars.return_value = []
    session.get.return_value = None
    monkeypatch.setattr(diagnosis_event_writes.smap, "fetch_evidence", lambda *_: {})
    monkeypatch.setattr(diagnosis_event_writes, "_require_report", lambda *_: None)
    diagnosis_event_writes.save_case_session_rows(session, draft.run_id, draft.producer_agent_id, draft)
    diagnosis_event_writes.save_diagnosis_events(session, draft.run_id, draft.finish(), "report")
    rows = [call.args[0] for call in session.add.call_args_list]
    assert sum(isinstance(row, CompleteEvent) for row in rows) == 4
    assert sum(isinstance(row, NarrativeLink) for row in rows) == 2
    assert any(isinstance(row, SourceEvidence) for row in rows)
    assert not any(isinstance(row, OrganizationCheck) for row in rows)


def test_resume_preserves_saved_events_without_querying_checks(event_tools, monkeypatch):
    draft, tools = event_tools
    identifier = create_event(tools["write_event"], "点灯")
    event = draft.events[identifier]
    monkeypatch.setattr(diagnosis_persistence, "_run_events", lambda *_: {identifier: event})
    monkeypatch.setattr(diagnosis_persistence, "_run_event_dicts", lambda *_: {
        identifier: {"first_text_position": 0, "participants": []}
    })
    monkeypatch.setattr(diagnosis_persistence.smap, "fetch_evidence", lambda *_: {})
    monkeypatch.setattr(diagnosis_persistence, "_evidence_payloads", lambda *_: [
        ref.model_dump() for ref in event.evidence
    ])
    draft.session.diagnosis = SimpleNamespace(session_rows=lambda _: {"links": []})
    recovered = EventOrganizationDraft(draft.session, draft.run_id, draft.agent_id)
    diagnosis_persistence.hydrate_draft_from_run(draft.session, draft.run_id, recovered)
    assert recovered.events[identifier] == event
    assert not hasattr(recovered, "reviewed_events") and not hasattr(recovered, "structure_reviews")
    session = Mock()
    session.scalars.return_value = []
    rows = diagnosis_publish.session_rows(session, draft.run_id)
    assert set(rows) == {"agent", "links"}
    assert all("event_checks" not in str(call.args[0]) for call in session.scalars.call_args_list)
