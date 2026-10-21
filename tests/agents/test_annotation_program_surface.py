"""当前正式程序的绑定面、检索投影与逐操作审计测试"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.program_contract import PROGRAM_TOOL_NAME
from src.agents.annotation.prompts import build_agent_message
from src.agents.annotation.text_search import TextSearchCandidate
from src.agents.annotation.tool_batch import _build_tool_batch_node
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import ChapterParagraphInfo
from tests.support.annotation_work_tools import build_annotation_tools
from tests.support.annotation_work_tools import build_program_test_runtime as ProgramRuntime
from tests.support.model_stream_adapter import StreamedFakeModelMixin


class _QueryService:
    async def search_text(self, query: str, *, range_name: str, limit: int = 50) -> list[TextSearchCandidate]:
        assert range_name == "all"
        return [
            TextSearchCandidate(
                chapter_id=2,
                paragraph_id=index + 10,
                excerpt=f"顾霜喝止众人-{index}",
                keyword_score=1.0,
                semantic_score=0.8,
            )
            for index in range(5)
        ]


class _RecordingObserver:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.closed = 0

    def record_tool_call(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)

    def close_turn(self) -> None:
        self.closed += 1


class _ProgramLLM(StreamedFakeModelMixin):
    def __init__(self, reply: AIMessage) -> None:
        self.reply = reply
        self.bound_names: list[str] = []

    def bind_tools(self, tools: list[Any]) -> _ProgramLLM:
        self.bound_names = [str(tool.name) for tool in tools]
        return self

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        return self.reply


def _ledger() -> AnnotationToolLedger:
    text = "“住手！”顾霜喝道。“退下。”众人散去。"
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chapter_text=text,
        allow_future_context=True,
        graph=FactGraph(run_scope="run-1"),
        paragraph_info=ChapterParagraphInfo(paragraph_ids=[1], char_spans=[(0, len(text))], texts=[text]),
    )


def _surface(ledger: AnnotationToolLedger, observer: Any = None) -> tuple[ProgramRuntime, Any, list[Any]]:
    tools = build_annotation_tools(_QueryService(), ledger)
    runtime = ProgramRuntime(tools, ledger, observer=observer)
    return runtime, runtime.build_tool(), tools


def _call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def test_catalog_is_current_formal_tool_surface() -> None:
    _, program_tool, tools = _surface(_ledger())
    assert {tool.name for tool in tools} == {
        "search_text",
        "write_entity",
        "write_metrics",
        "write_event",
        "write_plotline",
        "write_foreshadowing_action",
        "write_relation",
        "write_dialogue",
        "push_case",
        "claim_case",
        "claim_random_case",
        "submit_case",
        "search_cases",
        "search_events",
        "search_graph",
        "finish",
        "read_text",
        "read_chapter_text",
        "anchor_record",
        "write_link",
        "read_event",
        "read_entity",
    }
    assert program_tool.name == PROGRAM_TOOL_NAME
    for name in ("entity", "relation", "event", "participants", "dialogue", "label", "metric", "pending"):
        assert name + "(" in program_tool.description
    assert "search_pool(" not in program_tool.description
    assert "claim_case(" in program_tool.description
    assert "limit" in program_tool.description


async def test_case_program_preserves_claim_status_and_exposes_submission_candidates():
    runtime, _, _ = _surface(_ledger())
    first = json.loads(await runtime.execute(
        'a = push_case(case_type="event", description="检查第一件")\n'
        'b = push_case(case_type="event", description="检查第二件")\n'
        'claimed = claim_case(case_id=a["ref"]["case_id"])\n'
        'submitted = submit_case(case_id=claimed["case_id"])',
        "outer-case-context",
    ))
    assert not first.get("failed"), first
    assert runtime.env["claimed"]["status"] == "claimed"
    assert runtime.env["submitted"]["status"] == "submitted"
    offered = runtime.env["submitted"]["candidates"]
    assert offered and first["cases"][-1]["result"]["candidates"] == offered
    second = json.loads(await runtime.execute(
        'next_case = claim_case(case_id=submitted["candidates"][0]["case_id"])\n'
        'submit_case(case_id=next_case["case_id"])'
    ))
    assert not second.get("failed"), second
    assert second["cases"][-1]["result"]["candidates"] == []


@pytest.mark.parametrize("empty", [False, True])
def test_dialogue_candidate_prompts_report_actual_total(empty: bool) -> None:
    ledger = _ledger()
    candidates = [] if empty else ledger.dialogue_candidates
    messages = [
        build_agent_message(
            role="dialogue",
            paragraph_info=ledger.paragraph_info,
            candidates=candidates,
            role_scope="",
            chapter_id=ledger.current_chapter_id,
            chapter_order=ledger.current_chapter_order,
        ),
    ]
    for message in messages:
        block = message.split("<DialogueCandidates>\n", 1)[1].split("\n</DialogueCandidates>", 1)[0]
        total, payload = block.split("\n", 1)
        assert total == f"total: {len(candidates)}"
        assert len(json.loads(payload)) == len(candidates)


def test_link_schema_uses_actual_entity_or_event_ids() -> None:
    _, program_tool, tools = _surface(_ledger())
    link = next(tool for tool in tools if tool.name == "write_link")
    schema = link.args_schema.model_json_schema()
    assert {"source_id", "target_id", "kind"} <= set(schema["required"])
    assert "source_ref" not in schema["properties"]
    assert "record_id" not in schema["properties"]
    assert schema["properties"]["kind"]["enum"] == [
        "causal",
        "foreshadowing",
        "same_entity",
        "different_entity",
        "relation_change",
        "contains",
    ]
    assert schema["properties"]["change_kind"]["default"] is None


def test_source_write_schemas_do_not_expose_formal_event_id_parameters() -> None:
    """章级写入只引用声明，正式身份仅在诊断发布后存在"""
    _, program_tool, tools = _surface(_ledger())
    schemas = {tool.name: tool.args_schema.model_json_schema()["properties"] for tool in tools}
    assert "event_id" in schemas["write_plotline"]
    assert {"source_event_id", "target_event_id"} <= set(schemas["write_foreshadowing_action"])
    assert "root_event_id" not in schemas["write_foreshadowing_action"]
    assert "source_event_id" in program_tool.description
    assert "target_event_id" in program_tool.description


@pytest.mark.asyncio
async def test_direct_current_tools_use_same_dispatcher_and_unknown_call_is_isolated() -> None:
    ledger = _ledger()
    observer = _RecordingObserver()
    _, program_tool, tools = _surface(ledger, observer)
    batch = _build_tool_batch_node(
        [program_tool, *tools], ledger=ledger, observer=observer, program_tool_name=PROGRAM_TOOL_NAME
    )
    result = await batch(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        _call("unknown_tool", {}, "bad"),
                        _call("write_entity", {"el": "a1", "name": "顾霜", "entity_type": "character"}, "entity"),
                        _call(
                            "write_metrics",
                            {"summary": "当前章", "emotional_valence": 0, "narrative_function": "铺垫"},
                            "m",
                        ),
                        _call("write_dialogue", {"candidate_index": 1, "verdict": "dialogue", "speaker": "a1"}, "d1"),
                        _call("write_dialogue", {"candidate_index": 2, "verdict": "dialogue"}, "d2"),
                        _call("finish", {}, "f"),
                    ],
                )
            ],
            "phase": "chapter_open",
            "iterations": 1,
            "error": None,
        }
    )
    receipts = [json.loads(message.content) for message in result["messages"]]
    assert receipts[0]["accepted"] is False
    assert receipts[1]["status"] == "written"
    assert receipts[-1]["status"] == "written"
    assert receipts[-1]["ref"]["end_requested"] is True
    assert ledger.end_requested and not ledger.chapter_finished
    entity_row = next(row for row in observer.rows if row["tool_name"] == "write_entity")
    assert entity_row["request_args"]["_program"]["direct_fallback"] is True
    assert observer.closed == 1


@pytest.mark.asyncio
async def test_native_batch_protocol_error_rejects_whole_batch() -> None:
    ledger = _ledger()
    tools = build_annotation_tools(_QueryService(), ledger)
    result = await _build_tool_batch_node(tools, ledger=ledger)(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        _call("unknown_tool", {}, "bad"),
                        _call("write_entity", {"el": "a1", "name": "顾霜", "entity_type": "character"}, "entity"),
                    ],
                )
            ],
            "phase": "chapter_open",
            "iterations": 1,
            "error": None,
        }
    )
    assert ledger.written_entities == {}
    assert all(json.loads(message.content)["accepted"] is False for message in result["messages"])


@pytest.mark.asyncio
async def test_audit_rows_carry_program_meta_and_inner_call_index() -> None:
    observer = _RecordingObserver()
    runtime, _, _ = _surface(_ledger(), observer)
    result = json.loads(
        await runtime.execute(
            'write_entity(el="a1", name="顾霜", entity_type="character")\nsearch_text(query="顾霜", fields=["nope"])'
        )
    )
    assert result["applied"] == 1
    assert result["failed"][0]["code"] == "unknown_field"
    entity_row, search_row = observer.rows
    assert entity_row["call_index"] >= 1000
    assert search_row["call_index"] > entity_row["call_index"]
    assert entity_row["request_args"]["_program"] == {
        "program_id": "p1",
        "op_index": 1,
        "source_line": 1,
        "record": "entity/顾霜",
        "direct_fallback": False,
    }
    assert search_row["request_args"]["_program"]["error_code"] == "unknown_field"
    assert search_row["error"]


@pytest.mark.asyncio
async def test_search_projection_keeps_source_capabilities_and_records_reads() -> None:
    ledger = _ledger()
    observer = _RecordingObserver()
    runtime, _, _ = _surface(ledger, observer)
    receipt = json.loads(await runtime.execute('hits = search_text(query="顾霜")'))
    results = json.loads(receipt["reads"][0]["result"])
    assert len(results) == 3
    assert set(results[0]) == {"content", "truncated", "chapter_id", "paragraph_ids", "capability"}
    assert results[0]["chapter_id"] == 2 and results[0]["paragraph_ids"] == [10]
    assert results[0]["capability"] == "other_text"
    assert ledger.authorized_text_paragraph_ids == {10, 11, 12, 13, 14}
    observer.rows.clear()
    await runtime.execute('search_text(query="顾霜", fields=["content", "keyword_score"], limit=2)')
    assert len(observer.rows[0]["receipt"]) == 2
    assert set(observer.rows[0]["receipt"][0]) == {"content", "keyword_score"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "field", "error_code"),
    [
        ('fields="content"', "fields", "invalid_value"),
        ('fields=["nope"]', "fields", "unknown_field"),
        ("limit=true", "limit", "invalid_value"),
        ("limit=99", "limit", "out_of_range"),
    ],
)
async def test_search_projection_errors_are_structured(options: str, field: str, error_code: str) -> None:
    runtime, _, _ = _surface(_ledger())
    receipt = json.loads(await runtime.execute(f'search_text(query="顾霜", {options})'))
    assert receipt["failed"][0]["field"] == field
    assert receipt["failed"][0]["code"] == error_code
    assert "reads" not in receipt


@pytest.mark.asyncio
async def test_read_echo_is_bounded() -> None:
    runtime, _, _ = _surface(_ledger())
    receipt = json.loads(await runtime.execute('search_text(query="顾霜")\n' * 9))
    assert receipt["applied"] == 9
    assert len(receipt["reads"]) == 8
    assert receipt["reads_omitted"] == 1
    assert all("result" in read for read in receipt["reads"])
