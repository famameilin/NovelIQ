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
from langchain_core.messages import AIMessage

from src.agents.annotation.errors import AnnotationStageRejection
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.tool_batch import _invoke_tool
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import ChapterParagraphInfo
from tests.support.annotation_work_tools import build_annotation_tools
from tests.support.model_stream_adapter import StreamedFakeModelMixin

_CHUNK_TEXT = "“住手”回荡"


class _QueryServiceStub:
    """2026-08-19 用于为事件写入提供最小查询服务（无需检索历史）"""

    async def search_text(self, query, *, range_name, limit=50):
        del query, range_name, limit
        return []


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


def _seed_completion(tools: dict[str, Any]) -> None:
    """显式提交事件测试原文中的对话判定与必需指标"""
    _call(tools, "write_metrics", {"summary": "顾霜拔剑", "emotional_valence": 0, "narrative_function": "冲突"})
    _call(tools, "write_dialogue", {"candidate_index": 1, "verdict": "dialogue"})


def _root_args(**overrides: Any) -> dict:
    """2026-09-14 用于构造 write_event 根事件参数（默认一棵无参与者树的根 el=t1）"""
    payload: dict[str, Any] = {"el": "t1", "isroot": True, "description": "顾霜拔剑", "evidence": 1}
    payload.update(overrides)
    return payload


def _child_args(**overrides: Any) -> dict:
    """2026-09-14 用于构造 write_event 子事件参数（默认 main 子事件 el=t1/e1；无 order）"""
    payload: dict[str, Any] = {
        "el": "t1/e1",
        "isroot": False,
        "type": "main",
        "description": "顾霜收势",
        "evidence": 1,
    }
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


class _SequenceLLM(StreamedFakeModelMixin):
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


@pytest.mark.asyncio
async def test_write_event_defaults_character_participant_state_fields() -> None:
    """2026-10-04 用于验证参与者三态缺省归一（合同由必填即拒改为缺省落账）

    role/narrative_role/action/emotion 均可缺省：role 按登记大类给默认
    （character→主体）、叙事功能近义词归一（主角→主体）、emotion 越界按边界钳制；
    不再产生结构化拒绝，动态状态以空字段落账。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    entity = _entity_id(tools, "顾霜")
    _call(tools, "write_event", _root_args())

    receipt = _call(
        tools,
        "write_event",
        _root_args(characters=[{"entityid": entity, "narrative_role": "主角", "emotion": 5}]),
    )

    assert receipt["status"] == "written"
    observation = ledger.observation_by_record[f"t1/root/participant/{entity}"]
    assert observation.role_function is not None and observation.role_function == "主体"
    assert observation.emotion == 2
    assert observation.action is None
    (participant,) = ledger.bound_payloads["events"][0].participants
    assert participant.role == "主体"


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


@pytest.mark.asyncio
async def test_write_event_requires_chapter_evidence_and_preserves_anchor_on_rewrite() -> None:
    ledger = _ledger(
        paragraph_ids=[44, 45],
        char_spans=[(0, 4), (4, len(_CHUNK_TEXT))],
        texts=["“住手”", "回荡"],
    )
    tools = _tools(ledger)

    missing = await _stage_rejection(tools, "write_event", _root_args(evidence=None))
    assert (missing["field"], missing["code"]) == ("evidence", "missing_evidence")
    invalid = await _stage_rejection(tools, "write_event", _root_args(evidence=3))
    assert (invalid["field"], invalid["code"]) == ("evidence", "out_of_range")
    assert ledger.bound_payloads.get("events") is None

    _call(tools, "write_event", _root_args(evidence=1))
    root = ledger.bound_payloads["events"][0]
    root_id = root.node_id
    _call(tools, "write_event", _root_args(description="顾霜应声", evidence=None))
    assert root.node_id == root_id
    assert root.evidence_paragraph_id == 44

    child_missing = await _stage_rejection(tools, "write_event", _child_args(evidence=None))
    assert (child_missing["field"], child_missing["code"]) == ("evidence", "missing_evidence")
    assert len(ledger.bound_payloads["events"]) == 1
    _call(tools, "write_event", _child_args(evidence=2))
    child = ledger.bound_payloads["events"][1]
    assert child.evidence_paragraph_id == 45
    _call(tools, "write_event", _child_args(description="顾霜转身", evidence=None))
    assert child.evidence_paragraph_id == 45


def test_write_event_infers_single_paragraph_evidence() -> None:
    ledger = _ledger(paragraph_ids=[44])
    _call(_tools(ledger), "write_event", _root_args(evidence=None))
    assert ledger.bound_payloads["events"][0].evidence_paragraph_id == 44


@pytest.mark.asyncio
async def test_participation_rejections_point_at_record_and_keep_written_tree() -> None:
    """el 层级键的错误形态给可自纠的结构化拒绝且不破坏已写入的事件树

    2026-10-04 树键校验下沉：未知树键的子事件改为挂起（见
    test_write_event_child_before_root_defers_until_root_arrives），
    本测试只保留仍即时拒绝的形态——根写成路径形态（bad_el）、
    子事件占用保留键 root（reserved）、已建节点改写 type（immutable）。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    _entity_id(tools, "顾霜")
    _call(tools, "write_event", _root_args())
    _call(tools, "write_event", _child_args())

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
