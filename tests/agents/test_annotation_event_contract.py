"""事件层测试：实时小调用事件树语义（write_event 单工具 + finish）

2026-09-14 写入面重构后的覆盖（相对 09-13"根/子/参与者分工具"合同）：
- 根/子/参与者折叠进单工具 write_event：根 el=树键（如 t1）、子 el=树键/节点键
  （如 t1/e1），无 order 参数（树内先后=调用顺序）；characters 数组=该节点参与者
  完整集合，给出即整体替换；参与者记录键 "<节点记录>/participant/<entityid原值>"；
- 写入即生效：小调用直接落到 event_trees/bound_payloads，成功回执
  {"status": "written", "record": "t1/root" 或 "t1/e1"}；真实 node_id/tree_id 不外露；
- 唯一收尾 finish：工具体只回 {"status": "pending"}，收尾判定由账本做
  （本文件用 ledger.finish_chapter() 走同一汇点；旧名 finish_chunk 已退役）；
- 单条记录失败=结构化拒绝（record/field/code/expected），只回滚该调用；
  schema 层失败时 write_event 的记录键由 tool_record_key 生成（根 "t1/root"、
  子 "t1/e1"），ledger 层参与者拒绝仍是 "<节点记录>/participant/<entityid>"；
- 子事件必填 type（main/secondary）、根不得填 type；已建节点 type 不可改写；
  伏笔属性（isforeshadowing/confidence）只属于根，isforeshadowing=true 根必填 confidence；
- 实体引用统一 EntityRef：int=运行期编号 n、str=本章 write_entity 自定的 el 键；
  历史树引用（cause_tree_id）退役，search_event 授权的历史树根由 write_event 的
  foreshadowing_action + root_event_id 引用（2026-09-18 案例裁决工具删净）；
- 同一章内 (人物, 动作) 二元组唯一：重复的那条在写入点被拒绝，
  逐条失败不阻塞同回合的 finish 收尾。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.annotation.errors import AnnotationStageRejection
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import _invoke_tool, build_annotation_graph
from src.agents.annotation.prompts import build_chapter_message
from src.agents.annotation.schema import (
    ChapterParagraphInfo,
    EventTreeHistoryResult,
    SearchResult,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools

_CHUNK_TEXT = "“住手”回荡"


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


def _history_tree(
    tree_id: str,
    root_node_id: str,
    description: str,
    *,
    is_foreshadow_setup: bool = False,
) -> EventTreeHistoryResult:
    """2026-08-22 用于构造预设历史树根视图（search_event 授权的引用来源）"""
    return EventTreeHistoryResult(
        tree_id=tree_id,
        root_node_id=root_node_id,
        chapter_id=1,
        chapter_order=1,
        description=description,
        participants=[{"entity": "顾霜", "role": "主体"}],
        cross_chapter=False,
        is_foreshadow_setup=is_foreshadow_setup,
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
        current_chapter_text=_CHUNK_TEXT,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChapterParagraphInfo(
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


def _entity_id(tools: dict[str, Any], name: str, entity_type: str = "character") -> str:
    """2026-09-19 用于登记实体（el 用登记名）并取回 run 级 uuid id（参与者/说话人引用面）"""
    receipt = _call(tools, "write_entity", {"name": name, "entity_type": entity_type, "el": name})
    return str(receipt["id"])


def _seed_metrics(tools: dict[str, Any]) -> None:
    """2026-09-13 用于提交最小指标载荷（finish 的硬前提）"""
    _call(tools, "write_metrics", {"summary": "顾霜拔剑", "emotional_valence": 0, "narrative_function": "冲突"})


def _root_args(**overrides: Any) -> dict:
    """2026-09-14 用于构造 write_event 根事件参数（默认一棵无参与者树的根 el=t1）"""
    payload: dict[str, Any] = {"el": "t1", "isroot": True, "description": "顾霜拔剑"}
    payload.update(overrides)
    return payload


def _child_args(**overrides: Any) -> dict:
    """2026-09-14 用于构造 write_event 子事件参数（默认 main 子事件 el=t1/e1；无 order）"""
    payload: dict[str, Any] = {"el": "t1/e1", "isroot": False, "type": "main", "description": "顾霜收势"}
    payload.update(overrides)
    return payload


def _participant(**overrides: Any) -> dict:
    """2026-09-19 用于构造 characters 条目（entityid 为 run 级 uuid id，测试里显式传入）"""
    payload: dict[str, Any] = {
        "entityid": "00000000-0000-0000-0000-000000000001",
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
    """2026-09-14 用于构造唯一 finish 收尾声明（判定推迟到本回合调用处理完后）"""
    return _write_call("finish", {}, call_id="call-finish-chapter")


def _event_tree_calls(
    *,
    tree_key: str,
    description: str,
    action: str,
    entity: int,
    call_id: str,
) -> list[dict]:
    """2026-09-14 用于构造一棵最小事件树的小调用组（根 + 挂人物参与的子事件）

    参与者内联在子事件的 characters 数组里（旧 participation 独立调用已并入
    write_event）：同 (人物, 动作) 重复时整条子事件调用被拒并回滚，根不受影响。
    """
    return [
        _write_call(
            "write_event",
            {"el": tree_key, "isroot": True, "description": description},
            call_id=f"{call_id}-root",
        ),
        _write_call(
            "write_event",
            {
                "el": f"{tree_key}/e1",
                "isroot": False,
                "type": "main",
                "description": f"{description}收势",
                "characters": [_participant(entityid=entity, action=action)],
            },
            call_id=f"{call_id}-child",
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
    """2026-09-13 用于在给定账本上执行单章 LangGraph"""
    tools = build_annotation_tools(_QueryServiceStub(), ledger)
    graph = build_annotation_graph(llm, tools, ledger=ledger, max_iterations=max_iterations)
    return await graph.ainvoke(
        {
            "messages": [
                SystemMessage(content="test"),
                HumanMessage(
                    content=build_chapter_message(
                                                chapter_text=_CHUNK_TEXT,
                        candidates=ledger.dialogue_candidates,
                    )
                ),
            ],
            "phase": "chapter_open",
            "iterations": 0,
            "error": None,
        }
    )


def test_write_event_returns_tree_and_authorizes_root() -> None:
    """2026-08-22 创建事件树由服务端派发节点 id 并登记授权

    2026-09-14 单工具 write_event：根 el=t1、参与者内联 characters，回执
    {status: written, record: t1/root / t1/e1, content}；2026-09-19 id 纪律下
    content 携带落库终值与节点 run 级 uuid id（=落库 event_id，树级 uuid 不外露），
    真实 id 亦可从账本读取——授权集合仍登记根与子节点 id（挂树的授权来源）。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    entity = _entity_id(tools, "顾霜")
    root_receipt = _call(tools, "write_event", _root_args(characters=[_participant(entityid=entity)]))
    root_content = root_receipt.pop("content")
    assert root_receipt == {"status": "written", "record": "t1/root"}
    child_receipt = _call(tools, "write_event", _child_args())
    child_content = child_receipt.pop("content")
    assert child_receipt == {"status": "written", "record": "t1/e1"}

    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    root_node_id = tree["root_node_id"]
    assert root_content == {
        "id": root_node_id,
        "description": "顾霜拔剑",
        "isforeshadowing": False,
        "confidence": None,
        "characters": [
            {"entity": "顾霜", "role": "主体", "narrative_role": "主体", "action": "拔剑", "emotion": -1}
        ],
    }
    assert child_content["id"] == tree["nodes"]["e1"]
    assert child_content["type"] == "main"
    assert "isforeshadowing" not in child_content
    assert "node_id" not in child_content and "tree_id" not in child_content
    assert root_node_id in ledger.authorized_event_ids
    assert set(tree["nodes"].values()) <= ledger.authorized_event_ids
    bound = ledger.bound_payloads["events"]
    assert [node.node_id for node in bound] == list(tree["nodes"].values())
    assert bound[0].tree_id == tree["tree_id"]
    assert bound[0].cause_role == "root"
    assert bound[0].description == "顾霜拔剑"
    assert bound[0].participants[0].action == "拔剑"
    assert ledger.bound_payloads["character_observations"][0].action == "拔剑"

    _seed_metrics(tools)
    receipt = ledger.finish_chapter()
    assert receipt["status"] == "completed"
    assert receipt["chapter_id"] == 1
    assert receipt["records"]["events"] == 2
    assert receipt["records"]["character_observations"] == 1


