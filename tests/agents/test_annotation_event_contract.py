"""事件声明写面：完整字段、独立身份、参与者与来源约束"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.agents.annotation.errors import AnnotationStageRejection
from src.agents.annotation.ledger import AnnotationToolLedger
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import ChapterParagraphInfo
from tests.support.annotation_work_tools import build_annotation_tools, build_program_annotation_tools


def _ledger() -> AnnotationToolLedger:
    return AnnotationToolLedger(
        run_scope="run-declarations",
        current_chapter_id=1,
        current_chapter_text="甲进入山门。乙追来。",
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChapterParagraphInfo(
            paragraph_ids=[0, 1], char_spans=[(0, 6), (6, 10)], texts=["甲进入山门。", "乙追来。"]
        ),
    )


def _args(el: str = "e1", **overrides: Any) -> dict[str, Any]:
    result = {
        "el": el,
        "title": "进入山门",
        "problem": "能否进入山门",
        "summary": "甲进入山门遭乙追赶",
        "event_type": "追逐",
        "status": "ongoing",
        "progress": "甲进入山门",
        "evidence": 1,
    }
    result.update(overrides)
    return result


def _tools(ledger: AnnotationToolLedger, *, program: bool = False) -> dict[str, Any]:
    build = build_program_annotation_tools if program else build_annotation_tools
    return {tool.name: tool for tool in build(MagicMock(), ledger)}


def _call(tools: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    return json.loads(tools["write_event"].invoke(args))


@pytest.mark.parametrize("program", [False, True])
def test_complete_declaration_fields_round_trip_through_both_production_tools(program: bool) -> None:
    ledger = _ledger()
    result = _call(_tools(ledger, program=program), _args())
    event = ledger.bound_payloads["events"][0]
    assert result["status"] == "written"
    assert event.event_id == event.node_id
    assert event.parent_node_id is None
    assert event.title == "进入山门"
    assert event.problem == "能否进入山门"
    assert event.summary == "甲进入山门遭乙追赶"
    assert event.event_type == "追逐"
    assert event.status == "ongoing"
    assert event.progress == "甲进入山门"
    assert event.evidence_paragraph_id == 0
    content = result["content"]
    assert content["event_id"] == event.event_id
    assert "declaration_id" not in content


@pytest.mark.parametrize("field", ["title", "problem", "summary", "event_type", "status", "evidence"])
def test_declaration_requires_complete_business_fields(field: str) -> None:
    ledger = _ledger()
    args = _args()
    del args[field]
    with pytest.raises(ValidationError):
        _call(_tools(ledger), args)
    assert not ledger.bound_payloads.get("events")


@pytest.mark.parametrize(
    "field,value",
    [("isroot", True), ("type", "main"), ("parent_ref", "e0"), ("node_ref", "e0"), ("description", "旧逐动作参数")],
)
def test_old_process_and_implicit_parent_contract_is_rejected(field: str, value: Any) -> None:
    ledger = _ledger()
    with pytest.raises(ValidationError):
        _call(_tools(ledger, program=True), _args(**{field: value}))
    assert not ledger.bound_payloads.get("events")


def test_local_path_and_call_order_never_form_parent_containment() -> None:
    ledger = _ledger()
    tools = _tools(ledger, program=True)
    _call(tools, _args("t1/e2"))
    _call(tools, _args("t1", title="追赶", summary="乙追来", evidence=2))
    events = ledger.bound_payloads["events"]
    assert len(events) == 2
    assert not ledger.pending_child_events
    assert all(event.parent_node_id is None for event in events)
    assert len({event.event_id for event in events}) == 2


@pytest.mark.parametrize("entity_type", ["location", "organization"])
def test_participant_name_auto_registration_and_location_role(entity_type: str) -> None:
    ledger = _ledger()
    _call(_tools(ledger), _args(characters=[{"name": "山门", "entity_type": entity_type, "role": "地点"}]))
    event = ledger.bound_payloads["events"][0]
    assert len(event.participants) == 1
    assert ledger.graph.display_name(event.participants[0].entity) == "山门"
    assert str(event.participants[0].role) == "地点"


def test_same_declaration_is_idempotent_but_business_content_is_immutable() -> None:
    ledger = _ledger()
    tools = _tools(ledger)
    _call(tools, _args())
    _call(tools, _args())
    with pytest.raises(AnnotationStageRejection, match="不可改写"):
        _call(tools, _args(summary="改成另一个事件"))
    assert len(ledger.bound_payloads["events"]) == 1
    assert ledger.bound_payloads["events"][0].summary == "甲进入山门遭乙追赶"


def test_foreshadowing_and_source_anchor_survive_ledger_snapshot() -> None:
    ledger = _ledger()
    tools = _tools(ledger)
    _call(tools, _args(isforeshadowing=True, confidence="high"))
    snapshot = ledger.snapshot()
    ledger.restore(snapshot)
    event = ledger.bound_payloads["events"][0]
    assert event.is_foreshadow_setup
    assert event.payoff_likelihood == "high"
    assert event.evidence_paragraph_id == 0


def test_confidence_and_original_paragraph_are_still_validated() -> None:
    ledger = _ledger()
    tools = _tools(ledger)
    with pytest.raises(AnnotationStageRejection, match="confidence"):
        _call(tools, _args(isforeshadowing=True))
    with pytest.raises(AnnotationStageRejection, match="evidence"):
        _call(tools, _args(evidence=99))
    assert not ledger.bound_payloads.get("events")
