"""2026-09-15 程序面（CodeAct）工具面与图形接入测试

覆盖落地方案裁定的必要边界：对外只广告 execute_code（绑定面）而分发面仍是完整
工具表、模型直发原生调用转入同一个内层 dispatcher 并记 direct_fallback、
未知调用逐条协议错误且同批其他调用照常执行（不整批作废）、原生模式保持既有
整批拒绝语义、逐 op 审计行带 _program 元数据（program_id/op_index/source_line/
record/error_code）、程序面检索回执按 fields/limit 紧凑投影且未声明字段结构化拒绝、
设置开关关闭时绑定面逐字回到原生工具面。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import _build_tool_batch_node
from src.agents.annotation.program import (
    PROGRAM_TOOL_NAME,
    ProgramRuntime,
    build_program_tool,
    program_api_text,
)
from src.agents.annotation.runner import _run_single_attempt
from src.agents.annotation.schema import CaseSearchResult, ChunkParagraphInfo, SearchResult, TextSearchResult
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools
from src.config import settings


class _QueryService:
    """2026-09-15 用于提供无数据库依赖的查询桩"""

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """2026-09-15 用于返回空案例检索结果"""
        del query, hidden_case_ids, case_type, limit, pending_cases
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        """2026-09-15 用于返回五条正文命中（投影断言用）"""
        del query, range_name, limit
        return [
            TextSearchResult(
                chapter_id=1,
                paragraph_ids=[1],
                content=f"顾霜喝止众人-{index}",
                keyword_score=0.5,
                semantic_score=0.1,
            )
            for index in range(5)
        ]

    def search_event_history(self, query, *, limit=50):
        """2026-09-15 用于返回空历史事件树"""
        del query, limit
        return []

    def fetch_active_case_details(self, case_id):
        """2026-09-15 用于表示没有 active 案例"""
        del case_id
        return None


class _RecordingObserver:
    """2026-09-15 用于记录逐条工具审计行而不落库"""

    def __init__(self) -> None:
        """2026-09-15 用于初始化空审计行"""
        self.rows: list[dict[str, Any]] = []
        self.closed = 0

    def record_tool_call(self, **kwargs) -> None:
        """2026-09-15 用于收集审计行参数"""
        self.rows.append(kwargs)

    def close_turn(self) -> None:
        """2026-09-15 用于记录回合闭合次数"""
        self.closed += 1


class _ProgramLLM:
    """2026-09-15 用于捕获绑定面并返回单个程序回合的伪模型"""

    def __init__(self, tool_calls: list[dict[str, Any]]) -> None:
        """2026-09-15 用于保存唯一回复的工具调用"""
        self._tool_calls = tool_calls
        self.bound_names: list[str] = []
        self.calls = 0

    def bind_tools(self, tools):
        """2026-09-15 用于记录实际绑定给模型的工具名"""
        self.bound_names = [str(tool.name) for tool in tools]
        return self

    async def ainvoke(self, messages):
        """2026-09-15 用于返回该回复（第二个回合视为未按预期收尾）"""
        del messages
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("本章应在一个回合内完成")
        return AIMessage(content="", tool_calls=self._tool_calls)


def _chunk_text() -> str:
    """2026-09-15 用于提供含两个对话候选的单段章文本"""
    return "“住手！”顾霜喝道。“退下。”众人散去，夜色渐深。"


def _paragraph_info(text: str) -> ChunkParagraphInfo:
    """2026-09-15 用于构造整章单段段落坐标"""
    return ChunkParagraphInfo(paragraph_ids=[1], char_spans=[(0, len(text))], texts=[text])


def _ledger(**overrides) -> AnnotationToolLedger:
    """2026-09-15 用于构造带事实图与段落坐标的账本"""
    text = _chunk_text()
    kwargs = {
        "run_scope": "run-1",
        "current_chapter_id": 1,
        "current_chunk_id": 1,
        "current_chunk_text": text,
        "allow_future_context": False,
        "graph": FactGraph(),
        "paragraph_info": _paragraph_info(text),
    }
    kwargs.update(overrides)
    return AnnotationToolLedger(**kwargs)


def _surface(ledger: AnnotationToolLedger, observer: Any = None) -> tuple[list[Any], ProgramRuntime, Any]:
    """2026-09-15 用于构造程序面工具表与批次节点（与 runner 装配同形）"""
    inner = build_annotation_tools(_QueryService(), ledger)
    runtime = ProgramRuntime(inner, ledger, observer=observer)
    program_tool = build_program_tool(runtime)
    return [*inner, program_tool], runtime, program_tool


def test_program_api_text_lists_inner_tools_and_search_options() -> None:
    """2026-09-15 程序面 API 目录由工具对象生成：内层工具齐全、检索带 fields/limit 说明"""
    _tools, runtime, program_tool = _surface(_ledger())
    text = program_api_text(runtime.tool_list)
    for name in ("write_entity", "write_event", "write_relation", "write_dialogue", "write_metrics", "finish_chapter"):
        assert f"{name}:" in text
    assert "参数JSON Schema" in text
    assert "可选字段" in text and "limit=" in text
    assert program_tool.name == PROGRAM_TOOL_NAME
    assert "True/False/None" in program_tool.description
    assert "true/false/null" in program_tool.description
    assert "write_entity:" in program_tool.description


@pytest.mark.asyncio
async def test_batch_falls_back_for_direct_native_calls() -> None:
    """2026-09-15 直发原生调用转入同一内层 dispatcher：不报未开放工具、审计记 direct_fallback"""
    ledger = _ledger()
    observer = _RecordingObserver()
    tools, _runtime, program_tool = _surface(ledger, observer)
    batch = _build_tool_batch_node(
        tools,
        ledger=ledger,
        observer=observer,
        program_tool_name=program_tool.name,
    )
    state = await batch(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "search_graph", "args": {"entities": ["顾霜"]}, "id": "c1", "type": "tool_call"}
                    ],
                )
            ],
            "phase": "chunk_open",
        }
    )
    receipt = json.loads(str(state["messages"][-1].content))
    assert "本轮未开放工具" not in json.dumps(receipt, ensure_ascii=False)
    assert set(receipt) == {"matches", "missing", "relations", "neighbors"}
    row = next(item for item in observer.rows if item["tool_name"] == "search_graph")
    assert row["status"] == "success"
    assert row["request_args"]["_program"]["direct_fallback"] is True


@pytest.mark.asyncio
async def test_unknown_tool_is_per_call_error_and_siblings_run() -> None:
    """2026-09-15 未知调用只回协议错误且不写入：同批其他合法调用照常执行"""
    ledger = _ledger()
    observer = _RecordingObserver()
    tools, _runtime, program_tool = _surface(ledger, observer)
    batch = _build_tool_batch_node(
        tools,
        ledger=ledger,
        observer=observer,
        program_tool_name=program_tool.name,
    )
    state = await batch(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "search_nowhere", "args": {}, "id": "c1", "type": "tool_call"},
                        {
                            "name": "write_entity",
                            "args": {"name": "顾霜", "entity_type": "character", "el": "gs"},
                            "id": "c2",
                            "type": "tool_call",
                        },
                    ],
                )
            ],
            "phase": "chunk_open",
        }
    )
    unknown, written = (json.loads(str(message.content)) for message in state["messages"])
    assert "本轮未开放工具" in json.dumps(unknown, ensure_ascii=False)
    assert written["status"] == "written"
    assert set(ledger.written_entities) == {"顾霜"}


@pytest.mark.asyncio
async def test_native_mode_still_rejects_whole_batch() -> None:
    """2026-09-15 原生模式（program_tool_name 缺省）保持既有整批拒绝语义"""
    ledger = _ledger()
    observer = _RecordingObserver()
    tools, _runtime, _program_tool = _surface(ledger, observer)
    batch = _build_tool_batch_node(tools, ledger=ledger, observer=observer)
    state = await batch(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "search_nowhere", "args": {}, "id": "c1", "type": "tool_call"},
                        {
                            "name": "write_entity",
                            "args": {"name": "顾霜", "entity_type": "character", "el": "gs"},
                            "id": "c2",
                            "type": "tool_call",
                        },
                    ],
                )
            ],
            "phase": "chunk_open",
        }
    )
    for message in state["messages"]:
        assert "本轮未开放工具" in json.dumps(json.loads(str(message.content)), ensure_ascii=False)
    assert ledger.written_entities == {}


@pytest.mark.asyncio
async def test_audit_rows_carry_program_meta_and_inner_call_index() -> None:
    """2026-09-15 逐 op 审计行：内层 call_index 与外层隔离、_program 带定位与 error_code"""
    ledger = _ledger()
    observer = _RecordingObserver()
    tools, _runtime, program_tool = _surface(ledger, observer)
    batch = _build_tool_batch_node(
        tools,
        ledger=ledger,
        observer=observer,
        program_tool_name=program_tool.name,
    )
    code = (
        'write_entity(name="侯飞白", entity_type="character", el="hfb")\n'
        'write_entity(name="贺府", entity_type="location", el="hf")\n'
        'write_relation(from_entity="hfb", to_entity="hf", relation_type="隶属")\n'
        "write_metrics(summary=\"贺府夜谈\", emotional_valence=0, narrative_function=\"冲突\")\n"
    )
    await batch(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": PROGRAM_TOOL_NAME, "args": {"code": code}, "id": "c1", "type": "tool_call"}
                    ],
                )
            ],
            "phase": "chunk_open",
        }
    )

    # 外层 execute_code 行在内层 op 之后落库（内层在外层调用执行期间写入），
    # 但 call_index 编号空间把两者分开：外层 0、内层 1000+
    outer = next(item for item in observer.rows if item["tool_name"] == PROGRAM_TOOL_NAME)
    assert outer["call_index"] == 0
    assert outer["request_args"]["code"] == code

    inner_rows = [item for item in observer.rows if item["tool_name"] == "write_entity"]
    assert [item["call_index"] for item in inner_rows] == [1000, 1001]
    meta = inner_rows[0]["request_args"]["_program"]
    assert meta["program_id"] == "p1"
    assert meta["op_index"] == 1
    assert meta["source_line"] == 1
    assert meta["direct_fallback"] is False
    assert meta["record"] == "entity/侯飞白"

    relation_row = next(item for item in observer.rows if item["tool_name"] == "write_relation")
    relation_meta = relation_row["request_args"]["_program"]
    assert relation_row["status"] == "error"
    assert relation_meta["error_code"] == "endpoint_invalid"
    assert relation_meta["op_index"] == 3
    assert relation_meta["record"] == "relation/侯飞白-贺府/隶属"


@pytest.mark.asyncio
async def test_search_projection_caps_items_and_fields() -> None:
    """2026-09-15 程序面检索回执只回明确要求的字段与前若干项"""
    ledger = _ledger()
    observer = _RecordingObserver()
    _tools, runtime, _program_tool = _surface(ledger, observer)

    await runtime.execute(
        'hits = search_text(query="顾霜")\n'
        'write_metrics(summary="x", emotional_valence=0, narrative_function="冲突")'
    )
    default_row = next(item for item in observer.rows if item["tool_name"] == "search_text")
    assert len(default_row["receipt"]) == 3
    assert set(default_row["receipt"][0]) == {"content", "truncated"}

    observer.rows.clear()
    await runtime.execute('hits = search_text(query="顾霜", fields=["content", "keyword_score"], limit=2)')
    explicit_row = next(item for item in observer.rows if item["tool_name"] == "search_text")
    assert len(explicit_row["receipt"]) == 2
    assert set(explicit_row["receipt"][0]) == {"content", "keyword_score"}


@pytest.mark.asyncio
async def test_search_projection_rejects_unknown_field_and_bad_limit() -> None:
    """2026-09-15 未声明字段名与越界 limit 结构化拒绝并列出可选字段"""
    ledger = _ledger()
    _tools, runtime, _program_tool = _surface(ledger)

    unknown = json.loads(await runtime.execute('search_text(query="顾霜", fields=["nope"])'))
    assert unknown["status"] == "partial"
    assert unknown["failed"][0]["tool"] == "search_text"
    assert unknown["failed"][0]["field"] == "fields"
    assert unknown["failed"][0]["code"] == "unknown_field"
    assert "content" in unknown["failed"][0]["expected"]

    out_of_range = json.loads(await runtime.execute('search_text(query="顾霜", limit=99)'))
    assert out_of_range["failed"][0]["field"] == "limit"
    assert out_of_range["failed"][0]["code"] == "out_of_range"


@pytest.mark.asyncio
async def test_runner_advertises_only_execute_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-09-15 单块章走程序面：绑定面只有 execute_code，且本章正常完成"""
    monkeypatch.setattr(settings.models.annotation, "codeact_enabled", True)
    text = _chunk_text()
    program = (
        'write_metrics(summary="顾霜喝止众人", emotional_valence=0, narrative_function="冲突")\n'
        "finish_chapter()"
    )
    llm = _ProgramLLM(
        [
            {
                "name": PROGRAM_TOOL_NAME,
                "args": {"code": program},
                "id": "c1",
                "type": "tool_call",
            }
        ]
    )
    result = await _run_single_attempt(
        run_id="run-1",
        chapter_id=1,
        attempt_number=1,
        current_chunks=[(1, text)],
        novel_title=None,
        llm=llm,
        session_factory=lambda: _NullSession(),
        query_service_factory=lambda session: _QueryService(),
        graph_state=FactGraph(),
        paragraph_info=_paragraph_info(text),
        program_mode=True,
    )
    assert llm.bound_names == [PROGRAM_TOOL_NAME]
    assert result.annotation is not None