@pytest.mark.asyncio
async def test_write_event_requires_character_participant_state_fields() -> None:
    """2026-08-30 用于拒绝未携带人物动态状态的角色参与者

    2026-09-14 参与者并入 write_event.characters：三态在账本按登记类型强制分流，
    缺失在 ledger 层被翻译成结构化拒绝（record=t1/root/participant/1,
    field=narrative_role, code=missing），只指向该条记录且不写入；
    整节点参与者集合是完整替换，失败时原节点保持无参与者。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    entity = _entity_id(tools, "顾霜")
    _call(tools, "write_event", _root_args())

    receipt = await _stage_rejection(
        tools,
        "write_event",
        _root_args(characters=[{"entityid": entity, "role": "主体"}]),
    )

    assert receipt["record"] == f"t1/root/participant/{entity}"
    assert receipt["field"] == "narrative_role"
    assert receipt["code"] == "missing"
    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    assert ledger.bound_payloads["events"][0].participants == []
    assert set(tree["nodes"]) == {"root"}
    assert ledger.tree_key_index == {"t1": tree["tree_id"]}
    assert ledger.observation_by_record == {}


def test_write_event_without_participants_derives_empty_character_domain() -> None:
    """2026-08-30 用于允许无人物事件明确收尾空人物动态领域

    2026-09-14：无参与者树用 write_event(isroot=true) 即时落账，再用唯一
    finish 收尾；character_observations 随事件域派生的语义不变。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    _call(tools, "write_event", _root_args(description="山门夜雨"))
    _seed_metrics(tools)

    receipt = ledger.finish_chapter()

    assert receipt["records"]["character_observations"] == 0
    assert ledger.bound_payloads["character_observations"] == []
    assert "events" not in ledger.missing_content_domains()


