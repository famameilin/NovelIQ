"""2026-09-15 程序面（CodeAct）工具面与图形接入测试

2026-09-19 双路径定案：程序面有两处——subagent 面（SubagentProgramRuntime）与
agent 路径写者面（ProgramRuntime，程序内直调正式工具）。本文件覆盖 subagent 面边界：

- 绑定面两件（execute_code + finish）；execute_code 目录 = 4 检索 + 5 案例 + finish +
  八类构造器，五个正式写入工具既不在目录也不在命名空间；
- 目录文案与命名空间/参数取值目录同源（防漂移）、与目录里 "名字: 说明" 同源的根
  description 不再在参数 schema 里重复下发；
- 模型直发绑定面之外的 native 工具名逐条协议错误且不写入、同批其他调用照常执行；
  原生回退面（无程序入口）保持既有整批拒绝语义；
- 逐 op 审计行带 _program 元数据（program_id/op_index/source_line/record/error_code），
  内层 call_index 与外层隔离；
- 程序面检索回执按 fields/limit 紧凑投影、未声明字段结构化拒绝；读结果回显且失败清单
  排在 refs 之前；
- subagent 的 finish 只声明本 subagent 完毕，不触发整章冻结。

2026-09-18 随写者面删除的用例（见提交说明）：章级 finish 在程序末尾结算、native finish
触发整章冻结、写者面合同文案、runner 程序模式绑定面。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import _build_tool_batch_node, build_subagent_graph
from src.agents.annotation.program import PROGRAM_TOOL_NAME
from src.agents.annotation.schema import CaseSearchResult, ChapterParagraphInfo, SearchResult, TextSearchResult
from src.agents.annotation.subagent_ir import SubagentAnnotation
from src.agents.annotation.subagent_program import SubagentProgramRuntime
from src.agents.annotation.tools import FINISH_TOOL_NAME, AnnotationToolLedger, build_annotation_tools

# 八类构造器（顺序即目录顺序；finish 不是构造器，是面上一等工具）
CONSTRUCTOR_NAMES: tuple[str, ...] = (
    "entity",
    "relation",
    "event",
    "participants",
    "dialogue",
    "label",
    "metric",
    "pending",
)

# 四个检索工具：程序面给它们包了 fields/limit 紧凑投影
SEARCH_TOOL_NAMES: tuple[str, ...] = ("search_graph", "search_text", "search_event", "search_pool")


class _QueryService:
    """2026-09-15 用于提供无数据库依赖的查询桩"""

    current_chapter_order = None

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
                    chapter_id=1,
                    created_chapter=1,
                    keys=[f"键{index}"],
                    description=f"案例描述{index}",
                )
                for index in range(3)
            ],
        )


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


class _SubagentProgramLLM:
    """2026-09-15 用于捕获绑定面并按序返回伪模型回复（供 subagent 图会话用）"""

    def __init__(self, replies: list[AIMessage]) -> None:
        """2026-09-15 用于保存各回合回复（末条固定为无工具回复=会话收束）"""
        self._replies = list(replies)
        self.bound_names: list[str] = []
        self.calls = 0
        # 2026-09-20 逐请求留存实际下发的消息（注入块只在请求里，不在状态链里）
        self.captured: list[list[Any]] = []

    def bind_tools(self, tools):
        """2026-09-15 用于记录实际绑定给模型的工具名"""
        self.bound_names = [str(tool.name) for tool in tools]
        return self

    async def ainvoke(self, messages):
        """2026-09-15 用于返回该回合回复（超出预设的回合一律回无工具回复）"""
        self.captured.append(list(messages))
        self.calls += 1
        return self._replies[min(self.calls - 1, len(self._replies) - 1)]


def _chapter_text() -> str:
    """2026-09-15 用于提供含两个对话候选的单段章文本"""
    return "“住手！”顾霜喝道。“退下。”众人散去，夜色渐深。"


def _paragraph_info(text: str) -> ChapterParagraphInfo:
    """2026-09-15 用于构造整章单段段落坐标"""
    return ChapterParagraphInfo(paragraph_ids=[1], char_spans=[(0, len(text))], texts=[text])


def _ledger(**overrides) -> AnnotationToolLedger:
    """2026-09-15 用于构造带事实图与段落坐标的账本"""
    text = _chapter_text()
    kwargs = {
        "run_scope": "run-1",
        "current_chapter_id": 1,
        "current_chapter_text": text,
        "allow_future_context": False,
        "graph": FactGraph(),
        "paragraph_info": _paragraph_info(text),
    }
    kwargs.update(overrides)
    return AnnotationToolLedger(**kwargs)


def _runtime(
    ledger: AnnotationToolLedger,
    *,
    subagent: SubagentAnnotation | None = None,
    observer: Any = None,
    query: Any = None,
) -> SubagentProgramRuntime:
    """2026-09-18 用于按生产装配方式构造 subagent 程序面（共享章级账本与生产工具表）"""
    tool_map = {tool.name: tool for tool in build_annotation_tools(query or _QueryService(), ledger)}
    return SubagentProgramRuntime(
        tool_map,
        ledger,
        subagent if subagent is not None else SubagentAnnotation(role="structure"),
        observer=observer,
    )


def _surface(
    ledger: AnnotationToolLedger,
    *,
    observer: Any = None,
    query: Any = None,
) -> tuple[SubagentProgramRuntime, Any]:
    """2026-09-18 用于构造 subagent 程序面与对外的 execute_code 工具"""
    runtime = _runtime(ledger, observer=observer, query=query)
    return runtime, runtime.build_tool()


def _bound_batch(runtime: SubagentProgramRuntime, ledger: AnnotationToolLedger, observer: Any):
    """2026-09-18 用于按生产 subagent 图装配工具批次节点

    绑定面（tools）= [execute_code, finish]，program_tool_name 收成 execute_code；
    chapter_finish_name=None：subagent 的同名 finish 不是章级收尾，不冻结整章、
    也不在批次末尾结算。
    """
    return _build_tool_batch_node(
        [runtime.build_tool(), runtime.finish_tool],
        ledger=ledger,
        observer=observer,
        program_tool_name=PROGRAM_TOOL_NAME,
        chapter_finish_name=None,
    )


def _tool_call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    """2026-09-18 用于构造一条工具调用载荷"""
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


@pytest.mark.asyncio
async def test_event_attach_resolves_own_tree_key() -> None:
    """2026-09-18 挂进伏笔树收本 subagent 的局部键（本章事件 t1）

    构造器落库的 el 是 `角色:树键`（namespace_event_el），模型只知道自己的 t1；本面的
    event(..., foreshadowing_action=..., root_event_id=...) 必须把局部树键换算成落库 el
    再交给写入路径，否则挂树在事件引用表上必然落空。本用例钉住这层换算与产出的落库项。
    """
    ledger = _ledger()
    subagent = SubagentAnnotation(role="event")
    runtime = _runtime(ledger, subagent=subagent)
    receipt = json.loads(
        await runtime.execute(
            'event(el="t1", isroot=True, description="埋设", evidence=1, isforeshadowing=True, confidence="low")\n'
            'event(el="t1/e2", isroot=False, description="续接", evidence=1, type="main", '
            'foreshadowing_action="reinforce", root_event_id="t1", payoff_likelihood="high", strength="medium")'
        )
    )
    assert receipt["status"] == "applied"
    assert receipt["applied"] == 2
    assert "failed" not in receipt
    # 挂在树上的确实是本 subagent 刚写的那棵树（局部键换算成落库 el 之后才认得出来）
    tree = next(iter(ledger.event_trees.values()))
    attached = ledger.resolved_cases[0]
    assert attached.case_id == ""
    assert attached.foreshadowing_root_event_id == tree["root_node_id"]
    assert attached.foreshadowing_event_id == tree["nodes"]["e2"]
    # 2026-09-19 挂边顺带更新树根属性：两个三档字段原样落到无案例的解决项
    assert attached.payoff_likelihood == "high"
    assert attached.strength == "medium"
    orphan = json.loads(
        await runtime.execute('event(el="t9", isroot=True, description="无挂边", evidence=1, strength="low")')
    )
    assert orphan["failed"][0]["code"] == "not_on_attach"


@pytest.mark.asyncio
async def test_constructor_namespaces_relation_endpoints() -> None:
    """2026-09-18 引用键的命名空间化发生在构造器里（生产入参已是 `角色:局部键`）

    本面每个 subagent 都用 a1/t1 这类局部键，写入面按落库 el 索引，所以构造器编译出的
    生产入参必须带角色命名空间；未登记的 id 当场结构化拒绝，不靠生产面兜底。
    """
    ledger = _ledger()
    runtime = _runtime(ledger, subagent=SubagentAnnotation(role="structure"))
    receipt = json.loads(
        await runtime.execute(
            'entity(id="a1", name="顾霜", entity_type="character", evidence=1)\n'
            'entity(id="a2", name="众人", entity_type="character", evidence=1)\n'
            'relation(from_id="a1", to_id="a2", relation_type="敌对", evidence=1)'
        )
    )
    assert receipt["status"] == "applied"
    assert "failed" not in receipt
    # 落库 el 索引里的键带角色命名空间（三个 subagent 各自的 a1 互不占用）
    assert set(ledger.entity_el_index) == {"structure:a1", "structure:a2"}
    assert ledger.written_relations
    failure = json.loads(
        await runtime.execute('relation(from_id="a9", to_id="a2", relation_type="敌对", evidence=1)')
    )
    assert failure["failed"][0]["code"] == "unknown_reference"


@pytest.mark.asyncio
async def test_subagent_graph_injects_progress_ledger_every_turn() -> None:
    """2026-09-20 三条 lane 与写者面同一份【进度账本】逐回合注入

    run 54a72932 实测：写者面 80/80 请求带注入块、三条 lane 0/439——服务端不重放思考，
    每个 subagent 跨回合同样看不到自己上轮的判定。注入块只进当次请求（状态链长度按
    "链上原有消息"算），所以每个回合的请求比状态链恰好多这一条。
    """
    ledger = _ledger()
    subagent = SubagentAnnotation(role="structure")
    runtime = _runtime(ledger, subagent=subagent)
    llm = _SubagentProgramLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call(
                        PROGRAM_TOOL_NAME,
                        {"code": 'entity(id="a1", name="顾霜", entity_type="character", evidence=1)'},
                        "c1",
                    )
                ],
            ),
            AIMessage(content="写完", tool_calls=[]),
        ]
    )
    graph = build_subagent_graph(llm, runtime.build_tool(), runtime.finish_tool, ledger=ledger, max_iterations=5)
    await graph.ainvoke(
        {
            "messages": [HumanMessage(content="标注本章")],
            "phase": "chapter_open",
            "iterations": 0,
            "error": None,
        }
    )

    # 回合 1：初始消息 + 注入块；回合 2：状态链（初始 + AI + 程序回执）+ 注入块
    assert [len(messages) for messages in llm.captured] == [2, 4]
    assert [len(messages) - len(llm.captured[0]) for messages in llm.captured[1:]] == [2]
    assert isinstance(llm.captured[1][-1], HumanMessage)
    # 2026-09-20 与写者面同一位置约束：注入块恒在末位、且上一轮那份不进下一轮请求
    assert isinstance(llm.captured[0][-1], HumanMessage)
    first_block = str(llm.captured[0][-1].content)
    assert first_block != str(llm.captured[1][-1].content)
    assert all(str(message.content) != first_block for message in llm.captured[1])
    # 末位那份携带本轮之前的写入：第 2 回合末位可见第 1 回合登记的实体 el
    assert "a1" in str(llm.captured[1][-1].content)


@pytest.mark.asyncio
async def test_native_names_off_the_bound_surface_are_per_call_protocol_errors() -> None:
    """2026-09-15 绑定面之外的 native 工具名逐条协议错误、不写入；同批 finish 照常执行

    subagent 的绑定面是 [execute_code, finish]：模型直发 write_entity/search_graph 一律
    逐条协议错误并记 direct_fallback 之外的普通失败，不整批作废，也不触发任何正式写入。
    """
    ledger = _ledger()
    observer = _RecordingObserver()
    subagent = SubagentAnnotation(role="structure")
    runtime = _runtime(ledger, subagent=subagent, observer=observer)
    batch = _bound_batch(runtime, ledger, observer)
    state = await batch(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        _tool_call(
                            "write_entity",
                            {"name": "顾霜", "entity_type": "character", "el": "gs"},
                            "c1",
                        ),
                        _tool_call("search_graph", {"entities": ["顾霜"]}, "c2"),
                        _tool_call(FINISH_TOOL_NAME, {}, "c3"),
                    ],
                )
            ],
            "phase": "chapter_open",
        }
    )
    receipts = [json.loads(str(message.content)) for message in state["messages"]]
    rejected = [receipt for receipt in receipts if receipt.get("tool") in {"write_entity", "search_graph"}]
    assert len(rejected) == 2
    for receipt in rejected:
        assert receipt["accepted"] is False
    finished = [receipt for receipt in receipts if receipt.get("record") == "structure/finish"]
    assert len(finished) == 1
    assert finished[0]["status"] == "written"
    assert subagent.finished is True
    assert ledger.written_entities == {}
    assert ledger.annotation is None


@pytest.mark.asyncio
async def test_native_fallback_batch_still_rejects_whole_batch() -> None:
    """2026-09-15 原生回退面（program_tool_name 缺省）保持既有整批拒绝语义"""
    ledger = _ledger()
    observer = _RecordingObserver()
    tools = build_annotation_tools(_QueryService(), ledger)
    batch = _build_tool_batch_node(tools, ledger=ledger, observer=observer)
    state = await batch(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        _tool_call("search_nowhere", {}, "c1"),
                        _tool_call(
                            "write_entity",
                            {"name": "顾霜", "entity_type": "character", "el": "gs"},
                            "c2",
                        ),
                    ],
                )
            ],
            "phase": "chapter_open",
        }
    )
    receipts = [json.loads(str(message.content)) for message in state["messages"]]
    rejected = [receipt for receipt in receipts if receipt.get("tool") in {"search_nowhere", "write_entity"}]
    assert len(rejected) == 2
    for receipt in rejected:
        assert receipt["accepted"] is False
    assert ledger.written_entities == {}


@pytest.mark.asyncio
async def test_direct_native_finish_runs_inner_dispatcher_without_freezing_chapter() -> None:
    """2026-09-18 直发 native finish（绑定面上的另一件）：按 direct_fallback 走内层 dispatcher，不冻结整章"""
    ledger = _ledger()
    observer = _RecordingObserver()
    subagent = SubagentAnnotation(role="structure")
    runtime = _runtime(ledger, subagent=subagent, observer=observer)
    batch = _bound_batch(runtime, ledger, observer)
    state = await batch(
        {
            "messages": [AIMessage(content="", tool_calls=[_tool_call(FINISH_TOOL_NAME, {}, "c1")])],
            "phase": "chapter_open",
        }
    )
    receipt = json.loads(str(state["messages"][-1].content))
    assert receipt["status"] == "written"
    assert receipt["ref"]["finished"] is True
    assert subagent.finished is True

    row = next(item for item in observer.rows if item["tool_name"] == FINISH_TOOL_NAME)
    assert row["status"] == "success"
    assert row["request_args"]["_program"]["direct_fallback"] is True
    # 本 subagent 的 finish 不是章级收尾：章不冻结、不产出章级标注
    assert ledger.chapter_finished is False
    assert ledger.annotation is None


@pytest.mark.asyncio
async def test_audit_rows_carry_program_meta_and_inner_call_index() -> None:
    """2026-09-15 逐 op 审计行：内层 call_index 与外层隔离、_program 带定位与 error_code"""
    ledger = _ledger()
    observer = _RecordingObserver()
    subagent = SubagentAnnotation(role="structure")
    runtime = _runtime(ledger, subagent=subagent, observer=observer)
    batch = _bound_batch(runtime, ledger, observer)
    code = (
        'entity(id="a1", name="侯飞白", entity_type="character", evidence=1)\n'
        'entity(id="a2", name="贺府", entity_type="location", evidence=1)\n'
        'relation(from_id="a1", to_id="a9", relation_type="利益", evidence=1)\n'
        'search_text(query="顾霜", fields=["nope"])\n'
    )
    await batch(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[_tool_call(PROGRAM_TOOL_NAME, {"code": code}, "c1")],
                )
            ],
            "phase": "chapter_open",
        }
    )

    # 外层 execute_code 行在内层 op 之后落库（内层在外层调用执行期间写入），
    # 但 call_index 编号空间把两者分开：外层 0、内层 1000+
    outer = next(item for item in observer.rows if item["tool_name"] == PROGRAM_TOOL_NAME)
    assert outer["call_index"] == 0
    assert outer["request_args"]["code"] == code

    inner = [item for item in observer.rows if item["tool_name"] == "entity"]
    assert len(inner) == 2
    assert all(item["call_index"] >= 1000 for item in inner)
    meta = inner[0]["request_args"]["_program"]
    assert meta["program_id"] == "p1"
    assert meta["op_index"] == 1
    assert meta["record"] == "structure/entity/a1"
    assert meta["direct_fallback"] is False

    relation_row = next(item for item in observer.rows if item["tool_name"] == "relation")
    assert relation_row["status"] == "error"
    assert relation_row["request_args"]["_program"]["op_index"] == 3
    assert relation_row["request_args"]["_program"]["record"] == "structure/relation/a1-a9"

    # 检索类失败按 receipt 的 code 进 _program.error_code（构造器路径只带 record）
    search_row = next(item for item in observer.rows if item["tool_name"] == "search_text")
    assert search_row["status"] == "error"
    assert search_row["request_args"]["_program"]["error_code"] == "unknown_field"
    assert search_row["request_args"]["_program"]["source_line"] == 4


@pytest.mark.asyncio
async def test_search_projection_caps_items_and_fields() -> None:
    """2026-09-15 程序面检索回执只回明确要求的字段与前若干项"""
    ledger = _ledger()
    observer = _RecordingObserver()
    runtime, _program_tool = _surface(ledger, observer=observer)

    await runtime.execute(
        'hits = search_text(query="顾霜")\n'
        'metric(summary="x", emotional_valence=0, narrative_function="冲突")'
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
    runtime, _program_tool = _surface(_ledger())

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
async def test_receipt_echoes_reads_and_puts_failures_first() -> None:
    """2026-09-17 回执回显检索读结果，且失败清单排在进度之前（§12.5①）

    程序里的检索此前只把 payload 交给程序变量，模型看不到值（实测同一句检索连发 7 次）；
    失败清单排在进度后面时，模型要先蹚过进度才看到失败原因。
    """
    runtime, _program_tool = _surface(_ledger())

    out = json.loads(
        await runtime.execute(
            'hits = search_text(query="顾霜")\n'
            'relation(from_id="a1", to_id="a1", relation_type="利益", evidence=1)'
        )
    )
    assert list(out) == ["status", "applied", "progress", "failed", "reads"]
    assert out["reads"][0]["tool"] == "search_text"
    assert out["reads"][0]["op"] == 1
    assert "顾霜喝止众人-0" in out["reads"][0]["result"]
    assert out["failed"][0]["tool"] == "relation"


@pytest.mark.asyncio
async def test_reads_echo_is_capped_and_skips_failed_reads() -> None:
    """2026-09-17 读结果回显按条数上限收敛、被拒的检索不进 reads"""
    runtime, _program_tool = _surface(_ledger())

    program = "".join(f'search_text(query="顾霜", limit={index % 5 + 1})\n' for index in range(9))
    out = json.loads(await runtime.execute(program))
    assert len(out["reads"]) == 9  # 8 条明细 + 1 条省略说明

    rejected = json.loads(await runtime.execute('search_text(query="顾霜", fields=["nope"])'))
    assert "reads" not in rejected
    assert rejected["failed"][0]["code"] == "unknown_field"


@pytest.mark.asyncio
async def test_search_pool_projection_compacts_dict_collection() -> None:
    """2026-09-15 字典形态检索（search_pool）同样按前若干项与字段白名单投影"""
    ledger = _ledger()
    observer = _RecordingObserver()
    runtime, _program_tool = _surface(ledger, observer=observer, query=_PoolQueryService())
    receipt = json.loads(
        await runtime.execute(
            'metric(summary="x", emotional_valence=0, narrative_function="冲突")\n'
            'pending = search_pool(case_type="all", limit=2)'
        )
    )
    assert receipt["applied"] == 2
    row = next(item for item in observer.rows if item["tool_name"] == "search_pool")
    assert len(row["receipt"]["results"]) == 2
    assert set(row["receipt"]["results"][0]) == {
        "result_kind",
        "id",
        "type",
        "created_chapter",
        "description",
        "keys",
    }
    assert "pool" in row["receipt"]
