"""事件层测试：实时小调用事件树语义（write_event_root / write_event_child / 参与者 + finish_chunk）

2026-09-13 实时写入改造后的覆盖（相对旧"暂存 + finish_domain"合同）：
- 写入即生效：小调用直接落到 event_trees/bound_payloads，成功回执
  {"status": "written", "record": ...}；模型面只见章内局部键（tree_key/node_key），
  真实 node_id/tree_id 是服务端内部标识，不外露；
- 唯一收尾 finish_chunk：工具体只回 {"status": "pending"}，本回合全部调用处理完后
  由账本做收尾判定（本文件用 ledger.finish_chunk() 走同一汇点）；
- 单条记录失败=结构化拒绝（record/field/code/expected），只回滚该调用；
  旧契约的整树 pydantic 报错、草稿 patches、逐域完成声明已删除；
- 事件树按调用顺序实时生长：main 顺延主因链、secondary 挂当时主链尾；
- cause_tree_id 只接受 search_event 授权的历史树 id（本章局部 tree_key 的解析
  见 tools._resolve_cause_tree 的现状），一经确定不可改写；
- 同一 chunk 内 (人物, 动作) 二元组唯一：重复的那条在写入点被拒绝，
  逐条失败不阻塞同回合的 finish_chunk 收尾。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.annotation.errors import AnnotationStageRejection
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import _invoke_tool, build_annotation_graph
from src.agents.annotation.prompts import build_chunk_message
from src.agents.annotation.schema import (
    ChunkParagraphInfo,
    EventTreeHistoryResult,
    SearchResult,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools

_CHUNK_TEXT = "\u201c住手\u201d回荡"


class _QueryServiceStub:
    """2026-08-19 用于为事件写入提供最小查询服务（无需检索历史）"""

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        del query, hidden_case_ids, case_type, limit
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        del query, range_name, limit
        return []

    def fetch_active_case_details(self, case_id):
        del case_id
        return None

    def search_event_history(self, query, *, limit=50):
        del query, limit
        return []


class _EventHistoryQueryService(_QueryServiceStub):
    """2026-08-22 用于返回预设历史事件树根视图并记录检索的查询桩"""

    def __init__(self, trees: list[EventTreeHistoryResult]) -> None:
        self.trees = trees

    def search_event_history(self, query, *, limit=50):
        del query, limit
        return list(self.trees)


def _history_tree(tree_id: str, root_node_id: str, description: str) -> EventTreeHistoryResult:
    """2026-08-22 用于构造预设历史树根视图（cause_tree_id 的授权来源）"""
    return EventTreeHistoryResult(
        tree_id=tree_id,
        root_node_id=root_node_id,
        chapter_id=1,
        chapter_order=1,
        description=description,
        participants=[{"entity": "顾霜", "role": "主体"}],
        cross_chapter=False,
    )


def _ledger(
    *,
    paragraph_ids: list[int] | None = None,
    char_spans: list[tuple[int, int]] | None = None,
    texts: list[str] | None = None,
) -> AnnotationToolLedger:
    """2026-08-30 用于构造带唯一当前原文与空事实图的事件测试账本"""
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=10,
        current_chunk_text=_CHUNK_TEXT,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=paragraph_ids or [0],
            char_spans=char_spans or [(0, len(_CHUNK_TEXT))],
            texts=texts or [_CHUNK_TEXT],
        ),
    )


def _tools(ledger: AnnotationToolLedger, service: Any = None) -> dict[str, Any]:
    """2026-09-13 用于构建按工具名索引的写者工具集"""
    return {tool.name: tool for tool in build_annotation_tools(service or _QueryServiceStub(), ledger)}


def _call(tools: dict[str, Any], name: str, args: dict) -> dict[str, Any]:
    """2026-09-13 用于直接调用单个写入工具并解析成功回执"""
    return json.loads(tools[name].invoke(args))


def _write_call(name: str, args: dict, *, call_id: str) -> dict:
    """2026-09-13 用于构造经 graph._invoke_tool 的生产调用（含 schema 层失败翻译）"""
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


async def _stage_rejection(tools: dict[str, Any], name: str, args: dict) -> dict[str, Any]:
    """2026-09-13 用于取得单条记录的结构化拒绝回执（record/field/code/expected）"""
    with pytest.raises(AnnotationStageRejection) as exc_info:
        await _invoke_tool(tools, _write_call(name, args, call_id="call-rejected"))
    return exc_info.value.receipt()


def _entity_number(tools: dict[str, Any], name: str, entity_type: str = "character") -> int:
    """2026-09-13 用于登记实体并取回运行期编号（参与者/说话人参数都用编号）"""
    receipt = _call(tools, "write_entity", {"name": name, "entity_type": entity_type})
    return int(receipt["n"])


def _seed_metrics(tools: dict[str, Any]) -> None:
    """2026-09-13 用于提交最小指标载荷（finish_chunk 的硬前提）"""
    _call(tools, "write_metrics", {"summary": "顾霜拔剑", "emotional_valence": 0, "narrative_function": "冲突"})


def _root_args(**overrides: Any) -> dict:
    """2026-09-13 用于构造 write_event_root 参数（默认一棵无参与者树的根）"""
    payload: dict[str, Any] = {"tree_key": "t1", "description": "顾霜拔剑"}
    payload.update(overrides)
    return payload


def _child_args(**overrides: Any) -> dict:
    """2026-09-13 用于构造 write_event_child 参数（默认 main 子事件）"""
    payload: dict[str, Any] = {
        "tree_key": "t1",
        "node_key": "e1",
        "order": 1,
        "type": "main",
        "description": "顾霜收势",
    }
    payload.update(overrides)
    return payload


def _character_participation_args(**overrides: Any) -> dict:
    """2026-09-13 用于构造 write_character_participation 参数（entity 为运行期编号，默认 1=顾霜）"""
    payload: dict[str, Any] = {
        "tree_key": "t1",
        "node_key": "root",
        "entity": 1,
        "role": "主体",
        "narrative_role": "主体",
        "action": "拔剑",
        "emotion": -1,
    }
    payload.update(overrides)
    return payload


def _metrics_call(call_id: str = "call-metrics") -> dict:
    """2026-09-13 用于构造最小指标写入调用（收尾的硬前提）"""
    return _write_call(
        "write_metrics",
        {"summary": "顾霜拔剑", "emotional_valence": 0, "narrative_function": "冲突"},
        call_id=call_id,
    )


def _tool_message(calls: list[dict]) -> AIMessage:
    """2026-08-07 用于构造带工具调用的模型回复"""
    return AIMessage(content="", tool_calls=calls)


def _tool_receipts(captured_round: list) -> list[str]:
    """2026-08-10 用于提取某轮模型请求中的全部 ToolMessage 内容"""
    return [str(message.content) for message in captured_round if getattr(message, "type", "") == "tool"]


def _finish_call() -> dict:
    """2026-09-13 用于构造唯一 finish_chunk 收尾声明（判定推迟到本回合调用处理完后）"""
    return _write_call("finish_chunk", {}, call_id="call-finish-chunk")


def _event_tree_calls(
    *,
    tree_key: str,
    description: str,
    action: str,
    entity: int,
    call_id: str,
) -> list[dict]:
    """2026-09-13 用于构造一棵最小事件树的小调用组（根 + 根上人物参与）"""
    return [
        _write_call(
            "write_event_root",
            {"tree_key": tree_key, "description": description},
            call_id=f"{call_id}-root",
        ),
        _write_call(
            "write_character_participation",
            _character_participation_args(tree_key=tree_key, entity=entity, action=action),
            call_id=f"{call_id}-p1",
        ),
    ]


class _SequenceLLM:
    """2026-09-13 用于按顺序返回模型消息的测试模型（仅 ainvoke）"""

    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.captured_messages: list[list] = []

    def bind_tools(self, tools):
        """2026-09-13 用于满足 LangChain 模型绑定合同"""
        return self

    async def ainvoke(self, messages):
        """2026-09-13 用于返回下一条测试模型消息并记录输入"""
        self.calls += 1
        self.captured_messages.append(list(messages))
        return self.responses.pop(0)


async def _invoke_graph(
    llm: _SequenceLLM,
    ledger: AnnotationToolLedger,
    *,
    max_iterations: int = 30,
) -> dict:
    """2026-09-13 用于在给定账本上执行单 chunk 章节 LangGraph"""
    tools = build_annotation_tools(_QueryServiceStub(), ledger)
    graph = build_annotation_graph(llm, tools, ledger=ledger, max_iterations=max_iterations)
    return await graph.ainvoke(
        {
            "messages": [
                SystemMessage(content="test"),
                HumanMessage(
                    content=build_chunk_message(
                        chunk_index=1,
                        chunk_total=1,
                        chunk_text=_CHUNK_TEXT,
                        candidates=ledger.dialogue_candidates,
                    )
                ),
            ],
            "phase": "chunk_open",
            "iterations": 0,
            "error": None,
        }
    )


def test_write_event_returns_tree_and_authorizes_root() -> None:
    """2026-08-22 创建事件树由服务端派发 tree_id/root_node_id 并登记授权

    2026-09-13 实时写入：模型面回执改为 {status: written, record: t1/root}；
    tree_id/root_node_id 是服务端内部标识（模型只用 tree_key 指树），
    真实 id 从账本读取——授权集合仍登记根与子节点 id（resolve_foreshadowing_case 的授权来源）。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    entity = _entity_number(tools, "顾霜")
    _call(tools, "write_event_root", _root_args())
    _call(tools, "write_event_child", _child_args())
    _call(tools, "write_character_participation", _character_participation_args(entity=entity))

    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    root_node_id = tree["root_node_id"]
    assert root_node_id in ledger.authorized_event_ids
    assert set(tree["nodes"].values()) <= ledger.authorized_event_ids
    bound = ledger.bound_payloads["events"]
    assert [node.node_id for node in bound] == list(tree["nodes"].values())
    assert bound[0].tree_id == tree["tree_id"]
    assert bound[0].cause_role == "root"
    assert bound[0].description == "顾霜拔剑"
    assert ledger.bound_payloads["character_observations"][0].action == "拔剑"

    _seed_metrics(tools)
    receipt = ledger.finish_chunk()
    assert receipt["status"] == "completed"
    assert receipt["chunk_id"] == 10
    assert receipt["records"]["events"] == 2
    assert receipt["records"]["character_observations"] == 1