def test_write_event_empty_completion_does_not_invent_event() -> None:
    """2026-08-30 用于允许无事件章节显式收尾且不捏造事件

    2026-09-14：空域不再用逐域声明，直接 finish 收尾；
    空事件是合法终态，不建树不建节点。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    _seed_metrics(tools)

    receipt = ledger.finish_chapter()

    assert receipt["status"] == "completed"
    assert receipt["records"]["events"] == 0
    assert ledger.event_trees == {}
    assert ledger.bound_payloads["events"] == []
    assert ledger.bound_payloads["character_observations"] == []


@pytest.mark.asyncio
async def test_write_event_isforeshadowing_creates_thread_binding() -> None:
    """2026-09-13 伏笔即事件树：isforeshadowing=true 根事件携带伏笔属性

    2026-09-14 收敛：伏笔属性只剩 isforeshadowing+confidence（值域 high/medium/low，
    写进 payoff_likelihood），且只属于根——根缺 confidence 在写入点结构化拒绝
    （record=t2/root, field=confidence, code=missing），子事件带伏笔属性同样拒绝
    （field=isforeshadowing, code=not_on_child）且不建出该子节点。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    _entity_id(tools, "顾霜")
    _call(tools, "write_event", _root_args())

    missing = await _stage_rejection(
        tools,
        "write_event",
        _root_args(el="t2", description="神秘玉戒发光", isforeshadowing=True),
    )
    assert missing["record"] == "t2/root"
    assert missing["field"] == "confidence"
    assert missing["code"] == "missing"

    _call(
        tools,
        "write_event",
        _root_args(el="t2", description="神秘玉戒发光", isforeshadowing=True, confidence="medium"),
    )

    on_child = await _stage_rejection(
        tools,
        "write_event",
        _child_args(el="t2/e1", description="顾霜注意到玉戒", isforeshadowing=True),
    )
    assert on_child["record"] == "t2/e1"
    assert on_child["field"] == "isforeshadowing"
    assert on_child["code"] == "not_on_child"
    assert "t2/e1" not in ledger.event_trees[ledger.tree_key_index["t2"]]["nodes"]

    bound = ledger.bound_payloads["events"]
    root = next(node for node in bound if node.is_foreshadow_setup)
    assert root.is_foreshadow_setup is True
    assert root.description == "神秘玉戒发光"
    assert root.payoff_likelihood == "medium"
    tree = ledger.event_trees[ledger.tree_key_index["t2"]]
    assert tree["isforeshadowing"] is True
    assert tree["root_node_id"] == root.node_id


