"""当前正式程序的绑定面、检索投影与逐操作审计测试"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import _build_tool_batch_node, build_annotation_graph
from src.agents.annotation.program import PROGRAM_TOOL_NAME, ProgramRuntime, build_program_tool
from src.agents.annotation.prompts import build_chapter_message, build_subagent_message
from src.agents.annotation.schema import ChapterParagraphInfo, TextSearchResult
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools
from tests.support.model_stream_adapter import StreamedFakeModelMixin


class _QueryService:
    async def search_text(self, query: str, *, range_name: str, limit: int = 50) -> list[TextSearchResult]:
        assert range_name == "all"
        return [
            TextSearchResult(chapter_id=2, paragraph_ids=[index + 10], content=f"顾霜喝止众人-{index}",
                             keyword_score=1.0, semantic_score=0.8)
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
        run_scope="run-1", current_chapter_id=1, current_chapter_text=text, allow_future_context=True,
        graph=FactGraph(run_scope="run-1"),
        paragraph_info=ChapterParagraphInfo(paragraph_ids=[1], char_spans=[(0, len(text))], texts=[text]),
    )


def _surface(ledger: AnnotationToolLedger, observer: Any = None) -> tuple[ProgramRuntime, Any, list[Any]]:
    tools = build_annotation_tools(_QueryService(), ledger)
    runtime = ProgramRuntime(tools, ledger, observer=observer)
    return runtime, build_program_tool(runtime), tools


def _call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def test_catalog_is_current_formal_tool_surface() -> None:
    _, program_tool, tools = _surface(_ledger())
    assert {tool.name for tool in tools} == {
        "search_text", "write_entity", "write_metrics", "write_event", "write_relation", "write_dialogue",
        "push_case", "finish",
        "read_text", "read_chapter_text", "anchor_record", "write_link",
    }
    assert program_tool.name == PROGRAM_TOOL_NAME
    for tool in tools:
        assert tool.name + "(" in program_tool.description
    assert "chapter_id" in program_tool.description
    assert "capability" in program_tool.description
    assert "search_pool(" not in program_tool.description
    assert "promise_case(" not in program_tool.description
    assert "fields" in program_tool.description and "limit" in program_tool.description


@pytest.mark.parametrize("empty", [False, True])
def test_dialogue_candidate_prompts_report_actual_total(empty: bool) -> None:
    ledger = _ledger()
    candidates = [] if empty else ledger.dialogue_candidates
    messages = [
        build_chapter_message(chapter_text=ledger.current_chapter_text, candidates=candidates),
        build_subagent_message(
            role="dialogue", paragraph_info=ledger.paragraph_info, candidates=candidates, role_scope="",
        ),
    ]
    for message in messages:
        block = message.split("<DialogueCandidates>\n", 1)[1].split("\n</DialogueCandidates>", 1)[0]
        total, payload = block.split("\n", 1)
        assert total == f"total: {len(candidates)}"
        assert len(json.loads(payload)) == len(candidates)


def test_link_pairing_table_is_visible_in_schema_and_program_parameters() -> None:
    _, program_tool, tools = _surface(_ledger())
    link = next(tool for tool in tools if tool.name == "write_link")
    schema = link.args_schema.model_json_schema()
    for field in ("kind", "change_kind"):
        description = schema["properties"][field]["description"]
        assert "same_entity / different_entity / causal / foreshadowing | 省略或 None" in description
        assert (
            "relation_change | 必填 assert / reinforce / weaken / refine / break / supersede / retract" in description
        )
    assert "relation_change | 必填" in program_tool.description
    assert "自动绑定" in program_tool.description
    assert schema["properties"]["change_kind"]["default"] is None


@pytest.mark.asyncio
async def test_graph_binds_execute_code_and_finish_and_completes_chapter() -> None:
    ledger = _ledger()
    _, program_tool, tools = _surface(ledger)
    finish_tool = next(tool for tool in tools if tool.name == "finish")
    llm = _ProgramLLM(AIMessage(content="", tool_calls=[
        _call(PROGRAM_TOOL_NAME, {"code": 'write_metrics(summary="当前章", emotional_valence=0, '
                                        'narrative_function="铺垫")\n'
                                        'for candidate in [1, 2]:\n'
                                        '    write_dialogue(candidate_index=candidate, verdict="dialogue")'}, "p1"),
        _call("finish", {}, "f1"),
    ]))
    graph = build_annotation_graph(
        llm, [program_tool, *tools], ledger=ledger, max_iterations=2,
        bind_tools=[program_tool, finish_tool], program_tool_name=PROGRAM_TOOL_NAME,
    )
    state = await graph.ainvoke({"messages": [HumanMessage(content="标注本章")], "phase": "chapter_open",
                                "iterations": 0, "error": None})
    assert llm.bound_names == [PROGRAM_TOOL_NAME, "finish"]
    assert state["phase"] == "completed" and state["error"] is None
    assert len(ledger.completed_chapters) == 1


@pytest.mark.asyncio
async def test_direct_current_tools_use_same_dispatcher_and_unknown_call_is_isolated() -> None:
    ledger = _ledger()
    observer = _RecordingObserver()
    _, program_tool, tools = _surface(ledger, observer)
    batch = _build_tool_batch_node([program_tool, *tools], ledger=ledger, observer=observer,
                                   program_tool_name=PROGRAM_TOOL_NAME)
    result = await batch({"messages": [AIMessage(content="", tool_calls=[
        _call("unknown_tool", {}, "bad"),
        _call("write_entity", {"el": "a1", "name": "顾霜", "entity_type": "character"}, "entity"),
        _call("write_metrics", {"summary": "当前章", "emotional_valence": 0, "narrative_function": "铺垫"}, "m"),
        _call("write_dialogue", {"candidate_index": 1, "verdict": "dialogue", "speaker": "a1"}, "d1"),
        _call("write_dialogue", {"candidate_index": 2, "verdict": "dialogue"}, "d2"),
        _call("finish", {}, "f"),
    ])], "phase": "chapter_open", "iterations": 1, "error": None})
    receipts = [json.loads(message.content) for message in result["messages"]]
    assert receipts[0]["accepted"] is False
    assert receipts[1]["status"] == "written"
    assert receipts[-1]["status"] == "completed"
    assert ledger.chapter_finished
    entity_row = next(row for row in observer.rows if row["tool_name"] == "write_entity")
    assert entity_row["request_args"]["_program"]["direct_fallback"] is True
    assert observer.closed == 1


@pytest.mark.asyncio
async def test_native_batch_protocol_error_rejects_whole_batch() -> None:
    ledger = _ledger()
    tools = build_annotation_tools(_QueryService(), ledger)
    result = await _build_tool_batch_node(tools, ledger=ledger)({
        "messages": [AIMessage(content="", tool_calls=[
            _call("unknown_tool", {}, "bad"),
            _call("write_entity", {"el": "a1", "name": "顾霜", "entity_type": "character"}, "entity"),
        ])], "phase": "chapter_open", "iterations": 1, "error": None,
    })
    assert ledger.written_entities == {}
    assert all(json.loads(message.content)["accepted"] is False for message in result["messages"])


@pytest.mark.asyncio
async def test_audit_rows_carry_program_meta_and_inner_call_index() -> None:
    observer = _RecordingObserver()
    runtime, _, _ = _surface(_ledger(), observer)
    result = json.loads(await runtime.execute(
        'write_entity(el="a1", name="顾霜", entity_type="character")\n'
        'search_text(query="顾霜", fields=["nope"])'
    ))
    assert result["applied"] == 1
    assert result["failed"][0]["code"] == "unknown_field"
    entity_row, search_row = observer.rows
    assert entity_row["call_index"] >= 1000
    assert search_row["call_index"] > entity_row["call_index"]
    assert entity_row["request_args"]["_program"] == {
        "program_id": "p1", "op_index": 1, "source_line": 1, "record": "entity/顾霜", "direct_fallback": False,
    }
    assert search_row["request_args"]["_program"]["error_code"] == "unknown_field"
    assert search_row["status"] == "error"


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
@pytest.mark.parametrize(("options", "field", "error_code"), [
    ('fields="content"', "fields", "invalid_value"),
    ('fields=["nope"]', "fields", "unknown_field"),
    ("limit=true", "limit", "invalid_value"),
    ("limit=99", "limit", "out_of_range"),
])
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