@pytest.mark.asyncio
async def test_write_event_requires_character_participant_state_fields() -> None:
    """2026-08-30 用于拒绝未携带人物动态状态的角色参与者

    2026-09-13 实时写入：三态是 write_character_participation 的必填参数，
    缺失在 schema 层被翻译成结构化拒绝（record=t1/root/participant/1,
    field=narrative_role, code=missing），只指向该条记录且不写入；
    旧契约"整树报错"与裸 ValueError 断言不再适用。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    entity = _entity_number(tools, "顾霜")
    _call(tools, "write_event_root", _root_args())

    receipt = await _stage_rejection(
        tools,
        "write_character_participation",
        {"tree_key": "t1", "node_key": "root", "entity": entity, "role": "主体"},
    )

    assert receipt["record"] == "t1/root/participant/1"
    assert receipt["field"] == "narrative_role"
    assert receipt["code"] == "missing"
    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    assert ledger.bound_payloads["events"][0].participants == []
    assert set(tree["nodes"]) == {"root"}
    assert ledger.tree_key_index == {"t1": tree["tree_id"]}
    assert ledger.observation_by_record == {}


def test_write_event_without_participants_derives_empty_character_domain() -> None:
    """2026-08-30 用于允许无人物事件明确收尾空人物动态领域

    2026-09-13：无参与者树先 write_event_root 即时落账，再用唯一 finish_chunk 收尾；
    character_observations 随事件域派生的语义不变。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    _call(tools, "write_event_root", _root_args(description="山门夜雨"))
    _seed_metrics(tools)

    receipt = ledger.finish_chunk()

    assert receipt["records"]["character_observations"] == 0
    assert ledger.bound_payloads["character_observations"] == []
    assert "events" not in ledger.missing_content_domains()