@pytest.mark.asyncio
async def test_runner_keeps_native_surface_when_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-09-15 codeact_enabled=false：绑定面逐字回到原生工具面（回退开关）"""
    monkeypatch.setattr(settings.models.annotation, "codeact_enabled", False)
    text = _chunk_text()
    llm = _ProgramLLM(
        [
            {
                "name": "write_metrics",
                "args": {"summary": "顾霜喝止众人", "emotional_valence": 0, "narrative_function": "冲突"},
                "id": "c1",
                "type": "tool_call",
            },
            {"name": "finish_chapter", "args": {}, "id": "c2", "type": "tool_call"},
        ]
    )
    result = await _run_single_attempt(
        run_id="run-1",
        chapter_id=1,
        attempt_number=1,
        current_chunks=[(1, text)],
        novel_title=None,
        llm=llm,
        session_factory=lambda: _NullSession(),
        query_service_factory=lambda session: _QueryService(),
        graph_state=FactGraph(),
        paragraph_info=_paragraph_info(text),
        program_mode=True,
    )
    assert PROGRAM_TOOL_NAME not in llm.bound_names
    assert "write_entity" in llm.bound_names
    assert result.annotation is not None


@pytest.mark.asyncio
async def test_search_pool_projection_compacts_dict_collection() -> None:
    """2026-09-15 字典形态检索（search_pool）同样按前若干项与字段白名单投影"""
    ledger = _ledger()
    observer = _RecordingObserver()
    inner = build_annotation_tools(_PoolQueryService(), ledger)
    runtime = ProgramRuntime(inner, ledger, observer=observer)
    receipt = json.loads(
        await runtime.execute(
            'write_metrics(summary="x", emotional_valence=0, narrative_function="冲突")\n'
            'pending = search_pool(case_type="all", limit=2)'
        )
    )
    assert receipt["applied"] == 2
    row = next(item for item in observer.rows if item["tool_name"] == "search_pool")
    assert len(row["receipt"]["results"]) == 2
    assert set(row["receipt"]["results"][0]) == {
        "result_kind",
        "case_number",
        "type",
        "created_chapter",
        "description",
        "keys",
    }
    assert "pool" in row["receipt"]


class _PoolQueryService(_QueryService):
    """2026-09-15 用于返回三条案例命中的查询桩"""

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """2026-09-15 用于返回三条案例检索结果"""
        del query, hidden_case_ids, case_type, limit, pending_cases
        return SearchResult(
            results=[
                CaseSearchResult(
                    id=f"case-{index}",
                    type="entity_alias",
                    chunk_id=1,
                    created_chapter=1,
                    keys=[f"键{index}"],
                    description=f"案例描述{index}",
                )
                for index in range(3)
            ],
        )


class _NullSession:
    """2026-09-15 用于满足会话协议的最小会话桩（无数据库调用）"""

    def get_bind(self) -> None:
        """2026-09-15 用于声明无绑定"""
        return None