@pytest.mark.asyncio
async def test_write_event_rejects_invalid_children_without_mutating_ledger() -> None:
    """2026-08-30 用于验证子节点合同失败时不会留下半棵事件树

    2026-09-14：子节点 type 是闭合枚举，非法值在 schema 层翻成结构化拒绝
    （record=t1/e1, field=type, code=invalid_value），该节点不写入；
    根记录保留，换合法值重交即可（旧测试的裸 ValidationError 断言已不适用）。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    _call(tools, "write_event", _root_args())

    receipt = await _stage_rejection(tools, "write_event", _child_args(type="invalid"))

    assert receipt["record"] == "t1/e1"
    assert receipt["field"] == "type"
    assert receipt["code"] == "invalid_value"
    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    assert set(tree["nodes"]) == {"root"}
    assert ledger.bound_payloads["events"][0].description == "顾霜拔剑"

    _call(tools, "write_event", _child_args())
    _seed_metrics(tools)
    ledger.finish_chapter()
    assert len(ledger.bound_payloads["events"]) == 2


@pytest.mark.asyncio
async def test_write_event_rejects_duplicate_character_action_atomically() -> None:
    """2026-08-30 用于保证重复人物动作只拒绝那一条记录，不部分写入第二棵事件树

    2026-09-14：参与者内联在 write_event 调用里——(人物, 动作) 重复时整条子事件
    调用在写入点被拒并回滚自己（第二棵树只剩根落账，坏的那条没进账），
    同回合的 finish 不受影响（逐条失败不阻塞收尾），第一棵树的记录原样保留。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    entity = _entity_id(tools, "顾霜")
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
    assert f'"record": "t2/e1/participant/{entity}"' in duplicate[0]
    assert '"field": "action"' in duplicate[0]
    # 重复记录被单独拒绝，同回合收尾照常完成
    assert result["phase"] == "completed"
    assert ledger.chapter_finished
    finish_receipt = json.loads([item for item in receipts if '"status": "completed"' in item][-1])

    # t1 根+子与 t2 根都落账（重复动作所在的 t2 子事件整条回滚）；重复动作未写入
    assert finish_receipt["records"]["events"] == 3
    assert set(ledger.tree_key_index) == {"t1", "t2"}
    assert [item.action for item in ledger.observation_by_record.values()] == ["拔剑"]


def test_write_event_accepts_authorized_history_root() -> None:
    """2026-08-22 search_event 授权后的历史树根可被本章引用（挂进既有伏笔树）

    2026-09-14：根事件不再有 cause_tree_id（跨章因果边退役）。
    2026-09-18 案例裁决工具删净：原 resolve_foreshadowing_case 的挂树行为由
    write_event(foreshadowing_action=..., root_event_id=...) 承接——search_event
    授权的历史伏笔树根作 root_event_id，本次写入的本章节点作挂树事件，成功即登记
    无案例的 foreshadowing 解决项（case_id=""）。
    """
    service = _EventHistoryQueryService(
        [_history_tree("tree-h", "node-h-root", "前章旧事", is_foreshadow_setup=True)]
    )
    ledger = _ledger()
    tools = _tools(ledger, service)
    _call(tools, "search_event", {"keyword": "旧事"})
    assert "tree-h" in ledger.history_tree_views
    assert "node-h-root" in ledger.authorized_event_ids

    receipt = _call(
        tools,
        "write_event",
        _root_args(
            description="顾霜拔剑",
            foreshadowing_action="reinforce",
            root_event_id="node-h-root",
        ),
    )

    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    assert receipt["status"] == "written"
    assert receipt["record"] == "t1/root"
    assert receipt["content"]["foreshadowing"] == {
        "action": "reinforce",
        "root_event_id": "node-h-root",
        "event_id": tree["root_node_id"],
    }
    resolved = ledger.resolved_cases[0]
    assert resolved.case_id == ""
    assert resolved.action == "foreshadowing"
    assert resolved.foreshadowing_action == "reinforce"
    assert resolved.foreshadowing_root_event_id == "node-h-root"
    assert resolved.foreshadowing_event_id == tree["root_node_id"]
    assert ledger.chapter_finished is False