def test_write_event_empty_completion_does_not_invent_event() -> None:
    """2026-08-30 用于允许无事件章节显式收尾且不捏造事件

    2026-09-13：空域不再用逐域 finish_domain("events") 声明，直接 finish_chunk 收尾；
    空事件是合法终态，不建树不建节点。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    _seed_metrics(tools)

    receipt = ledger.finish_chunk()

    assert receipt["status"] == "completed"
    assert receipt["records"]["events"] == 0
    assert ledger.event_trees == {}
    assert ledger.bound_payloads["events"] == []
    assert ledger.bound_payloads["character_observations"] == []


@pytest.mark.asyncio
async def test_write_event_isforeshadowing_creates_thread_binding() -> None:
    """2026-09-13 伏笔即事件树：isforeshadowing=true 根事件携带伏笔属性

    旧契约回执暴露 foreshadowing_root_node_id；新契约模型面只有 written 回执，
    "根即埋设事件"从落账节点与树登记读取；伏笔两字段缺一在写入点即结构化拒绝。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    _entity_number(tools, "顾霜")
    _call(tools, "write_event_root", _root_args())

    missing = await _stage_rejection(
        tools,
        "write_event_root",
        _root_args(tree_key="t2", isforeshadowing=True),
    )
    assert missing["record"] == "t2/root"
    assert missing["field"] == "expected_payoff_family"
    assert missing["code"] == "missing"

    _call(
        tools,
        "write_event_root",
        _root_args(
            tree_key="t2",
            description="神秘玉戒发光",
            isforeshadowing=True,
            expected_payoff_family="身份揭露",
            payoff_likelihood="medium",
        ),
    )

    bound = ledger.bound_payloads["events"]
    root = next(node for node in bound if node.is_foreshadow_setup)
    assert root.is_foreshadow_setup is True
    assert root.expected_payoff_family == "身份揭露"
    assert root.payoff_likelihood == "medium"
    tree = ledger.event_trees[ledger.tree_key_index["t2"]]
    assert tree["isforeshadowing"] is True
    assert tree["root_node_id"] == root.node_id


