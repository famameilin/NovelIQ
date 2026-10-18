"""真实标注工具的坐标、压缩回执、结构化写入与收尾回归"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.annotation import program_contract
from src.agents.annotation.agent import WorkExecution
from src.agents.annotation.agent_graph import build_agent_graph
from src.agents.annotation.agent_ir import AgentAnnotation
from src.agents.annotation.agent_runtime import AgentProgramRuntime
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.tool_batch import _build_tool_batch_node
from src.agents.annotation.work_tools import build_work_tools
from src.case_pool import CasePool
from src.event_trees.models import BoundEvent
from src.event_trees.trees import EventTrees
from src.fact_graph.graph import FactGraph, entity_key
from src.fact_graph.inputs import ChapterParagraphInfo, EntityInput
from src.work.annotation_work import WorkReceipt
from tests.support.annotation_work_tools import build_annotation_tools
from tests.support.annotation_work_tools import build_program_test_runtime as ProgramRuntime
from tests.support.model_stream_adapter import StreamedFakeModelMixin
from tests.support.storage_fixtures import fixture_id


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
        run_scope="optimized-run",
        current_chapter_id=24,
        current_chapter_text="".join(texts),
        allow_future_context=True,
        graph=FactGraph(run_scope="optimized-run"),
        paragraph_info=ChapterParagraphInfo(
            paragraph_ids=list(range(201, 201 + len(texts))),
            char_spans=spans,
            texts=texts,
        ),
    )


def _runtime(ledger: AnnotationToolLedger, role: str | None = None, *, observer: Any = None) -> Any:
    tools = build_annotation_tools(_QueryService(), ledger)
    if role is None:
        return ProgramRuntime(tools, ledger, observer=observer)
    ledger.role = role
    agent = AgentAnnotation(role=role)
    ledger.finish_work.__self__.agent = agent
    return AgentProgramRuntime(
        {tool.name: tool for tool in tools},
        ledger,
        agent,
        observer=observer,
    )


def _root(identifier: str = "opening", *, paragraph_id: int = 1) -> dict[str, Any]:
    return {
        "id": identifier,
        "description": "阿青举起长刀",
        "evidence": {"paragraph_id": paragraph_id},
        "participants": [
            {
                "name": "阿青",
                "entity_type": "character",
                "role": "主体",
                "narrative_role": "主体",
                "action": "举起长刀",
                "emotion": 0,
            }
        ],
    }


def _real_work_runtime(*, role: str = "event", observer: Any = None) -> tuple[Any, Any, WorkExecution]:
    """直接装配发布全书状态的生产工具，避免领域隔离夹具掩盖暂挂回执错误"""
    ledger = _ledger()
    ledger.role = role
    work = WorkReceipt("work", ledger.run_scope, "annotation", {"chapter_id": 24, "role": role})
    execution = WorkExecution(work, "invocation", ledger, AgentAnnotation(role=role))
    cases, trees = CasePool(ledger.run_scope), EventTrees(ledger.run_scope)
    # 作者身份收敛为单字符串：真实执行号就是三域的贡献作者
    cases.begin(execution.invocation_id)
    trees.begin(execution.invocation_id)
    agent = SimpleNamespace(run_id=ledger.run_scope, case_pool=cases, event_trees=trees, fact_graph=ledger.graph)
    ledger.work_id, ledger.invocation_id = execution.work_id, execution.invocation_id
    ledger.finish_work = execution.validate
    tool_map = {tool.name: tool for tool in build_work_tools(agent, execution, _QueryService())}
    runtime = AgentProgramRuntime(tool_map, ledger, execution.agent, observer=observer)
    return runtime, agent, execution


@pytest.mark.asyncio
async def test_event_search_pages_bound_payload_and_grant_only_returned_nodes(monkeypatch) -> None:
    runtime, agent, execution = _real_work_runtime()
    trees = agent.event_trees
    trees.begin(fixture_id(__name__, "saved"))
    nodes = [
        BoundEvent(
            node_id=f"node-{index:04d}",
            tree_id=f"tree-{index % 3}",
            parent_node_id=None,
            cause_role="root",
            description=f"院门事件{index}" + "正文" * 1500,
            evidence_paragraph_id=201,
            title=f"院门事件{index}" + "正文" * 1500,
            problem="明确事件问题",
            summary=f"院门事件{index}" + "正文" * 1500,
            event_type="行动",
            status="ongoing",
            declaration_id=f"node-{index:04d}",
        )
        for index in range(247)
    ]
    trees.sync(fixture_id(__name__, "saved"), 12, nodes)
    trees.confirm(fixture_id(__name__, "saved"))
    calls = []
    original_read = trees.read

    def read(identifier: str) -> Any:
        calls.append(identifier)
        return original_read(identifier)

    monkeypatch.setattr(trees, "read", read)
    tool = runtime.tools["search_events"]
    first_text = await tool.ainvoke({"query": "院门", "limit": 20})
    first = json.loads(first_text)
    assert first["total"] == 247
    assert len(first["events"]) == 20 and first["next_offset"] == 20
    assert len(calls) == 20
    assert set(execution.event_reads) == {item["declaration_id"] for item in first["events"]}
    assert "node-0246" not in execution.event_reads
    next_page = json.loads(await tool.ainvoke({"query": "院门", "limit": 20, "offset": first["next_offset"]}))
    assert first["events"][-1]["declaration_id"] != next_page["events"][0]["declaration_id"]
    filtered = json.loads(await tool.ainvoke({"chapter_id": 12, "tree_id": "tree-2"}))
    assert all(trees.read(item["declaration_id"])["content"]["tree_id"] == "tree-2" for item in filtered["events"])
    assert json.loads(await tool.ainvoke({"chapter_id": 99}))["total"] == 0
    detail = json.loads(await runtime.tools["read_event"].ainvoke({"node_id": "node-0246"}))
    assert len(detail["content"]["description"]) > 3000
    assert execution.event_reads["node-0246"] == detail
    echo = json.loads(await runtime.execute('page = search_events(query="院门", limit=20)'))
    echoed_page = json.loads(echo["reads"][0]["result"])
    assert echoed_page == first
    assert len(echoed_page["events"]) == 20


@pytest.mark.asyncio
async def test_event_search_filters_foreshadow_roots_and_compacts_pages() -> None:
    """伏笔根标记可过滤、紧凑索引可 100/页通览：跨章引用发现不再靠全目录翻页"""
    runtime, agent, execution = _real_work_runtime()
    trees = agent.event_trees
    trees.begin(fixture_id(__name__, "saved"))
    nodes = [
        BoundEvent(
            node_id=f"node-{index:04d}",
            tree_id=f"tree-{index % 3}",
            parent_node_id=None,
            cause_role="root",
            description=f"槐叶事件{index}",
            evidence_paragraph_id=10 + index,
            title=f"槐叶事件{index}",
            problem="明确事件问题",
            summary=f"槐叶事件{index}",
            event_type="行动",
            status="ongoing",
            declaration_id=f"node-{index:04d}",
            is_foreshadow_setup=index % 2 == 0,
        )
        for index in range(130)
    ]
    trees.sync(fixture_id(__name__, "saved"), 12, nodes)
    trees.confirm(fixture_id(__name__, "saved"))
    tool = runtime.tools["search_events"]
    roots = json.loads(await tool.ainvoke({"isforeshadowing": True, "limit": 20}))
    assert roots["total"] == 65
    assert all(item["is_foreshadow_setup"] for item in roots["events"])
    non_roots = json.loads(await tool.ainvoke({"isforeshadowing": False, "limit": 20}))
    assert non_roots["total"] == 65
    assert all(not item["is_foreshadow_setup"] for item in non_roots["events"])
    roots_index = json.loads(await tool.ainvoke({"isforeshadowing": True, "compact": True, "limit": 100}))
    assert len(roots_index["events"]) == 65
    assert roots_index["next_offset"] is None
    both_index = json.loads(await tool.ainvoke({"compact": True, "limit": 100}))
    assert len(both_index["events"]) == 100 and both_index["next_offset"] == 100
    assert all("summary" not in item for item in both_index["events"])
    with pytest.raises(ValueError, match="compact=True"):
        await tool.ainvoke({"limit": 100})


@pytest.mark.asyncio
async def test_graph_search_filters_relations_pages_and_reads_attributes_on_demand() -> None:
    runtime, agent, execution = _real_work_runtime()
    graph = agent.fact_graph
    graph.register_entities([EntityInput(name=f"角色{index:02d}", entity_type="character") for index in range(50)])
    graph.register_entities([EntityInput(name="院门", entity_type="location")])
    graph.entity_attributes[entity_key("角色00", "character")] = {"description": "原文" * 5000}
    graph.active_relations.update(
        (
            entity_key(f"角色{index:02d}", "character"),
            entity_key(f"角色{index + 1:02d}", "character"),
            "认识",
        )
        for index in range(49)
    )
    tool = runtime.tools["search_graph"]
    page_text = await tool.ainvoke({"query": "角色00", "limit": 20})
    page = json.loads(page_text)
    assert page["total_entities"] == 1
    assert page["total_relations"] == 1
    assert "attributes" not in page["entities"][0]
    assert execution.ledger.shared_entity_ids == {
        graph.entity_id("角色00", "character"),
        graph.entity_id("角色01", "character"),
    }
    assert graph.entity_id("角色49", "character") not in execution.ledger.shared_entity_ids
    first = json.loads(await tool.ainvoke({"limit": 20}))
    assert 0 < len(first["entities"]) <= 20
    assert 0 < len(first["relations"]) <= 20
    assert first["next_offset"] is not None and first["next_relation_offset"] is not None
    second = json.loads(
        await tool.ainvoke(
            {
                "limit": 20,
                "offset": first["next_offset"],
                "relation_offset": first["next_relation_offset"],
            }
        )
    )
    assert first["entities"][-1]["id"] not in {item["id"] for item in second["entities"]}
    assert first["relations"][-1] not in second["relations"]
    locations = json.loads(await tool.ainvoke({"entity_type": "location"}))
    assert [item["name"] for item in locations["entities"]] == ["院门"]
    assert not locations["relations"]
    detail = json.loads(
        await runtime.tools["read_entity"].ainvoke({"entity_id": graph.entity_id("角色00", "character")})
    )
    assert detail["attributes"]["description"] == "原文" * 5000


@pytest.mark.asyncio
async def test_program_business_failure_is_audited_without_rolling_back_applied_writes() -> None:
    observer = _RecordingObserver()
    runtime, _, execution = _real_work_runtime(observer=observer)
    batch = _build_tool_batch_node(
        [runtime.build_tool()],
        ledger=execution.ledger,
        observer=observer,
        program_tool_name="execute_code",
    )
    reply = _program_reply('entity(id="a", name="阿青", entity_type="character", evidence=1)\nprint("done")', "p")
    await batch({"messages": [reply], "phase": "chapter_open", "iterations": 0, "error": None})
    row = next(row for row in observer.rows if row["call_index"] == 0)
    assert row["status"] == "error"
    assert row["receipt"]["execution_status"] == "success"
    assert row["receipt"]["business_status"] == "runtime_error"
    assert row["receipt"]["applied"] == 0
    assert entity_key("阿青", "character") not in execution.ledger.written_entities
    assert "print" in row["receipt"]["error"]["message"]
    positional = json.loads(await runtime.execute('search_graph("阿青")'))
    assert positional["error"]["type"] == "bad_call"
    assert "具名参数" in positional["error"]["message"]
    reserved = json.loads(await runtime.execute('entity = read_entity(entity_id="unknown")'))
    assert reserved["error"]["type"] == "name_reserved"
    assert "entity" in reserved["error"]["message"]


@pytest.mark.asyncio
async def test_failed_declaration_keeps_prior_source_and_does_not_add_node() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger, "event")
    await runtime.execute(
        "event(el='e1', title='进入院门', problem='能否进入', summa"  # 同一程序文本
        "ry='进入院门', event_type='行动', status='ongoing', evid"  # 同一程序文本
        "ence=2)"  # 同一程序文本
    )
    receipt = json.loads(
        await runtime.execute(
            "event(el='e2', title='错误', problem='问题', summary='"  # 同一程序文本
            "另一个声明', event_type='行动', status='ongoing', evidenc"  # 同一程序文本
            "e=99)"  # 同一程序文本
        )
    )
    assert receipt["status"] == "partial"
    assert not ledger.pending_child_events
    assert len(ledger.bound_payloads["events"]) == 1


@pytest.mark.asyncio
async def test_agent_dialogue_preflight_rejects_entire_out_of_range_batch() -> None:
    ledger = _ledger(["“住手！”顾霜喝道。", "“退下。”众人散去。"])
    runtime = _runtime(ledger, "metric")
    body = json.loads(
        await runtime.execute('for index in [1, 99]:\n    dialogue(candidate_index=index, verdict="not_dialogue")')
    )
    assert body["status"] == "rejected", body
    assert body["error"]["type"] == "candidate_index_out_of_range"
    assert "total=2" in body["error"]["message"]
    assert not ledger.written_dialogues and not runtime.agent.dialogues
    assert runtime.ops == [] and runtime.env == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, "metric"])
async def test_zero_candidate_preflight_reports_empty_range(role: str | None) -> None:
    ledger = _ledger()
    runtime = _runtime(ledger, role)
    name = "write_dialogue" if role is None else "dialogue"
    body = json.loads(await runtime.execute(f'{name}(candidate_index=1, verdict="not_dialogue")'))
    assert body["status"] == "rejected", body
    assert "total=0" in body["error"]["message"]
    assert "无可用候选" in body["error"]["message"]
    assert not runtime.ops


class _RecordingObserver:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.closed = 0

    def record_tool_call(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)

    def close_turn(self) -> None:
        self.closed += 1


@pytest.mark.asyncio
async def test_capped_reads_keep_every_reference_and_persistent_variable(monkeypatch) -> None:
    texts = ["阿青" + "原文" * 1000 for _ in range(11)]
    ledger = _ledger(texts)
    runtime = _runtime(ledger)
    monkeypatch.setattr(program_contract, "_READ_ECHO_MAX_ITEMS", 2)
    body = json.loads(
        await runtime.execute(
            'person = write_entity(el="a1", name="阿青", entity_type="character")\n'
            "first = read_chapter_text(paragraph_id=1)\n"
            + "\n".join(f"read_chapter_text(paragraph_id={identifier})" for identifier in range(2, 12))
        )
    )
    assert body["status"] == "applied", body
    assert body["reads_omitted"] == 9
    assert len(body["reads"]) == 2
    assert len(body["references"]) == 11
    assert body["variables"]["first"]["paragraph_id"] == 201
    for read in body["reads"]:
        result = json.loads(read["result"])
        assert len(result["source_ref"]) == 64
        assert result["paragraph_id"] in {210, 211}
        # 去掉字符预算：回显不再截断，整段正文原样可见
        assert "truncated_chars" not in read
        assert result["content"] == texts[result["paragraph_id"] - 201]
    repaired = json.loads(
        await runtime.execute('anchor_record(record_id=person["record"], source_ref=first["source_ref"])')
    )
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
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "execute_code",
                "args": {"code": code},
                "id": identifier,
                "type": "tool_call",
            }
        ],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["entity", "event"])
async def test_clean_agent_finish_stops_without_another_model_request(role: str) -> None:
    ledger = _ledger()
    runtime = _runtime(ledger, role)
    model = _Replies([_program_reply("finish()", "p1")])
    graph = build_agent_graph(
        model,
        runtime.build_tool(),
        runtime.finish_tool,
        ledger=ledger,
        agent=runtime.agent,
        max_iterations=5,
        completion_check=lambda: _complete(runtime),
    )
    await graph.ainvoke(
        {"messages": [HumanMessage(content="完成")], "phase": "chapter_open", "iterations": 0, "error": None}
    )
    assert model.requests == 1


@pytest.mark.asyncio
async def test_finish_closes_work_after_rejected_optional_event() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger, "event")
    model = _Replies(
        [
            _program_reply(
                (
                    "event(el='t1', evidence=1, title='', problem='明确事件问题', summary='举"
                    "刀', event_type='行动', status='ongoing')\n"
                    "finish()"
                ),
                "p1",
            ),
            _program_reply(
                (
                    "event(el='t1', evidence=1, title='', problem='明确事件问题', summary='举"
                    "刀', event_type='行动', status='ongoing')"
                ),
                "p2",
            ),
            _program_reply("finish()", "p3"),
        ]
    )
    graph = build_agent_graph(
        model,
        runtime.build_tool(),
        runtime.finish_tool,
        ledger=ledger,
        agent=runtime.agent,
        max_iterations=5,
        completion_check=lambda: _complete(runtime),
    )
    await graph.ainvoke(
        {"messages": [HumanMessage(content="完成")], "phase": "chapter_open", "iterations": 0, "error": None}
    )
    assert model.requests == 1
    assert ledger.chapter_finished
    assert ledger.bound_payloads["events"] == []


@pytest.mark.asyncio
async def test_metric_finish_requires_its_own_metric() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger, "metric")
    model = _Replies(
        [
            _program_reply("finish()", "p1"),
            _program_reply(
                'metric(summary="阿青入门", emotional_valence=0, narrative_function="铺垫")\nfinish()', "p2"
            ),
        ]
    )
    graph = build_agent_graph(
        model,
        runtime.build_tool(),
        runtime.finish_tool,
        ledger=ledger,
        agent=runtime.agent,
        max_iterations=5,
        completion_check=lambda: _complete(runtime),
    )
    await graph.ainvoke(
        {"messages": [HumanMessage(content="完成")], "phase": "chapter_open", "iterations": 0, "error": None}
    )
    assert model.requests == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failed_call",
    [
        {"name": "unknown_tool", "args": {}},
        {
            "name": "execute_code",
            "args": {
                "code": (
                    "event(el='t1', evidence=1, title='举刀', problem='明确事件问题', summary="
                    "'举刀', event_type='行动', status='ongoing')"
                )
            },
        },
    ],
)
async def test_rejected_call_does_not_reopen_successfully_finished_work(failed_call: dict[str, Any]) -> None:
    ledger = _ledger()
    runtime = _runtime(ledger, "event")
    model = _Replies(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {**failed_call, "id": "bad", "type": "tool_call"},
                    {"name": "finish", "args": {}, "id": "f1", "type": "tool_call"},
                ],
            ),
            AIMessage(content="完成"),
        ]
    )
    graph = build_agent_graph(
        model,
        runtime.build_tool(),
        runtime.finish_tool,
        ledger=ledger,
        agent=runtime.agent,
        max_iterations=5,
        completion_check=lambda: _complete(runtime),
    )
    await graph.ainvoke(
        {"messages": [HumanMessage(content="完成")], "phase": "chapter_open", "iterations": 0, "error": None}
    )
    assert model.requests == 1
    assert runtime.agent.finished is True
    assert ledger.chapter_finished


def _complete(runtime):
    execution = runtime.ledger.finish_work.__self__
    missing = execution.validate()
    if not missing:
        execution.finished = runtime.agent.finished = runtime.ledger.chapter_finished = True
    return missing