@pytest.mark.asyncio
async def test_write_event_rejects_unauthorized_entity_reference() -> None:
    """2026-08-22 未经登记/检索授权的引用被结构化拒绝（cause_tree_id 的今日等价面）

    2026-09-19 id 纪律：实体引用统一 EntityRef——本章 write_entity 登记的
    el 键或 run 级 uuid id；两者都不是的引用在写入点结构化拒绝
    （record=t1/root/participant/ghost, field=entityid,
    code=unknown_entity_id），expected 指向 id/el 双来源；该节点参与者不写入。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    _entity_id(tools, "顾霜")
    _call(tools, "write_event", _root_args())

    receipt = await _stage_rejection(
        tools,
        "write_event",
        _root_args(characters=[_participant(entityid="ghost")]),
    )

    assert receipt["record"] == "t1/root/participant/ghost"
    assert receipt["field"] == "entityid"
    assert receipt["code"] == "unknown_entity_id"
    assert ledger.bound_payloads["events"][0].participants == []
    assert ledger.observation_by_record == {}


def test_write_event_does_not_require_local_paragraph_indices() -> None:
    """2026-08-22 回归：事件写入不再按段落锚点派生证据

    节点不携带锚点/字符区间/哈希/证据；章级证据由持久化层盖章。
    全局 paragraph_id 与局部下标错位时，实时事件写入与收尾仍应正常；
    2026-09-14 段落级监督随 write_metrics.labels 提交；2026-09-18 标签用段首可见号
    （正文 `N：`，此处即 1 基顺序号），全局 paragraph_id 只留在持久化侧。
    """
    text = _CHUNK_TEXT
    ledger = _ledger(
        paragraph_ids=[44, 45],
        char_spans=[(0, 4), (4, len(text))],
        texts=["“住手”", "回荡"],
    )
    tools = _tools(ledger)
    entity = _entity_id(tools, "顾霜")
    _call(tools, "write_event", _root_args(characters=[_participant(entityid=entity)]))
    _call(
        tools,
        "write_metrics",
        {
            "summary": "顾霜拔剑",
            "emotional_valence": 0,
            "narrative_function": "冲突",
            "labels": [{"paragraph_id": 1, "emotion": -1}],
        },
    )
    receipt = ledger.finish_chapter()

    assert receipt["status"] == "completed"
    bound = ledger.bound_payloads["events"][0]
    dumped = bound.model_dump()
    assert "anchor_paragraph_ids" not in dumped
    assert "evidence" not in dumped
    assert "char_start" not in dumped
    assert dumped["description"] == "顾霜拔剑"
    assert [
        (label.paragraph_id, label.emotion) for label in ledger.bound_payloads["paragraph_labels"]
    ] == [(44, -1)]


@pytest.mark.asyncio
async def test_failed_participation_resubmission_repairs_and_keeps_other_records() -> None:
    """2026-09-11 草稿补丁链（stash_event_draft + patches）已随小调用改造删除

    等价验证（2026-09-14）：characters 里未登记引用只指向该参与者记录（结构化拒绝，
    field=entityid/code=unknown_entity_id），已写入的根/子事件记录保留，
    重交同键根记录即修复（旧断言"draft_repaired/pending_event_draft 清空"没有对应物）。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    entity = _entity_id(tools, "顾霜")
    _call(tools, "write_event", _root_args())
    _call(tools, "write_event", _child_args())

    rejected = await _stage_rejection(
        tools,
        "write_event",
        _root_args(characters=[_participant(entityid="00000000-0000-0000-0000-000000000999")]),
    )

    assert rejected["record"] == "t1/root/participant/00000000-0000-0000-0000-000000000999"
    assert rejected["field"] == "entityid"
    assert rejected["code"] == "unknown_entity_id"
    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    assert ledger.bound_payloads["events"][0].description == "顾霜拔剑"
    assert set(tree["nodes"]) == {"root", "e1"}

    _call(tools, "write_event", _root_args(characters=[_participant(entityid=entity)]))
    _seed_metrics(tools)
    receipt = ledger.finish_chapter()

    assert receipt["records"]["events"] == 2
    assert set(ledger.event_trees)
    bound = ledger.bound_payloads["events"]
    assert bound[0].participants[0].entity == "顾霜"