def test_write_event_exposes_pydantic_schema_and_creates_ordered_children() -> None:
    """2026-08-30 用于验证工具公开真实参数合同并按调用顺序组装事件树

    2026-09-13 实时写入：整树 write_event 的位置式参数合同（children 数组）已删除，
    "公开真实合同"改断言各小工具的可见参数键（子事件入口没有 children/伏笔字段）；
    main 顺延主因链、secondary 挂当时链尾的组装语义不变（顺序由调用顺序表达）。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    assert set(tools["write_event_child"].args) == {
        "tree_key",
        "node_key",
        "order",
        "type",
        "description",
    }
    assert set(tools["write_event_root"].args) == {
        "tree_key",
        "description",
        "cause_tree_id",
        "isforeshadowing",
        "expected_payoff_family",
        "payoff_likelihood",
    }

    entity = _entity_number(tools, "顾霜")
    _call(tools, "write_event_root", _root_args())
    _call(tools, "write_character_participation", _character_participation_args(entity=entity))
    _call(tools, "write_event_child", _child_args(node_key="e1", order=1, type="main", description="顾霜收势"))
    _call(
        tools,
        "write_character_participation",
        _character_participation_args(entity=entity, node_key="e1", action="收势", emotion=0),
    )
    _call(tools, "write_event_child", _child_args(node_key="e2", order=2, type="secondary", description="旁观者惊呼"))
    _call(tools, "write_event_child", _child_args(node_key="e3", order=3, type="main", description="顾霜离开山门"))

    bound = ledger.bound_payloads["events"]
    assert [node.description for node in bound] == ["顾霜拔剑", "顾霜收势", "旁观者惊呼", "顾霜离开山门"]
    root_node = bound[0]
    main_node, secondary_node, final_main_node = (node.node_id for node in bound[1:])
    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    assert tree["trunk_tail"] == final_main_node
    by_node = {node.node_id: node for node in bound}
    assert by_node[main_node].parent_node_id == root_node.node_id
    assert by_node[main_node].cause_role == "main"
    assert by_node[secondary_node].parent_node_id == main_node
    assert by_node[secondary_node].cause_role == "secondary"
    assert by_node[final_main_node].parent_node_id == main_node
    assert by_node[final_main_node].cause_role == "main"
    assert by_node[main_node].participants[0].action == "收势"
    assert [item.action for item in ledger.bound_payloads["character_observations"]] == ["拔剑", "收势"]
    assert len([record for record in ledger.write_records if record["domain"] == "events"]) == 0
    _seed_metrics(tools)
    ledger.finish_chunk()
    assert len([record for record in ledger.write_records if record["domain"] == "events"]) == 1


@pytest.mark.asyncio
async def test_write_event_rejects_invalid_children_without_mutating_ledger() -> None:
    """2026-08-30 用于验证子节点合同失败时不会留下半棵事件树

    2026-09-13：子节点 type 是闭合参数，非法值在 schema 层翻成结构化拒绝
    （record=t1/e1, field=type, code=invalid_value），该节点不写入；
    根记录保留，换合法值重交即可（旧测试的裸 ValidationError 断言已不适用）。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    _call(tools, "write_event_root", _root_args())

    receipt = await _stage_rejection(tools, "write_event_child", _child_args(type="invalid"))

    assert receipt["record"] == "t1/e1"
    assert receipt["field"] == "type"
    assert receipt["code"] == "invalid_value"
    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    assert set(tree["nodes"]) == {"root"}
    assert ledger.bound_payloads["events"][0].description == "顾霜拔剑"

    _call(tools, "write_event_child", _child_args())
    _seed_metrics(tools)
    ledger.finish_chunk()
    assert len(ledger.bound_payloads["events"]) == 2


