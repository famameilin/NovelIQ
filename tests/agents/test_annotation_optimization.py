"""真实标注工具的坐标、压缩回执、结构化写入与收尾回归"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.annotation import program as program_module
from src.agents.annotation.program import build_program_tool
from src.agents.annotation.schema import ChapterParagraphInfo, EventParticipantRole, RoleFunction
from src.agents.annotation.subagent_graph import build_subagent_graph
from src.agents.annotation.subagent_ir import SubagentAnnotation
from src.agents.annotation.subagent_runtime import SubagentProgramRuntime
from src.agents.annotation.tool_batch import _build_tool_batch_node
from src.agents.annotation.tools import AnnotationToolLedger
from src.event_trees.submission import build_event_submission_tool
from src.fact_graph.graph import FactGraph
from tests.support.annotation_work_tools import build_annotation_tools
from tests.support.annotation_work_tools import build_program_test_runtime as ProgramRuntime
from tests.support.model_stream_adapter import StreamedFakeModelMixin


class _QueryService:
    async def search_text(self, query: str, *, range_name: str, limit: int = 50) -> list[Any]:
        return []


def _ledger(texts: list[str] | None = None) -> AnnotationToolLedger:
    texts = texts or ["阿青举起长刀。", "阿青走进院门。"]
    spans = []
    offset = 0
    for text in texts:
        spans.append((offset, offset + len(text)))
        offset += len(text)
    return AnnotationToolLedger(
        run_scope="optimized-run", current_chapter_id=24, current_chapter_text="".join(texts),
        allow_future_context=True, graph=FactGraph(run_scope="optimized-run"),
        paragraph_info=ChapterParagraphInfo(
            paragraph_ids=list(range(201, 201 + len(texts))), char_spans=spans, texts=texts,
        ),
    )


def _runtime(ledger: AnnotationToolLedger, role: str | None = None, *, observer: Any = None) -> Any:
    tools = build_annotation_tools(_QueryService(), ledger)
    if role is None:
        return ProgramRuntime(tools, ledger, observer=observer)
    ledger.role = role
    subagent = SubagentAnnotation(role=role)
    ledger.finish_work.__self__.subagent = subagent
    return SubagentProgramRuntime(
        {tool.name: tool for tool in tools}, ledger, subagent, observer=observer,
    )


def _root(identifier: str = "opening", *, paragraph_id: int = 1) -> dict[str, Any]:
    return {
        "id": identifier, "description": "阿青举起长刀", "evidence": {"paragraph_id": paragraph_id},
        "participants": [{
            "name": "阿青", "entity_type": "character", "role": "主体",
            "narrative_role": "主体", "action": "举起长刀", "emotion": 0,
        }],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, "event"])
async def test_structured_events_resolve_dependencies_and_anchor_real_paragraphs(role: str | None) -> None:
    ledger = _ledger()
    runtime = _runtime(ledger, role)
    tool = build_event_submission_tool(runtime)
    child = _root("enter", paragraph_id=2)
    child.update(root_id="opening", type="main", description="阿青进入院门")
    child["participants"][0]["action"] = "走进院门"
    body = json.loads(await tool.ainvoke({"events": [child, _root()]}))

    assert body["status"] == "applied", body
    assert [item["status"] for item in body["items"]] == ["written", "written"]
    assert len(ledger.event_trees) == 1
    assert len(ledger.bound_payloads["events"]) == 2
    assert {event.evidence_paragraph_id for event in ledger.bound_payloads["events"]} == {201, 202}
    assert set(ledger.written_entities) == {"阿青"}
    for item in body["items"]:
        record = ledger.production_record_key(item["record"])
        assert ledger.source_anchors[record][0].paragraph_id in {201, 202}
        assert ledger.source_anchors[record][0].chapter_id == 24
    # 同一项重提不新增树或节点；未提供参与者时保留已提交集合
    retry = json.loads(await tool.ainvoke({"events": [{
        "id": "enter", "root_id": "opening", "type": "main", "description": "阿青进入院门",
        "evidence": {"paragraph_id": 2},
    }]}))
    assert retry["items"][0]["status"] == "written"
    assert len(ledger.bound_payloads["events"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, "event"])
async def test_bad_item_does_not_reject_batch_and_only_failed_items_need_resubmission(role: str | None) -> None:
    ledger = _ledger()
    tool = build_event_submission_tool(_runtime(ledger, role))
    bad = _root("bad")
    bad["participants"][0]["emotion"] = "愤怒"
    child = {"id": "child", "root_id": "bad", "type": "main", "description": "入门",
             "evidence": {"paragraph_id": 2}}
    healthy = {"id": "healthy", "description": "院门敞开", "evidence": {"paragraph_id": 2}}
    body = json.loads(await tool.ainvoke({"events": [bad, child, healthy]}))

    assert body["status"] == "partial", body
    assert [item["status"] for item in body["items"]] == ["failed", "waiting", "written"]
    assert "events[0].participants.0.emotion" in body["items"][0]["failed"][0]["field"]
    assert len(ledger.bound_payloads["events"]) == 1
    bad["participants"][0]["emotion"] = 0
    repaired = json.loads(await tool.ainvoke({"events": [bad, child]}))
    assert repaired["status"] == "applied", repaired
    assert len(ledger.bound_payloads["events"]) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, "event"])
async def test_participant_state_defaults_and_normalization_lands_partial_trio(role: str | None) -> None:
    """2026-10-04 程序面合同放开（与 write_event.characters 同口径）：character 三态可省略/写偏

    role 省略按登记类型默认（character→主体）、叙事功能近义词归一（主角→主体）、
    情绪分值越界钳制（9→2）；缺省三态按空落账，不再以"必须同时提供"整组判拒。
    """
    ledger = _ledger()
    tool = build_event_submission_tool(_runtime(ledger, role))
    sparse = _root("sparse")
    sparse["participants"][0] = {
        "name": "阿青", "entity_type": "character", "narrative_role": "主角", "emotion": 9,
    }
    body = json.loads(await tool.ainvoke({"events": [sparse]}))

    assert body["status"] == "applied", body
    assert body["items"][0]["status"] == "written"
    observation = ledger.bound_payloads["character_observations"][0]
    assert observation.role_function == RoleFunction.SUBJECT
    assert observation.emotion == 2
    assert observation.action is None
    assert ledger.bound_payloads["events"][0].participants[0].role == EventParticipantRole.SUBJECT


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, "event"])
async def test_participant_field_misuse_still_rejected_on_submission(role: str | None) -> None:
    """2026-10-04 放开后拒绝面只留字段误用：事件角色词进叙事功能、地点角色配非 location、
    非 character 携带三态，与正式参与者校验同一口径"""
    ledger = _ledger()
    tool = build_event_submission_tool(_runtime(ledger, role))
    misuse = _root("misuse")
    misuse["participants"][0]["narrative_role"] = "行动者"
    location_role = _root("location_role")
    location_role["participants"][0]["role"] = "地点"
    noncharacter = _root("noncharacter")
    noncharacter["participants"][0] = {"name": "院门", "entity_type": "item", "role": "客体", "emotion": 1}
    body = json.loads(await tool.ainvoke({"events": [misuse, location_role, noncharacter]}))

    assert body["status"] == "partial", body
    assert all(item["status"] == "failed" for item in body["items"])
    assert not ledger.bound_payloads.get("events")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, "event"])
async def test_child_before_root_waits_in_ledger_until_root_arrives(role: str | None) -> None:
    """2026-10-04 程序面树键校验下沉：子事件先于树根提交不再 pending_dependency 判拒

    账本挂起（根建好后按到达序冲账），回执 waiting + note；waiting 项重提按更新处理
    把参与者补齐，同 id 重提不新增节点。
    """
    ledger = _ledger()
    tool = build_event_submission_tool(_runtime(ledger, role))
    child = {"id": "enter", "root_id": "opening", "type": "main", "description": "阿青进入院门",
             "evidence": {"paragraph_id": 2}}
    body = json.loads(await tool.ainvoke({"events": [child]}))

    assert body["status"] == "applied", body
    assert body["items"][0]["status"] == "waiting"
    assert "挂起" in body["items"][0]["note"]
    assert not ledger.bound_payloads.get("events")

    root_body = json.loads(await tool.ainvoke({"events": [_root()]}))
    assert root_body["items"][0]["status"] == "written"
    assert len(ledger.bound_payloads["events"]) == 2

    retry_participant = dict(_root()["participants"][0])
    retry_participant.update(action="走进院门", emotion=1)
    retry = json.loads(await tool.ainvoke({"events": [{**child, "participants": [retry_participant]}]}))
    assert retry["items"][0]["status"] == "written"
    assert len(ledger.bound_payloads["events"]) == 2
    assert ledger.bound_payloads["events"][1].participants[0].entity == "阿青"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, "event"])
@pytest.mark.parametrize("production_key", [
    "batch_deadbeef", "batch_deadbeef/root", "event:batch_deadbeef/root", "event/event/batch_deadbeef/root",
])
async def test_submission_rejects_production_root_keys_per_item(role: str | None, production_key: str) -> None:
    ledger = _ledger()
    runtime = _runtime(ledger, role)
    tool = build_event_submission_tool(runtime)
    bad = {"id": "enter", "root_id": production_key, "type": "main", "description": "阿青进入院门",
           "evidence": {"paragraph_id": 2}}
    body = json.loads(await tool.ainvoke({"events": [bad, _root()]}))
    assert [item["status"] for item in body["items"]] == ["failed", "written"], body
    (failure,) = body["items"][0]["failed"]
    assert failure["record"] == "submission/enter"
    assert failure["field"] == "events[0].root_id"
    assert production_key in failure["message"]
    assert not ledger.pending_child_events
    assert len(ledger.bound_payloads["events"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, "event"])
async def test_correct_child_resubmission_clears_only_exact_stale_pending_matches(role: str | None) -> None:
    ledger = _ledger()
    tool = build_event_submission_tool(_runtime(ledger, role))
    child = {"id": "enter", "root_id": "wrong_root", "type": "main", "description": "阿青进入院门",
             "evidence": {"paragraph_id": 2}}
    initial = json.loads(await tool.ainvoke({"events": [child, {**child, "id": "other_node"}]}))
    assert all(item["status"] == "waiting" for item in initial["items"])
    await tool.ainvoke({"events": [{**child, "root_id": "other_wrong", "description": "阿青守住院门"}]})
    await tool.ainvoke({"events": [{**child, "root_id": "third_wrong"}]})
    before = sum(len(items) for items in ledger.pending_child_events.values())
    stale = copy.deepcopy(next(iter(ledger.pending_child_events.values()))[0])
    assert before == 4
    corrected = json.loads(await tool.ainvoke({"events": [_root(), {**child, "root_id": "opening"}]}))
    assert all(item["status"] == "written" for item in corrected["items"]), corrected
    remaining = [item for items in ledger.pending_child_events.values() for item in items]
    assert len(remaining) == 2
    assert sorted(item["description"] for item in remaining) == ["阿青守住院门", "阿青进入院门"]
    assert len(ledger.bound_payloads["events"]) == 2
    ledger.pending_child_events["old_run_bucket"] = [stale]
    rewritten = json.loads(await tool.ainvoke({"events": [{**child, "root_id": "opening"}]}))
    assert rewritten["items"][0]["status"] == "written", rewritten
    assert "old_run_bucket" not in ledger.pending_child_events
    assert sum(len(items) for items in ledger.pending_child_events.values()) == 2
    assert len(ledger.bound_payloads["events"]) == 2


@pytest.mark.asyncio
async def test_failed_child_resubmission_restores_pending_and_does_not_add_node() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    await runtime.execute('write_event(el="wrong/e1", isroot=False, type="main", description="进入院门", evidence=2)\n'
                          'write_event(el="t1", isroot=True, description="阿青举刀", evidence=1)')
    before = copy.deepcopy(ledger.pending_child_events)
    receipt = json.loads(await runtime.execute(
        'write_event(el="t1/e1", isroot=False, type="main", description="进入院门", evidence=2, '
        'characters=[{"entityid": "unregistered"}])'
    ))
    assert receipt["status"] == "partial", receipt
    assert ledger.pending_child_events == before
    assert len(ledger.bound_payloads["events"]) == 1




@pytest.mark.asyncio
async def test_subagent_dialogue_preflight_rejects_entire_out_of_range_batch() -> None:
    ledger = _ledger(["“住手！”顾霜喝道。", "“退下。”众人散去。"])
    runtime = _runtime(ledger, "dialogue")
    body = json.loads(await runtime.execute('for index in [1, 99]:\n'
                                           '    dialogue(candidate_index=index, verdict="not_dialogue")'))
    assert body["status"] == "rejected", body
    assert body["error"]["type"] == "candidate_index_out_of_range"
    assert "total=2" in body["error"]["message"]
    assert not ledger.written_dialogues and not runtime.subagent.dialogues
    assert runtime.ops == [] and runtime.env == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, "dialogue"])
async def test_zero_candidate_preflight_reports_empty_range(role: str | None) -> None:
    ledger = _ledger()
    runtime = _runtime(ledger, role)
    name = "write_dialogue" if role is None else "dialogue"
    body = json.loads(await runtime.execute(f'{name}(candidate_index=1, verdict="not_dialogue")'))
    assert body["status"] == "rejected", body
    assert "total=0" in body["error"]["message"]
    assert "无可用候选" in body["error"]["message"]
    assert not runtime.ops


@pytest.mark.asyncio
async def test_invalid_quote_and_duplicate_ids_are_rejected_without_losing_good_events() -> None:
    ledger = _ledger()
    tool = build_event_submission_tool(_runtime(ledger))
    bad = _root()
    bad["evidence"]["quote"] = "这句原文并不存在"
    healthy = {"id": "healthy", "description": "入门", "evidence": {"paragraph_id": 2}}
    body = json.loads(await tool.ainvoke({"events": [bad, healthy, copy.deepcopy(healthy)]}))
    assert [item["status"] for item in body["items"]] == ["failed", "written", "failed"]
    assert not ledger.written_entities
    assert len(ledger.bound_payloads["events"]) == 1


@pytest.mark.asyncio
async def test_structured_submission_keeps_program_operation_limit_and_prior_success(monkeypatch) -> None:
    ledger = _ledger()
    tool = build_event_submission_tool(_runtime(ledger))
    monkeypatch.setattr(program_module, "_PROGRAM_MAX_OPS", 2)
    body = json.loads(await tool.ainvoke({"events": [_root(), _root("later")]}))
    assert body["error"]["type"] == "too_many_ops"
    assert set(ledger.written_entities) == {"阿青"}
    assert not ledger.bound_payloads.get("events")
    assert [item["id"] for item in body["items"]] == ["opening", "later"]
    assert all(item["status"] == "waiting" for item in body["items"])
    monkeypatch.setattr(program_module, "_PROGRAM_MAX_OPS", 300)
    body = json.loads(await tool.ainvoke({"events": [_root()]}))
    assert body["status"] == "applied", body
    assert len(ledger.bound_payloads["events"]) == 1


class _RecordingObserver:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.closed = 0

    def record_tool_call(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)

    def close_turn(self) -> None:
        self.closed += 1


@pytest.mark.asyncio
async def test_structured_item_failures_are_audited_and_native_submission_is_not_fallback() -> None:
    ledger = _ledger()
    observer = _RecordingObserver()
    runtime = _runtime(ledger, observer=observer)
    event_tool = build_event_submission_tool(runtime)
    batch = _build_tool_batch_node(
        [build_program_tool(runtime), event_tool], ledger=ledger, observer=observer,
        program_tool_name="execute_code",
    )
    bad = _root("bad")
    bad["participants"][0]["emotion"] = "愤怒"
    reply = AIMessage(content="", tool_calls=[{
        "name": "submit_events", "args": {"events": [bad, _root()]}, "id": "e1", "type": "tool_call",
    }])
    await batch({"messages": [reply], "phase": "chapter_open", "iterations": 0, "error": None})

    failure = next(row for row in observer.rows if row["status"] == "error")
    assert failure["tool_name"] == "submit_events"
    assert failure["request_args"]["_program"]["record"] == "submission/bad"
    assert failure["receipt"]["field"] == "events[0].participants.0.emotion"
    assert "emotion" in failure["error"]
    assert ledger.errors
    assert len(ledger.bound_payloads["events"]) == 1
    native = next(row for row in observer.rows if row["tool_name"] == "submit_events" and row["call_index"] == 0)
    assert "_program" not in native["request_args"]
    assert observer.closed == 1


@pytest.mark.asyncio
async def test_compressed_reads_keep_every_reference_and_persistent_variable(monkeypatch) -> None:
    ledger = _ledger(["阿青" + "原文" * 1000 for _ in range(11)])
    runtime = _runtime(ledger)
    monkeypatch.setattr(program_module, "_READ_ECHO_MAX_ITEMS", 2)
    monkeypatch.setattr(program_module, "_READ_ECHO_MAX_CHARS", 80)
    body = json.loads(await runtime.execute(
        'person = write_entity(el="a1", name="阿青", entity_type="character")\n'
        'first = read_chapter_text(paragraph_id=1)\n'
        + "\n".join(f"read_chapter_text(paragraph_id={identifier})" for identifier in range(2, 12))
    ))
    assert body["status"] == "applied", body
    assert body["reads_omitted"] == 9
    assert len(body["reads"]) == 2
    assert len(body["references"]) == 11
    assert body["variables"]["first"]["paragraph_id"] == 201
    for read in body["reads"]:
        result = json.loads(read["result"])
        assert len(result["source_ref"]) == 64
        assert result["paragraph_id"] in {210, 211}
        assert read["truncated_chars"] > 0
    repaired = json.loads(await runtime.execute(
        'anchor_record(record_id=person["record"], source_ref=first["source_ref"])'
    ))
    assert repaired["status"] == "applied"
    assert ledger.source_anchors["entity/阿青"][0].paragraph_id == 201


class _Replies(StreamedFakeModelMixin):
    def __init__(self, replies: list[AIMessage]) -> None:
        self.replies = replies
        self.requests = 0
        self.bound_names: list[str] = []

    def bind_tools(self, tools: list[Any]) -> _Replies:
        self.bound_names = [str(tool.name) for tool in tools]
        return self

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        reply = self.replies[self.requests]
        self.requests += 1
        return reply


def _program_reply(code: str, identifier: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{
        "name": "execute_code", "args": {"code": code}, "id": identifier, "type": "tool_call",
    }])


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["structure", "event"])
async def test_clean_subagent_finish_stops_without_another_model_request(role: str) -> None:
    ledger = _ledger()
    runtime = _runtime(ledger, role)
    model = _Replies([_program_reply("finish()", "p1")])
    graph = build_subagent_graph(
        model, runtime.build_tool(), runtime.finish_tool, ledger=ledger, subagent=runtime.subagent, max_iterations=5,
    )
    await graph.ainvoke({"messages": [HumanMessage(content="完成")], "phase": "chapter_open",
                        "iterations": 0, "error": None})
    assert model.requests == 1


@pytest.mark.asyncio
async def test_finish_closes_work_after_rejected_optional_event() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger, "event")
    model = _Replies([
        _program_reply('event(el="t1", isroot=True, type="main", description="举刀", evidence=1)\nfinish()', "p1"),
        _program_reply('event(el="t1", isroot=True, description="举刀", evidence=1)', "p2"),
        _program_reply("finish()", "p3"),
    ])
    graph = build_subagent_graph(
        model, runtime.build_tool(), runtime.finish_tool, ledger=ledger, subagent=runtime.subagent, max_iterations=5,
    )
    await graph.ainvoke({"messages": [HumanMessage(content="完成")], "phase": "chapter_open",
                        "iterations": 0, "error": None})
    assert model.requests == 1
    assert ledger.chapter_finished
    assert ledger.bound_payloads["events"] == []


@pytest.mark.asyncio
async def test_evidence_finish_requires_its_own_metric() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger, "evidence")
    model = _Replies([
        _program_reply("finish()", "p1"),
        _program_reply('metric(summary="阿青入门", emotional_valence=0, narrative_function="铺垫")\nfinish()', "p2"),
    ])
    graph = build_subagent_graph(
        model, runtime.build_tool(), runtime.finish_tool, ledger=ledger, subagent=runtime.subagent, max_iterations=5,
    )
    await graph.ainvoke({"messages": [HumanMessage(content="完成")], "phase": "chapter_open",
                        "iterations": 0, "error": None})
    assert model.requests == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_call", [
    {"name": "unknown_tool", "args": {}},
    {"name": "execute_code", "args": {
        "code": 'event(el="t1", isroot=True, type="main", description="举刀", evidence=1)',
    }},
])
async def test_rejected_call_does_not_reopen_successfully_finished_work(failed_call: dict[str, Any]) -> None:
    ledger = _ledger()
    runtime = _runtime(ledger, "event")
    model = _Replies([
        AIMessage(content="", tool_calls=[
            {**failed_call, "id": "bad", "type": "tool_call"},
            {"name": "finish", "args": {}, "id": "f1", "type": "tool_call"},
        ]),
        AIMessage(content="完成"),
    ])
    graph = build_subagent_graph(
        model, runtime.build_tool(), runtime.finish_tool, ledger=ledger, subagent=runtime.subagent, max_iterations=5,
    )
    await graph.ainvoke({"messages": [HumanMessage(content="完成")], "phase": "chapter_open",
                        "iterations": 0, "error": None})
    assert model.requests == 1
    assert runtime.subagent.finished is True
    assert ledger.chapter_finished


@pytest.mark.asyncio
async def test_subagent_graph_binds_structured_events_and_finishes_in_one_request() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger, "event")
    model = _Replies([AIMessage(content="", tool_calls=[
        {"name": "submit_events", "args": {"events": [_root()]}, "id": "e1", "type": "tool_call"},
        {"name": "finish", "args": {}, "id": "f1", "type": "tool_call"},
    ])])
    graph = build_subagent_graph(
        model, runtime.build_tool(), runtime.finish_tool, ledger=ledger, subagent=runtime.subagent,
        max_iterations=5, event_submission_tool=build_event_submission_tool(runtime),
    )
    await graph.ainvoke({"messages": [HumanMessage(content="完成")], "phase": "chapter_open",
                        "iterations": 0, "error": None})
    assert model.requests == 1
    assert "submit_events" in model.bound_names
    assert len(ledger.bound_payloads["events"]) == 1
    assert runtime.subagent.finished is True