@pytest.mark.asyncio
async def test_record_revision_after_failure_keeps_accepted_value() -> None:
    """2026-09-11 补丁后仍失败→合并草稿成新基线；等价验证（2026-09-14）：

    characters 条目里 emotion 写语气词在 schema 层即失败（ParticipantArg 前置校验），
    翻译出的拒绝记录键按 tool_record_key 回落到节点键 "t1/root"（不再是参与者
    路径）；失败的调用不改动已接受的同键记录，最后一次成功提交决定收尾值。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    entity = _entity_id(tools, "顾霜")
    _call(tools, "write_event", _root_args(characters=[_participant(entityid=entity, emotion=-1)]))

    rejected = await _stage_rejection(
        tools,
        "write_event",
        _root_args(characters=[_participant(entityid=entity, emotion="愤怒")]),
    )

    assert rejected["record"] == "t1/root"
    assert rejected["field"] == "emotion"
    # 旧合同 not_integer（int 解析失败）；2026-09-14 语气词由 ParticipantArg 前置校验
    # 拒绝，pydantic value_error 族按 _STAGE_FIELD_CODES 翻成 invalid_combination
    assert rejected["code"] == "invalid_combination"
    assert "https://" not in rejected["message"]
    assert next(iter(ledger.observation_by_record.values())).emotion == -1

    _call(tools, "write_event", _root_args(characters=[_participant(entityid=entity, emotion=-2)]))
    _seed_metrics(tools)
    ledger.finish_chapter()

    bound = ledger.bound_payloads["events"][0]
    assert bound.participants[0].entity == "顾霜"
    assert bound.participants[0].emotion == -2


@pytest.mark.asyncio
async def test_participation_rejections_point_at_record_and_keep_written_tree() -> None:
    """2026-09-11 补丁路径合同（无草稿/非法路径/越界路径报错）已随 patches 删除

    等价验证（2026-09-14）：el 层级键的错误形态都给可自纠的结构化拒绝且不破坏
    已写入的事件树——未知树键（unknown_tree）、根写成路径形态（bad_el）、
    子事件占用保留键 root（reserved）、已建节点改写 type（immutable，
    旧"树内顺序"约束已由"调用顺序=树内先后"取代）。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    _entity_id(tools, "顾霜")
    _call(tools, "write_event", _root_args())
    _call(tools, "write_event", _child_args())

    unknown_tree = await _stage_rejection(
        tools,
        "write_event",
        {"el": "t9/e1", "isroot": False, "type": "main", "description": "未知树上的子事件"},
    )
    assert unknown_tree["record"] == "t9/e1"
    assert unknown_tree["field"] == "el"
    assert unknown_tree["code"] == "unknown_tree"
    assert "write_event" in unknown_tree["expected"]

    bad_root_el = await _stage_rejection(
        tools,
        "write_event",
        {"el": "t1/e9", "isroot": True, "description": "根事件写成路径"},
    )
    assert bad_root_el["record"] == "t1/e9/root"
    assert bad_root_el["field"] == "el"
    assert bad_root_el["code"] == "bad_el"

    reserved = await _stage_rejection(
        tools,
        "write_event",
        {"el": "t1/root", "isroot": False, "type": "main", "description": "占用根键"},
    )
    assert reserved["record"] == "t1/root"
    assert reserved["field"] == "el"
    assert reserved["code"] == "reserved"

    immutable = await _stage_rejection(
        tools,
        "write_event",
        {"el": "t1/e1", "isroot": False, "type": "secondary", "description": "顾霜收势"},
    )
    assert immutable["record"] == "t1/e1"
    assert immutable["field"] == "type"
    assert immutable["code"] == "immutable"

    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    assert ledger.bound_payloads["events"][0].description == "顾霜拔剑"
    assert ledger.bound_payloads["events"][0].participants == []
    assert set(tree["nodes"]) == {"root", "e1"}