@pytest.mark.asyncio
async def test_write_event_rejects_duplicate_character_action_atomically() -> None:
    """2026-08-30 用于保证重复人物动作只拒绝那一条记录，不部分写入第二棵事件树

    2026-09-13：(人物, 动作) 同 chunk 唯一改在写入点拦下——第二条重复记录被单独拒绝，
    同回合的 finish_chunk 不受影响（逐条失败不阻塞收尾），第一棵树的记录与第二棵树的根
    都原样保留。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    entity = _entity_number(tools, "顾霜")
    llm = _SequenceLLM(
        [
            _tool_message(
                [
                    *_event_tree_calls(
                        tree_key="t1", description="顾霜拔剑", action="拔剑", entity=entity, call_id="call-t1"
                    ),
                    *_event_tree_calls(
                        tree_key="t2", description="顾霜再拔剑", action="拔剑", entity=entity, call_id="call-t2"
                    ),
                    _metrics_call(),
                    _finish_call(),
                ]
            )
        ]
    )

    result = await _invoke_graph(llm, ledger, max_iterations=1)

    receipts = _tool_receipts(result["messages"])
    duplicate = [receipt for receipt in receipts if '"code": "duplicate_observation"' in receipt]
    assert len(duplicate) == 1
    assert '"record": "t2/root/participant/1"' in duplicate[0]
    assert '"field": "action"' in duplicate[0]
    # 重复记录被单独拒绝，同回合收尾照常完成
    assert result["phase"] == "completed"
    assert ledger.chunk_finished
    finish_receipt = json.loads([item for item in receipts if '"status": "completed"' in item][-1])

    # 两棵树各只有一个根节点落账（t2 的根写入不受同树参与者被拒影响）；重复动作未写入
    assert finish_receipt["records"]["events"] == 2
    assert set(ledger.tree_key_index) == {"t1", "t2"}
    assert [item.action for item in ledger.observation_by_record.values()] == ["拔剑"]


def test_write_event_accepts_authorized_cause_tree() -> None:
    """2026-08-22 search_event 授权后的历史树可作跨章因果前驱

    2026-09-13：模型面不再回执 cross_chapter；等价验证=根节点落账后
    causal_event_refs 指向历史树根节点 id，且历史树已进授权视图供引用。
    """
    service = _EventHistoryQueryService([_history_tree("tree-h", "node-h-root", "前章旧事")])
    ledger = _ledger()
    tools = _tools(ledger, service)
    _entity_number(tools, "顾霜")
    _call(tools, "search_event", {"keyword": "旧事"})
    assert "tree-h" in ledger.history_tree_views

    _call(tools, "write_event_root", _root_args(cause_tree_id="tree-h"))
    _seed_metrics(tools)
    ledger.finish_chunk()

    bound_root = next(node for node in ledger.bound_payloads["events"] if node.cause_role == "root")
    assert bound_root.causal_event_refs == ["node-h-root"]
    assert bound_root.tree_id == next(iter(ledger.event_trees))


@pytest.mark.asyncio
async def test_write_event_rejects_unauthorized_cause_tree() -> None:
    """2026-08-22 未经 search_event 授权的 cause_tree_id 被拒绝

    2026-09-13：拒绝改结构化回执（record=t1/root, field=cause_tree_id,
    code=unknown_tree），该树不写入，模型可先 search_event 再引用历史树。
    """
    ledger = _ledger()
    tools = _tools(ledger)

    receipt = await _stage_rejection(
        tools,
        "write_event_root",
        _root_args(cause_tree_id="unknown-tree"),
    )

    assert receipt["record"] == "t1/root"
    assert receipt["field"] == "cause_tree_id"
    assert receipt["code"] == "unknown_tree"
    assert ledger.event_trees == {}
    assert ledger.tree_key_index == {}


def test_write_event_does_not_require_local_paragraph_indices() -> None:
    """2026-08-22 回归：事件写入不再按段落锚点派生证据

    节点不携带锚点/字符区间/哈希/证据；章级证据由持久化层盖章。
    全局 paragraph_id 与局部下标错位时，实时事件写入与收尾仍应正常。
    """
    text = _CHUNK_TEXT
    ledger = _ledger(
        paragraph_ids=[44, 45],
        char_spans=[(0, 4), (4, len(text))],
        texts=["\u201c住手\u201d", "回荡"],
    )
    tools = _tools(ledger)
    entity = _entity_number(tools, "顾霜")
    _call(tools, "write_event_root", _root_args())
    _call(tools, "write_character_participation", _character_participation_args(entity=entity))
    _seed_metrics(tools)
    receipt = ledger.finish_chunk()

    assert receipt["status"] == "completed"
    bound = ledger.bound_payloads["events"][0]
    dumped = bound.model_dump()
    assert "anchor_paragraph_ids" not in dumped
    assert "evidence" not in dumped
    assert "char_start" not in dumped
    assert dumped["description"] == "顾霜拔剑"


@pytest.mark.asyncio
async def test_failed_participation_resubmission_repairs_and_keeps_other_records() -> None:
    """2026-09-11 草稿补丁链（stash_event_draft + patches）已随小调用改造删除

    等价验证：单条参与者记录失败只指向该记录（结构化拒绝），已写入的根/子事件
    记录保留，重交同键记录即修复（旧断言"draft_repaired/pending_event_draft 清空"
    在新契约里没有对应物）。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    _entity_number(tools, "顾霜")
    _call(tools, "write_event_root", _root_args())
    _call(tools, "write_event_child", _child_args())

    rejected = await _stage_rejection(
        tools,
        "write_character_participation",
        _character_participation_args(entity=999),
    )

    assert rejected["record"] == "t1/root/participant/999"
    assert rejected["field"] == "entity"
    assert rejected["code"] == "unregistered_number"
    assert "1=顾霜" in rejected["message"]
    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    assert ledger.bound_payloads["events"][0].description == "顾霜拔剑"
    assert set(tree["nodes"]) == {"root", "e1"}

    _call(tools, "write_character_participation", _character_participation_args(entity=1))
    _seed_metrics(tools)
    receipt = ledger.finish_chunk()

    assert receipt["records"]["events"] == 2
    assert set(ledger.event_trees)
    bound = ledger.bound_payloads["events"]
    assert bound[0].participants[0].entity == "顾霜"


@pytest.mark.asyncio
async def test_record_revision_after_failure_keeps_accepted_value() -> None:
    """2026-09-11 补丁后仍失败→合并草稿成新基线；等价验证（2026-09-13）：

    同键记录重交是整条替换，失败的调用不改动已接受的同键记录（失败回滚到
    调用前快照），最后一次成功提交决定收尾值——旧"合并结果回写草稿"没有对应物。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    _entity_number(tools, "顾霜")
    _call(tools, "write_event_root", _root_args())
    _call(tools, "write_character_participation", _character_participation_args(entity=1, emotion=-1))

    rejected = await _stage_rejection(
        tools,
        "write_character_participation",
        _character_participation_args(entity=1, emotion="愤怒"),
    )

    assert rejected["record"] == "t1/root/participant/1"
    assert rejected["field"] == "emotion"
    assert rejected["code"] == "not_integer"
    assert "https://" not in rejected["message"]
    assert ledger.observation_by_record["t1/root/participant/1"].emotion == -1

    _call(tools, "write_character_participation", _character_participation_args(entity=1, emotion=-2))
    _seed_metrics(tools)
    ledger.finish_chunk()

    bound = ledger.bound_payloads["events"][0]
    assert bound.participants[0].entity == "顾霜"
    assert bound.participants[0].emotion == -2


@pytest.mark.asyncio
async def test_participation_rejections_point_at_record_and_keep_written_tree() -> None:
    """2026-09-11 补丁路径合同（无草稿/非法路径/越界路径报错）已随 patches 删除

    等价验证（2026-09-13）：参与者/子事件的定位键错误（未知 tree_key、未知
    node_key、乱序 order、保留 node_key）都给出可自纠的结构化拒绝，且不破坏
    已写入的事件树。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    _entity_number(tools, "顾霜")
    _call(tools, "write_event_root", _root_args())
    _call(tools, "write_event_child", _child_args())

    unknown_tree = await _stage_rejection(
        tools,
        "write_character_participation",
        _character_participation_args(tree_key="t9"),
    )
    assert unknown_tree["record"] == "t9/root/participant/1"
    assert unknown_tree["field"] == "tree_key"
    assert unknown_tree["code"] == "unknown_tree"
    assert "write_event_root" in unknown_tree["expected"]

    unknown_node = await _stage_rejection(
        tools,
        "write_character_participation",
        _character_participation_args(node_key="e9"),
    )
    assert unknown_node["record"] == "t1/e9/participant/1"
    assert unknown_node["field"] == "node_key"
    assert unknown_node["code"] == "unknown_node"
    assert "root, e1" in unknown_node["expected"]

    out_of_order = await _stage_rejection(
        tools,
        "write_event_child",
        _child_args(node_key="e2", order=1),
    )
    assert out_of_order["record"] == "t1/e2"
    assert out_of_order["field"] == "order"
    assert out_of_order["code"] == "out_of_order"
    assert "≥ 2" in out_of_order["expected"]

    reserved = await _stage_rejection(
        tools,
        "write_event_child",
        _child_args(node_key="root", order=2),
    )
    assert reserved["record"] == "t1/root"
    assert reserved["field"] == "node_key"
    assert reserved["code"] == "reserved"

    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    assert ledger.bound_payloads["events"][0].description == "顾霜拔剑"
    assert ledger.bound_payloads["events"][0].participants == []
    assert set(tree["nodes"]) == {"root", "e1"}
