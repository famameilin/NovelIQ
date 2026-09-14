"""2026-09-13 实时写入改造 / 2026-09-14 写入面重构后的合同测试（小调用写入即生效、唯一 finish_chapter 收尾）

覆盖用户裁定的必要行为边界：同轮多调用只计一轮、失败不丢失已写入记录、
逐条失败不阻塞收尾、重试按记录更新不重复、关系写入即入图、对话收尾时
一次性默认否定、事件实时按调用顺序生长。

2026-09-14 合同变化点（相对 09-13 九工具面，见 docs/write-surface-2026-0914-test-contract.md）：
- 写入面为五个领域工具（write_entity/write_metrics/write_event/write_relation/write_dialogue）
  + 唯一 finish_chapter；事件根/子/参与者折叠进单工具 write_event：
  el 层级键挂树（根 "t1"、子 "t1/e2"），树内先后=调用顺序，没有 order 参数；
- 句标签收编进 write_metrics(labels=[{paragraph_id, emotion}])，绑定载荷键
  sentence_labels → paragraph_labels；
- 参与写从独立工具改为 write_event 的 characters 数组（给出即整节点替换）；
  (人物, 动作) 重复、三态必填/非 character 不接受三态等校验全部保留；
- 收尾声明 ledger.finish_chunk() → ledger.finish_chapter()，chunk_finished → chapter_finished；
  快照/回滚语义保留（snapshot 含 entity_el_index，失败只回滚该条调用）。

此处以账本层为主（tools + ledger 直调 apply_* / finish_chapter），
回合计数的图循环语义用本文件末尾的真实 LangGraph 用例覆盖；
末尾另有一条漂移守卫：模型可见文案点名的工具必须在当前工具面上真实存在。
"""

from __future__ import annotations

import json
import re

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from src.agents.annotation.errors import AnnotationProtocolError, AnnotationStageRejection
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import (
    _invoke_tool,
    _missing_domains_reminder,
    build_annotation_graph,
)
from src.agents.annotation.prompts import (
    READER_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_case_pool_notice,
    build_chunk_message,
    build_reader_block_message,
    build_writer_chapter_message,
)
from src.agents.annotation.schema import (
    ENTITY_TAG_MAX_CHARS,
    ENTITY_TAG_MAX_COUNT,
    ChunkMetricsInput,
    ChunkParagraphInfo,
    SearchResult,
)
from src.agents.annotation.tools import (
    _DOMAIN_ORDER,
    AnnotationToolLedger,
    build_annotation_tools,
)


class _QueryService:
    """2026-09-13 用于提供无数据库依赖的查询桩"""

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """2026-09-13 用于返回空案例检索结果"""
        del query, hidden_case_ids, case_type, limit
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        """2026-09-13 用于返回空正文命中"""
        del query, range_name, limit
        return []

    def search_event_history(self, query, *, limit=50):
        """2026-09-13 用于返回空历史事件树"""
        del query, limit
        return []

    def fetch_active_case_details(self, case_id):
        """2026-09-13 用于表示没有 active 案例"""
        del case_id
        return None


def _chunk_text() -> str:
    """2026-09-13 用于提供含两个对话候选的单段章文本"""
    return "“住手！”顾霜喝道。“退下。”众人散去，夜色渐深。"


def _ledger(**overrides) -> AnnotationToolLedger:
    """2026-09-14 用于构造带事实图与段落坐标的账本（labels 段号校验依赖 paragraph_info）"""
    text = _chunk_text()
    kwargs = {
        "run_scope": "run-1",
        "current_chapter_id": 1,
        "current_chunk_id": 1,
        "current_chunk_text": text,
        "allow_future_context": False,
        "graph": FactGraph(),
        "paragraph_info": ChunkParagraphInfo(
            paragraph_ids=[1],
            char_spans=[(0, len(text))],
            texts=[text],
        ),
    }
    kwargs.update(overrides)
    return AnnotationToolLedger(**kwargs)


def _tools(ledger: AnnotationToolLedger) -> dict:
    """2026-09-13 用于按工具名索引新工具面"""
    return {tool.name: tool for tool in build_annotation_tools(_QueryService(), ledger)}


async def _call(tools: dict, name: str, args: dict) -> dict:
    """2026-09-13 用于按生产路径（graph._invoke_tool）执行单个小调用并解析回执

    走 graph 入口而不是直接 ainvoke：schema 层的 pydantic 失败在真运行里也由该层
    翻译成结构化拒绝，测试必须覆盖同一条路径。
    """
    call = {"name": name, "args": args, "id": f"call-{name}", "type": "tool_call"}
    return json.loads(await _invoke_tool(tools, call))


async def _rejection(tools: dict, name: str, args: dict) -> AnnotationStageRejection:
    """2026-09-13 用于执行预期被拒的小调用并取回结构化拒绝"""
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _call(tools, name, args)
    return excinfo.value


async def _register_entities(tools: dict) -> dict[str, int]:
    """2026-09-14 用于登记测试用实体并返回编号表（编号/el 键供关系、对话、事件引用）"""
    numbers = {}
    for name, entity_type in (("顾霜", "character"), ("众人", "organization"), ("山门", "location")):
        receipt = await _call(
            tools,
            "write_entity",
            {"name": name, "entity_type": entity_type, "el": name},
        )
        numbers[name] = receipt["n"]
    return numbers


async def _seed_metrics(tools: dict) -> None:
    """2026-09-13 用于提交最小指标载荷（收尾前置条件）"""
    await _call(
        tools,
        "write_metrics",
        {"summary": "顾霜喝止众人", "emotional_valence": 0, "narrative_function": "冲突"},
    )


async def _finish(ledger: AnnotationToolLedger, tools: dict) -> dict:
    """2026-09-14 用于按生产路径收尾（写指标后调用唯一 finish_chapter 的结算汇点）"""
    await _seed_metrics(tools)
    return ledger.finish_chapter()


# ---------------------------------------------------------------------------
# 事件：实时生长、三态与重复动态
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_children_grow_in_call_order_with_trunk_rules() -> None:
    """2026-09-14 事件树实时生长：main 顺延主链、secondary 挂当时链尾

    树内先后=调用顺序（order 参数退役）：根 el=树键，子 el=树键/节点键，
    同轮按序调用即按序挂树，参与者随节点的 characters 数组内联提交。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    await _register_entities(tools)
    root_receipt = await _call(tools, "write_event", {"el": "t1", "isroot": True, "description": "顾霜喝止众人"})
    root_content = root_receipt.pop("content")
    assert root_receipt == {"status": "written", "record": "t1/root"}
    assert root_content["description"] == "顾霜喝止众人"
    assert root_content["characters"] == []
    first_receipt = await _call(
        tools,
        "write_event",
        {"el": "t1/e1", "isroot": False, "type": "main", "description": "顾霜喝道"},
    )
    first_content = first_receipt.pop("content")
    assert first_receipt == {"status": "written", "record": "t1/e1"}
    assert first_content["type"] == "main"
    assert first_content["tree_id"] == root_content["tree_id"]
    await _call(
        tools,
        "write_event",
        {"el": "t1/e2", "isroot": False, "type": "secondary", "description": "众人散去"},
    )

    events = list(ledger.bound_payloads["events"])
    root, first, second = events
    assert [event.cause_role for event in events] == ["root", "main", "secondary"]
    assert [event.description for event in events] == ["顾霜喝止众人", "顾霜喝道", "众人散去"]
    assert first.parent_node_id == root.node_id
    # main 成为新链尾，secondary 挂在当时链尾（= main 子节点）
    assert second.parent_node_id == first.node_id
    assert all(event.tree_id == root.tree_id for event in events)

    receipt = await _finish(ledger, tools)
    assert receipt["status"] == "completed"
    assert receipt["records"]["events"] == 3


@pytest.mark.asyncio
async def test_character_participation_requires_all_three_state_fields() -> None:
    """2026-09-14 人物三态必填、不自动填默认值；非 character 条目不接受三态字段

    参与写并入 write_event 的 characters 数组后，分流规则不变：
    character 条目缺三态→账本级 code=missing；只给部分三态→schema 级整条拒绝
    （invalid_combination）；emotion 越界→out_of_range；非 character 带三态→
    observation_on_noncharacter（旧 not_character/is_character 双向拒绝的合并面）。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    numbers = await _register_entities(tools)
    await _call(tools, "write_event", {"el": "t1", "isroot": True, "description": "顾霜喝止众人"})

    missing = await _rejection(
        tools,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [{"entityid": numbers["顾霜"], "role": "主体"}],
        },
    )
    assert (missing.record, missing.field, missing.code) == (
        f"t1/root/participant/{numbers['顾霜']}",
        "narrative_role",
        "missing",
    )
    assert "三字段必填" in (missing.expected or "")

    partial = await _rejection(
        tools,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [
                {"entityid": numbers["顾霜"], "role": "主体", "narrative_role": "主体", "emotion": 1}
            ],
        },
    )
    assert (partial.record, partial.code) == ("t1/root", "invalid_combination")
    assert "必须同时提供" in (partial.expected or "")

    out_of_range = await _rejection(
        tools,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [
                {
                    "entityid": numbers["顾霜"],
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝道",
                    "emotion": 3,
                }
            ],
        },
    )
    assert (out_of_range.record, out_of_range.field, out_of_range.code, out_of_range.expected) == (
        "t1/root",
        "emotion",
        "out_of_range",
        "-2..2 整数分值（-2 强烈负面 … 2 强烈正面）",
    )

    not_character = await _rejection(
        tools,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [
                {
                    "entityid": numbers["众人"],
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "退下",
                    "emotion": 0,
                }
            ],
        },
    )
    assert (not_character.record, not_character.field, not_character.code) == (
        f"t1/root/participant/{numbers['众人']}",
        "narrative_role",
        "observation_on_noncharacter",
    )


@pytest.mark.asyncio
async def test_noncharacter_participation_derives_no_observation() -> None:
    """2026-09-14 只有 character 参与者派生人物动态状态，地点/组织只入参与列表

    旧两条参与写（write_character_participation + write_noncharacter_participation）
    合并为一次 write_event 的 characters 完整集合，分流与派生语义不变。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    numbers = await _register_entities(tools)
    await _call(
        tools,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [
                {
                    "entityid": numbers["顾霜"],
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝道",
                    "emotion": -1,
                },
                {"entityid": numbers["山门"], "role": "地点"},
            ],
        },
    )

    observations = list(ledger.bound_payloads["character_observations"])
    assert [(item.character, item.action, item.emotion) for item in observations] == [("顾霜", "喝道", -1)]
    participants = list(ledger.bound_payloads["events"])[0].participants
    assert [participant.entity for participant in participants] == ["顾霜", "山门"]
    assert participants[1].narrative_role is None


@pytest.mark.asyncio
async def test_duplicate_observation_pair_rejected_per_record_at_write() -> None:
    """2026-09-14 同一 chunk 内 (人物, 动作) 重复：只拒绝后写的那一条，先写的照常保留

    小调用合同下重复在校验时点即写入点拦下，拒绝 message 指出已记在哪条记录，
    修正那条后无需重交全树；重复的参与条目不落账，节点其余内容不受影响。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    numbers = await _register_entities(tools)
    await _call(tools, "write_event", {"el": "t1", "isroot": True, "description": "顾霜喝止众人"})
    first = await _call(
        tools,
        "write_event",
        {
            "el": "t1/e1",
            "isroot": False,
            "type": "main",
            "description": "子事件1",
            "characters": [
                {
                    "entityid": numbers["顾霜"],
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝道",
                    "emotion": 0,
                }
            ],
        },
    )
    first_content = first.pop("content")
    assert first == {"status": "written", "record": "t1/e1"}
    assert first_content["characters"] == [
        {"entity": "顾霜", "role": "主体", "narrative_role": "主体", "action": "喝道", "emotion": 0}
    ]

    duplicate = await _rejection(
        tools,
        "write_event",
        {
            "el": "t1/e2",
            "isroot": False,
            "type": "main",
            "description": "子事件2",
            "characters": [
                {
                    "entityid": numbers["顾霜"],
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝道",
                    "emotion": 0,
                }
            ],
        },
    )

    assert duplicate.record == f"t1/e2/participant/{numbers['顾霜']}"
    assert duplicate.field == "action"
    assert duplicate.code == "duplicate_observation"
    assert "t1/e1/participant" in duplicate.receipt()["message"]
    # 先写的那条与原节点结构都保留，重复记录没有落账
    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    nodes_by_id = {event.node_id: event for event in ledger.bound_payloads["events"]}
    assert [participant.entity for participant in nodes_by_id[tree["nodes"]["e1"]].participants] == ["顾霜"]
    assert nodes_by_id[tree["nodes"]["e2"]].participants == []

    # 改成不同动作后正常落账，两条动态状态都在
    await _call(
        tools,
        "write_event",
        {
            "el": "t1/e2",
            "isroot": False,
            "type": "main",
            "description": "子事件2",
            "characters": [
                {
                    "entityid": numbers["顾霜"],
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "退去",
                    "emotion": 0,
                }
            ],
        },
    )
    assert [item.action for item in ledger.bound_payloads["character_observations"]] == ["喝道", "退去"]


@pytest.mark.asyncio
async def test_el_shape_reserved_key_and_unknown_tree_are_rejected_per_record() -> None:
    """2026-09-14 el 层级键的形态约束：子必填 type、root 是保留节点键、树键必须先建，拒绝只指向该条记录

    order 参数退役（树内先后=调用顺序）后，事件写入点保留的形态校验是：
    子缺 type→missing；t1/root 占用保留键→reserved；未建树→unknown_tree；
    根带路径→bad_el。任一失败都不得动到同树已写入的根。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    await _call(tools, "write_event", {"el": "t1", "isroot": True, "description": "顾霜喝止众人"})
    await _call(
        tools,
        "write_event",
        {"el": "t1/e1", "isroot": False, "type": "main", "description": "顾霜喝道"},
    )

    missing_type = await _rejection(
        tools,
        "write_event",
        {"el": "t1/e2", "isroot": False, "description": "众人散去"},
    )
    assert (missing_type.record, missing_type.field, missing_type.code) == ("t1/e2", "type", "missing")
    assert "main" in (missing_type.expected or "") and "secondary" in (missing_type.expected or "")

    reserved = await _rejection(
        tools,
        "write_event",
        {"el": "t1/root", "isroot": False, "type": "main", "description": "众人散去"},
    )
    assert (reserved.record, reserved.field, reserved.code) == ("t1/root", "el", "reserved")

    unknown_tree = await _rejection(
        tools,
        "write_event",
        {"el": "t9/e1", "isroot": False, "type": "main", "description": "众人散去"},
    )
    assert (unknown_tree.record, unknown_tree.field, unknown_tree.code) == ("t9/e1", "el", "unknown_tree")

    bad_el = await _rejection(
        tools,
        "write_event",
        {"el": "t1/e2", "isroot": True, "description": "众人散去"},
    )
    assert (bad_el.record, bad_el.field, bad_el.code) == ("t1/e2/root", "el", "bad_el")

    # 四次失败全部只回滚自己：树里仍只有先写入的根与 e1
    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    assert sorted(tree["nodes"]) == ["e1", "root"]
    assert len(ledger.bound_payloads["events"]) == 2


@pytest.mark.asyncio
async def test_child_replay_updates_description_and_participant_replay_updates_state() -> None:
    """2026-09-14 同键重放按更新语义：子节点只可改述、参与者重写三态不新增记录

    order 退役后结构位唯一不可改的字段是 type（code=immutable）；
    characters 给出即整节点替换，同条目重写=更新动态状态。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    numbers = await _register_entities(tools)
    await _call(tools, "write_event", {"el": "t1", "isroot": True, "description": "顾霜喝止众人"})
    await _call(
        tools,
        "write_event",
        {"el": "t1/e1", "isroot": False, "type": "main", "description": "顾霜喝道"},
    )
    await _call(
        tools,
        "write_event",
        {"el": "t1/e1", "isroot": False, "type": "main", "description": "顾霜厉声喝道"},
    )

    immutable = await _rejection(
        tools,
        "write_event",
        {"el": "t1/e1", "isroot": False, "type": "secondary", "description": "众人散去"},
    )
    assert (immutable.record, immutable.field, immutable.code) == ("t1/e1", "type", "immutable")

    await _call(
        tools,
        "write_event",
        {
            "el": "t1/e1",
            "isroot": False,
            "type": "main",
            "description": "顾霜厉声喝道",
            "characters": [
                {
                    "entityid": numbers["顾霜"],
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝道",
                    "emotion": 2,
                }
            ],
        },
    )
    await _call(
        tools,
        "write_event",
        {
            "el": "t1/e1",
            "isroot": False,
            "type": "main",
            "description": "顾霜厉声喝道",
            "characters": [
                {
                    "entityid": numbers["顾霜"],
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝道",
                    "emotion": -1,
                }
            ],
        },
    )

    events = list(ledger.bound_payloads["events"])
    assert [event.cause_role for event in events] == ["root", "main"]
    assert events[1].description == "顾霜厉声喝道"
    assert events[1].participants[0].emotion == -1
    assert len(ledger.observation_by_record) == 1


@pytest.mark.asyncio
async def test_root_foreshadowing_attributes_are_validated_at_write_and_updated_in_place() -> None:
    """2026-09-14 伏笔属性只属于根、isforeshadowing=true 必填 confidence；根重放按更新语义改写属性

    跨章因果前驱（cause_tree_id）退役后，事件根在写入点强制的属性合同是：
    根带 isforeshadowing 缺 confidence → missing；子带伏笔属性 → not_on_child；
    根带 type → not_on_root；同键重放更新描述与伏笔属性（不新增节点），
    取代旧"一经确定不可改写"的结算期校验。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    await _register_entities(tools)

    missing_confidence = await _rejection(
        tools,
        "write_event",
        {"el": "t1", "isroot": True, "description": "顾霜喝止众人", "isforeshadowing": True},
    )
    assert (missing_confidence.record, missing_confidence.field, missing_confidence.code) == (
        "t1/root",
        "confidence",
        "missing",
    )
    assert "events" not in ledger.bound_payloads

    await _call(
        tools,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "isforeshadowing": True,
            "confidence": "high",
        },
    )
    root = ledger.bound_payloads["events"][0]
    assert root.is_foreshadow_setup is True
    assert str(root.payoff_likelihood) == "high"

    not_on_child = await _rejection(
        tools,
        "write_event",
        {
            "el": "t1/e1",
            "isroot": False,
            "type": "main",
            "description": "顾霜喝道",
            "isforeshadowing": True,
        },
    )
    assert (not_on_child.record, not_on_child.field, not_on_child.code) == ("t1/e1", "isforeshadowing", "not_on_child")

    not_on_root = await _rejection(
        tools,
        "write_event",
        {"el": "t1", "isroot": True, "type": "main", "description": "顾霜喝止众人"},
    )
    assert (not_on_root.record, not_on_root.field, not_on_root.code) == ("t1/root", "type", "not_on_root")

    # 根重放更新语义：改描述与伏笔属性，不新增节点
    replay = await _call(
        tools,
        "write_event",
        {"el": "t1", "isroot": True, "description": "顾霜厉声喝止众人", "isforeshadowing": False},
    )
    assert replay["record"] == "t1/root"
    assert len(ledger.bound_payloads["events"]) == 1
    assert ledger.bound_payloads["events"][0].description == "顾霜厉声喝止众人"
    assert ledger.bound_payloads["events"][0].payoff_likelihood is None
    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    assert tree["isforeshadowing"] is False
    assert tree["root_node_id"] == ledger.bound_payloads["events"][0].node_id


@pytest.mark.asyncio
async def test_second_root_with_same_tree_key_updates_description_in_place() -> None:
    """2026-09-14 同树键重交按更新语义：只改描述与伏笔属性，不新增节点"""
    ledger = _ledger()
    tools = _tools(ledger)
    await _call(tools, "write_event", {"el": "t1", "isroot": True, "description": "顾霜喝止众人"})
    await _call(tools, "write_event", {"el": "t1", "isroot": True, "description": "顾霜厉声喝止众人"})

    assert len(ledger.bound_payloads["events"]) == 1
    assert ledger.bound_payloads["events"][0].description == "顾霜厉声喝止众人"
    assert len(ledger.event_trees) == 1
    root_node_id = ledger.event_trees[ledger.tree_key_index["t1"]]["root_node_id"]
    assert root_node_id == ledger.bound_payloads["events"][0].node_id


# ---------------------------------------------------------------------------
# 对话：收尾时才默认否
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dialogue_default_is_applied_once_at_chapter_finish() -> None:
    """2026-09-12/14 未提交候选只在 finish_chapter 收尾时一次性默认 not_dialogue"""
    ledger = _ledger()
    tools = _tools(ledger)
    await _register_entities(tools)
    assert len(ledger.dialogue_candidates) == 2

    await _call(
        tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": 1, "tone": "愤怒"},
    )
    # 提交第一条不得把其余候选提前判否
    assert ledger.dialogue_missing_indexes == []
    assert 2 not in ledger.written_dialogues

    receipt = await _finish(ledger, tools)
    assert receipt["dialogue_defaulted"] == [2]
    assert sorted(ledger.written_dialogues) == [1, 2]
    assert ledger.written_dialogues[2].verdict == "not_dialogue"

    # 收尾后 chunk 由系统冻结：再写同一序号被阶段协议拒绝，收尾结果不变
    ledger.complete_active_chunk()
    with pytest.raises(AnnotationProtocolError, match="阶段 completed"):
        await _call(tools, "write_dialogue", {"candidate_index": 1, "verdict": "not_dialogue"})
    assert ledger.ready_chunk is not None
    assert sorted(ledger.written_dialogues) == [1, 2]


@pytest.mark.asyncio
async def test_dialogue_replay_updates_verdict_in_place() -> None:
    """2026-09-13 同序号重交按更新语义（旧契约的"candidate_index 重复"报错已退役）"""
    ledger = _ledger()
    tools = _tools(ledger)
    await _register_entities(tools)
    await _call(
        tools, "write_dialogue", {"candidate_index": 1, "verdict": "dialogue", "speaker": 1, "tone": "平静"}
    )
    await _call(
        tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "inner_monologue"},
    )
    assert list(ledger.written_dialogues) == [1]
    assert ledger.written_dialogues[1].speaker is None

    missing_speaker_rule = await _rejection(
        tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "not_dialogue", "tone": "平静"},
    )
    assert missing_speaker_rule.code == "invalid_combination"

    out_of_range = await _rejection(
        tools,
        "write_dialogue",
        {"candidate_index": 9, "verdict": "dialogue"},
    )
    assert (out_of_range.field, out_of_range.code) == ("candidate_index", "out_of_range")


@pytest.mark.asyncio
async def test_dialogue_receipt_reports_chapter_progress() -> None:
    """2026-09-13 对话回执带本章进度：判一条写一条时不必自己记已判到哪

    run c80105cc 实测：同一份 speaker/tone 映射在 ch2 誊写 2 遍、ch4 誊写 3 遍
    （约 1.2 万字符），根因是思考不入历史、进度只存在模型心里。回执给
    written/total 两个数，进度成为可回读的事实；同序号重写不推进 written。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    await _register_entities(tools)

    first = await _call(
        tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": 1, "tone": "平静"},
    )
    assert first["progress"] == {"written": 1, "total": len(ledger.dialogue_candidates)}

    replay = await _call(tools, "write_dialogue", {"candidate_index": 1, "verdict": "not_dialogue"})
    assert replay["progress"]["written"] == 1

    second = await _call(tools, "write_dialogue", {"candidate_index": 2, "verdict": "not_dialogue"})
    assert second["progress"]["written"] == 2


# ---------------------------------------------------------------------------
# 关系：写入即入图、重写整体替换
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relations_are_flushed_on_write_and_replayed_by_endpoint_pair() -> None:
    """2026-09-13 关系写入即入图：同一对端点重写即整体替换，图终态=本章完整集合

    旧合同"关系先暂存、结束关系域时一次性入图"已废止：实测写入即 flush，
    等价验证=同对端点第二次提交换类型后图与操作日志都只留后写的那条。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    numbers = await _register_entities(tools)
    await _call(
        tools,
        "write_relation",
        {"from_entity": numbers["顾霜"], "to_entity": numbers["众人"], "relation_type": "领导"},
    )
    assert len(ledger.graph.active_relations) == 1
    assert len(ledger.graph.relation_assert_ops) == 1

    # 同一条边重交不新增（图按端点对去重）
    await _call(
        tools,
        "write_relation",
        {"from_entity": numbers["顾霜"], "to_entity": numbers["众人"], "relation_type": "领导"},
    )
    assert len(ledger.graph.active_relations) == 1

    # 同一对端点换类型即整体替换：账本只留一条，图与操作日志也只剩后写的类型
    await _call(
        tools,
        "write_relation",
        {"from_entity": numbers["顾霜"], "to_entity": numbers["众人"], "relation_type": "敌对"},
    )
    assert len(ledger.written_relations) == 1
    assert len(ledger.graph.active_relations) == 1
    assert len(ledger.graph.relation_assert_ops) == 1
    assert str(next(iter(ledger.written_relations.values())).relation_type) == "敌对"


@pytest.mark.asyncio
async def test_relation_write_after_chunk_completed_is_rejected() -> None:
    """2026-09-14 收尾并冻结后 chunk 关闭：再写关系被拒，收尾载荷保持不变"""
    ledger = _ledger()
    tools = _tools(ledger)
    numbers = await _register_entities(tools)
    await _call(
        tools,
        "write_relation",
        {"from_entity": numbers["顾霜"], "to_entity": numbers["众人"], "relation_type": "领导"},
    )
    await _finish(ledger, tools)
    ledger.complete_active_chunk()

    with pytest.raises(AnnotationProtocolError, match="阶段 completed"):
        await _call(
            tools,
            "write_relation",
            {"from_entity": numbers["顾霜"], "to_entity": numbers["众人"], "relation_type": "敌对"},
        )
    assert len(ledger.written_relations) == 1
    assert len(ledger.ready_chunk.events) == 0
    assert ledger.ready_chunk.dialogues == []


# ---------------------------------------------------------------------------
# 实体：部分更新合并语义（docstring"只提交本次变化的字段"的服务端兑现）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_entity_partial_update_preserves_unsubmitted_fields() -> None:
    """2026-09-14 已登记实体部分更新：未提交字段保留现值、null 删键、tags 空数组清空

    旧实现整条替换——模型按 docstring 指引只提交变化字段时其余字段被静默抹掉，
    可见合同与服务端行为相悖（content 回显把该现状显形后修复）。合并语义：
    省略字段保留；tags 提交空数组=清空；attributes 提交即 JSON Merge Patch。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    first = await _call(tools, "write_entity", {
        "name": "顾霜", "entity_type": "character", "el": "a",
        "tags": ["冷面"], "description": "佩刀女子", "attributes": {"兵器": "刀", "旧痕": "疤"},
    })
    update = await _call(tools, "write_entity", {
        "name": "顾霜", "entity_type": "character", "el": "a",
        "description": "护院教头", "attributes": {"旧痕": None, "佩饰": "玉"},
    })
    assert update["content"] == {
        "name": "顾霜",
        "entity_type": "character",
        "tags": ["冷面"],
        "description": "护院教头",
        "attributes": {"兵器": "刀", "佩饰": "玉"},
        "n": first["n"],
    }
    assert ledger.written_entities["顾霜"].tags == ["冷面"]

    cleared = await _call(tools, "write_entity", {
        "name": "顾霜", "entity_type": "character", "el": "a", "tags": [],
    })
    assert cleared["content"]["tags"] == []
    assert cleared["content"]["description"] == "护院教头"
    assert cleared["content"]["attributes"] == {"兵器": "刀", "佩饰": "玉"}


# ---------------------------------------------------------------------------
# 收尾：唯一 finish_chapter 的判定边界
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finish_ignores_failed_records_from_same_round() -> None:
    """2026-09-13 收尾不受同回合失败记录影响：失败只回滚自己，收尾按已写入内容完成

    旧合同要求"本回合有失败就拒绝收尾，先修正再重交"，那条规则把收尾绑到无关记录的
    成功上（末轮出现一次失败即整章作废）；逐条失败在调用点已有独立回执，收尾只管
    chunk 能不能装出来（指标缺提交才拒绝）。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    await _register_entities(tools)
    await _seed_metrics(tools)

    receipt = ledger.finish_chapter()

    assert receipt["status"] == "completed"
    assert "warnings" not in receipt
    assert ledger.chapter_finished


@pytest.mark.asyncio
async def test_chapter_finish_requires_one_metrics_submission() -> None:
    """2026-09-14 指标是收尾硬前提：缺 write_metrics 的 finish_chapter 被拒

    旧合同的"指标域必须显式结束"已废止：其他内容域可空（收尾回执给出各域条数），
    唯独指标必须有载荷，缺则 code=missing_record。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    with pytest.raises(AnnotationStageRejection) as excinfo:
        ledger.finish_chapter()
    assert excinfo.value.code == "missing_record"
    assert (excinfo.value.record, excinfo.value.field) == ("finish_chapter", "metrics")

    await _seed_metrics(tools)
    assert ledger.finish_chapter()["status"] == "completed"
    assert isinstance(ledger.metrics_payload, ChunkMetricsInput)


@pytest.mark.asyncio
async def test_finish_chapter_protocol_guards() -> None:
    """2026-09-14 收尾协议的调用点校验：逐域 finish_domain 已删除、未收尾不得冻结

    2026-09-13 取消暂存与逐域结束：工具面上没有 finish_domain，
    未收尾时 complete_active_chunk 直接报错点名 finish_chapter。
    """
    ledger = _ledger()
    tools = _tools(ledger)

    assert "finish_domain" not in tools
    assert "finish_chapter" in tools
    assert "finish_chunk" not in tools
    with pytest.raises(ValueError, match="先调用 finish_chapter"):
        ledger.complete_active_chunk()

    await _finish(ledger, tools)
    ledger.complete_active_chunk()
    assert ledger.phase == "completed"
    with pytest.raises(Exception, match="阶段 completed"):
        ledger.complete_active_chunk()


@pytest.mark.asyncio
async def test_event_entity_gate_requires_search_graph_once_per_chapter() -> None:
    """2026-09-13 实体准入闸门只对本章第一次登记生效（同轮多条登记不被自己挡住）"""
    ledger = _ledger(graph=FactGraph(history_entity_types={"旧人": "character"}))
    tools = _tools(ledger)
    with pytest.raises(Exception, match="search_graph"):
        await _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "顾霜"})

    await tools["search_graph"].ainvoke({"entities": ["顾霜"]})
    await _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    await _call(tools, "write_entity", {"name": "众人", "entity_type": "organization", "el": "众人"})


# ---------------------------------------------------------------------------
# 段落标签与单条失败边界
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paragraph_label_replay_updates_emotion_and_bad_submission_rejected() -> None:
    """2026-09-14 段落标签随 write_metrics 整域提交：同段号重交覆盖分值，越界段号只拒这一次提交

    句标签（write_sentence_label 按原文区间绑定）退役：paragraph_id 取
    ledger.paragraph_info.paragraph_ids，越界段号在 apply_metrics 写入点整次
    提交拒绝并指明是哪一条标签，此前已提交的标签照常保留。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    base = {"summary": "顾霜喝止众人", "emotional_valence": 0, "narrative_function": "冲突"}
    first = await _call(tools, "write_metrics", {**base, "labels": [{"paragraph_id": 1, "emotion": -1}]})
    assert first["record"] == "metrics"
    replay = await _call(tools, "write_metrics", {**base, "labels": [{"paragraph_id": 1, "emotion": 1}]})
    assert replay["record"] == first["record"]

    labels = list(ledger.bound_payloads["paragraph_labels"])
    assert len(labels) == 1
    assert labels[0].emotion == 1
    assert labels[0].paragraph_id in ledger.paragraph_info.paragraph_ids

    missing = await _rejection(
        tools,
        "write_metrics",
        {**base, "labels": [{"paragraph_id": 99, "emotion": 0}]},
    )
    assert (missing.record, missing.field, missing.code) == ("metrics", "paragraph_id", "out_of_range")
    assert len(ledger.bound_payloads["paragraph_labels"]) == 1


@pytest.mark.asyncio
async def test_failed_call_keeps_previously_written_records_in_same_round() -> None:
    """2026-09-14 失败不丢失已写入记录：同轮后面的失败调用只回滚自己

    参与者并入 write_event 的 characters 后，被拒数组在账本改写中途抛出：
    snapshot/restore 必须把该节点已派生的动态状态原样带回，先写记录不受影响。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    numbers = await _register_entities(tools)
    await _call(
        tools,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [
                {
                    "entityid": numbers["顾霜"],
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝道",
                    "emotion": 1,
                }
            ],
        },
    )
    snapshot = ledger.snapshot()
    with pytest.raises(AnnotationStageRejection):
        await tools["write_event"].ainvoke(
            {
                "el": "t1",
                "isroot": True,
                "description": "顾霜喝止众人",
                "characters": [
                    {
                        "entityid": numbers["众人"],
                        "role": "主体",
                        "narrative_role": "主体",
                        "action": "退下",
                        "emotion": 0,
                    },
                    {
                        "entityid": numbers["顾霜"],
                        "role": "主体",
                        "narrative_role": "主体",
                        "action": "喝止",
                        "emotion": 1,
                    },
                ],
            }
        )
    ledger.restore(snapshot)

    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    root = next(event for event in ledger.bound_payloads["events"] if event.node_id == tree["root_node_id"])
    assert [participant.entity for participant in root.participants] == ["顾霜"]
    assert root.participants[0].emotion == 1
    assert [(item.character, item.action, item.emotion) for item in ledger.observation_by_record.values()] == [
        ("顾霜", "喝道", 1)
    ]


# ---------------------------------------------------------------------------
# 图循环：一轮多调用只计一个回合
# ---------------------------------------------------------------------------


class _SingleReplyLLM:
    """2026-09-13 用于返回单个回合的多工具回复并记录累计轮次"""

    def __init__(self, response) -> None:
        """2026-09-13 用于保存唯一回复"""
        self.response = response
        self.calls = 0

    def bind_tools(self, tools):
        """2026-09-13 用于兼容 langchain 绑定协议"""
        del tools
        return self

    async def ainvoke(self, messages):
        """2026-09-13 用于返回该回复（第二个回合直接耗尽）"""
        del messages
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("本轮不应触发第二次模型调用")
        return self.response


@pytest.mark.asyncio
async def test_same_round_small_calls_counts_as_single_iteration() -> None:
    """2026-09-14 同轮多个小调用 + 唯一 finish_chapter 整体只计一个模型回合

    收尾在本回合调用处理完后判定成功 → 自动冻结并完成章节，
    因此循环不再有第二轮，"达到上限"错误也不触发（旧合同逐域结束需要多轮）。
    """
    from langchain_core.messages import AIMessage

    ledger = _ledger()
    tools = build_annotation_tools(_QueryService(), ledger)
    ledger.graph_queried = True
    parallel_calls = [
        {
            "name": "write_entity",
            "args": {"name": "顾霜", "entity_type": "character", "el": "顾霜"},
            "id": "c1",
            "type": "tool_call",
        },
        {
            "name": "write_entity",
            "args": {"name": "众人", "entity_type": "organization", "el": "众人"},
            "id": "c2",
            "type": "tool_call",
        },
        {
            "name": "write_metrics",
            "args": {"summary": "顾霜喝止众人", "emotional_valence": 0, "narrative_function": "冲突"},
            "id": "c3",
            "type": "tool_call",
        },
        {"name": "finish_chapter", "args": {}, "id": "c4", "type": "tool_call"},
    ]
    llm = _SingleReplyLLM(AIMessage(content="", tool_calls=parallel_calls))
    graph = build_annotation_graph(llm, tools, ledger=ledger, max_iterations=1)
    state = await graph.ainvoke(
        {
            "messages": [SystemMessage(content="test"), HumanMessage(content="chunk")],
            "phase": "chunk_open",
            "iterations": 0,
            "error": None,
        }
    )

    assert state["iterations"] == 1
    assert state["error"] is None
    assert llm.calls == 1
    # 收尾判定在本回合全部调用处理完后执行：工具体只回 pending，结算回执才是结论
    finish_receipt = json.loads(str(state["messages"][-1].content))
    assert finish_receipt["status"] == "completed"
    assert finish_receipt["records"]["entities"] == 2
    assert state["phase"] == "completed"
    assert ledger.chapter_finished


# ---------------------------------------------------------------------------
# 参数面与收尾事务边界
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_undeclared_argument_is_rejected_per_call_not_dropped() -> None:
    """2026-09-14 未声明参数被整条拒绝：多余字段不静默丢弃，字段名随回执回到模型"""
    ledger = _ledger()
    tools = _tools(ledger)

    extra_entity = await _rejection(
        tools,
        "write_entity",
        {"name": "顾霜", "entity_type": "character", "el": "顾霜", "aliases": ["顾姑娘"]},
    )
    assert (extra_entity.record, extra_entity.field) == ("entity/顾霜", "aliases")
    assert extra_entity.code == "unknown_field"
    assert "不接受参数 aliases" in extra_entity.receipt()["message"]
    assert ledger.written_entities == {}

    numbers = await _register_entities(tools)
    await _call(tools, "write_event", {"el": "t1", "isroot": True, "description": "顾霜喝止众人"})
    extra_child = await _rejection(
        tools,
        "write_event",
        {
            "el": "t1/e1",
            "isroot": False,
            "type": "main",
            "description": "众人散去",
            "order": 1,
        },
    )
    assert (extra_child.record, extra_child.field) == ("t1/e1", "order")
    assert extra_child.code == "unknown_field"

    extra_participation = await _rejection(
        tools,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [
                {
                    "entityid": numbers["众人"],
                    "role": "客体",
                    "aliases": ["众人甲"],
                }
            ],
        },
    )
    assert (extra_participation.record, extra_participation.field) == ("t1/root", "aliases")
    assert extra_participation.code == "unknown_field"
    assert ledger.event_trees[ledger.tree_key_index["t1"]]["nodes"] == {
        "root": ledger.event_trees[ledger.tree_key_index["t1"]]["root_node_id"]
    }


@pytest.mark.asyncio
async def test_chapter_finish_is_atomic(monkeypatch) -> None:
    """2026-09-14 finish_chapter 收尾自带事务边界：ready_chunk 构造失败即整体回滚，已写入记录保留

    旧合同"事件域结算多棵树组装到一半失败即整体回滚暂存记录"已废止：
    现合同没有领域级结算，等价验证=唯一收尾的构造阶段失败时账本回到收尾前
    （已写入记录原样保留），修正后重试可正常收尾。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    numbers = await _register_entities(tools)
    for tree_key, action in (("t1", "喝道"), ("t2", "退去")):
        await _call(
            tools,
            "write_event",
            {
                "el": tree_key,
                "isroot": True,
                "description": f"{tree_key} 根事件",
                "characters": [
                    {
                        "entityid": numbers["顾霜"],
                        "role": "主体",
                        "narrative_role": "主体",
                        "action": action,
                        "emotion": 0,
                    }
                ],
            },
        )
    await _seed_metrics(tools)

    original = AnnotationToolLedger._build_ready_chunk
    failing = {"on": True}

    def _flaky(self):
        """2026-09-13 用于在第 1 次收尾构造 ready_chunk 时注入故障（模拟构造期校验失败）"""
        if failing["on"]:
            raise ValueError("收尾校验失败: 注入的构造期故障")
        return original(self)

    # 账本是 slots dataclass，实例不允许新增属性，只能按类打补丁
    monkeypatch.setattr(AnnotationToolLedger, "_build_ready_chunk", _flaky)

    with pytest.raises(AnnotationStageRejection) as excinfo:
        ledger.finish_chapter()

    assert excinfo.value.code == "assembly_failed"
    # 收尾整体回滚：ready_chunk/chapter_finished 回到收尾前，已写入记录与两棵树都保留
    assert ledger.ready_chunk is None
    assert not ledger.chapter_finished
    assert set(ledger.tree_key_index) == {"t1", "t2"}
    assert ledger.write_records == []
    assert [item.action for item in ledger.observation_by_record.values()] == ["喝道", "退去"]

    failing["on"] = False
    receipt = ledger.finish_chapter()

    assert receipt["status"] == "completed"
    assert receipt["records"]["events"] == 2
    assert {record["domain"] for record in ledger.write_records} == {
        "entities",
        "metrics",
        "events",
        "relations",
        "dialogues",
    }
    assert [event.description for event in ledger.bound_payloads["events"]] == ["t1 根事件", "t2 根事件"]


_MODEL_VISIBLE_TOOL_NAME = re.compile(
    r"\b(?:write|search|resolve|close|push|ask)_[a-z_]+|\bfinish_chapter\b|\bsend_message\b"
)
# 模型可见文案里合法但不在写者工具面上的名字：send_message 是读者面的单次上报通道，
# 写者只会经 ask_reader 反问，从不直接调用它。
_NON_WRITER_FACE_TOOL_NAMES = frozenset({"send_message"})


def _model_visible_texts() -> dict[str, str]:
    """2026-09-13 用于汇总模型可见且会点名工具的文案（工具 docstring、收尾提醒、提示词区块）"""
    tools = _tools(_ledger())
    text = _chunk_text()
    texts = {f"tool.{name}.description": str(tool.description) for name, tool in tools.items()}
    # 缺内容提醒的三种真实取值：无缺口、全缺、仅内容域缺（写者面全放开后不再分解锁面）
    for label, missing in (
        ("nothing_missing", []),
        ("all_missing", list(_DOMAIN_ORDER)),
        ("content_missing", [domain for domain in _DOMAIN_ORDER if domain != "entities"]),
    ):
        texts[f"hint.{label}"] = _missing_domains_reminder(missing) or ""
    texts["prompt.system"] = SYSTEM_PROMPT
    texts["prompt.reader_system"] = READER_SYSTEM_PROMPT
    texts["prompt.case_pool"] = build_case_pool_notice()
    texts["prompt.chunk_message"] = build_chunk_message(
        chunk_index=1, chunk_total=1, chunk_text=text, candidates=[]
    )
    texts["prompt.writer_chapter"] = build_writer_chapter_message(reader_reports_view="(无)", candidates=[])
    texts["prompt.reader_block"] = build_reader_block_message(
        block_number=1,
        block_total=1,
        paragraph_info=ChunkParagraphInfo(paragraph_ids=[1], char_spans=[(0, len(text))], texts=[text]),
        candidates=[],
    )
    return texts


def test_model_visible_text_references_only_registered_tools() -> None:
    """2026-09-13 漂移守卫：模型可见文案点名的工具必须在当前工具面上真实存在

    删/改工具时最先失效的是散文引用（工具 docstring、收尾提醒、提示词区块）：
    模型照文案调用不存在的工具会白烧一个回合，且没有 schema 报错可自纠。
    此处把三类文案一次性扫一遍，名字必须落在已注册工具或显式跨面白名单里。
    """
    registered = set(_tools(_ledger()))
    matches = {
        source: sorted(set(_MODEL_VISIBLE_TOOL_NAME.findall(text)))
        for source, text in _model_visible_texts().items()
    }
    unknown = {
        source: [name for name in names if name not in registered and name not in _NON_WRITER_FACE_TOOL_NAMES]
        for source, names in matches.items()
    }

    assert {source: names for source, names in unknown.items() if names} == {}
    # 反空转：文案里确实点到了多个工具名，正则没失配
    assert len({name for names in matches.values() for name in names}) >= 8


# ---------------------------------------------------------------------------
# 2026-09-13 根因修复：可见约束 / 登记即进池
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_case_hands_out_number_usable_in_same_chunk() -> None:
    """2026-09-13 登记即进池：push_case 当场发案例编号，本案例当章即可解决

    run 1b388eb3 第 2 章实锤：模型写错一条关系后推案例想撤边，回执只给 target_key、
    不给编号，池里也搜不到 ⇒ 5 轮 33% 预算烧在零命中检索上。登记即进池后，
    同章拿到编号即可 resolve_fact_case 撤掉那条边。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    numbers = await _register_entities(tools)
    await _call(
        tools,
        "write_relation",
        {"from_entity": numbers["顾霜"], "to_entity": numbers["众人"], "relation_type": "敌对"},
    )
    assert ledger.graph.relation_exists("顾霜", "众人", "敌对")

    pushed = await _call(
        tools,
        "push_case",
        {
            "description": "误建关系：顾霜与众人并非敌对，需解除该边",
            "keys": ["顾霜", "众人", "敌对"],
            "type": "关系修正",
        },
    )
    assert pushed["accepted"] is True
    case_number = pushed["case_number"]

    resolved = await _call(
        tools,
        "resolve_fact_case",
        {
            "case_number": case_number,
            "reason": "误建关系，解除该边",
            "from_entity": numbers["顾霜"],
            "to_entity": numbers["众人"],
            "relation_type": "敌对",
            "change_kind": "解除",
        },
    )

    assert resolved["accepted"] is True
    assert resolved["case_number"] == case_number
    assert not ledger.graph.relation_exists("顾霜", "众人", "敌对")
    assert pushed["target_key"] in ledger.resolved_case_ids


@pytest.mark.asyncio
async def test_search_pool_renders_pending_case_from_same_chunk() -> None:
    """2026-09-13 检索面接线：本 chunk 登记的待建案例随 search_pool 结果返回并带 pending 标记

    仓储层的匹配语义（关键词/枚举/池规模）由 DB 用例覆盖，此处只验工具层把待建案例
    透传给查询服务并把结果渲染进回执、取回同一个案例编号。
    """

    class _PendingEchoQueryService(_QueryService):
        """2026-09-13 用于把传入的待建案例原样作为检索结果返回"""

        def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
            del query, case_type, limit
            return SearchResult(results=[case for case in pending_cases if case.id not in hidden_case_ids])

    ledger = _ledger()
    tools = {tool.name: tool for tool in build_annotation_tools(_PendingEchoQueryService(), ledger)}
    pushed = await _call(
        tools,
        "push_case",
        {
            "description": "玉戒尺在第 5 章异常发光",
            "keys": ["玉戒尺"],
            "type": "伏笔疑点",
        },
    )

    found = await _call(tools, "search_pool", {"query": "玉戒尺"})

    assert [item["case_number"] for item in found["results"]] == [pushed["case_number"]]
    assert found["results"][0]["pending"] is True
    assert found["results"][0]["keys"] == ["玉戒尺"]


def test_event_tools_declare_same_round_local_keys_on_schema() -> None:
    """2026-09-14 漂移守卫：事件树的同轮依赖必须写在模型可见面

    run 431a66d8 归因：模型把"先建树、再挂节点/参与者"当成依赖上一轮回执，
    明明可以同批按序调用却拆成多轮，白烧回合。写入面合并为单工具 write_event 后，
    护栏锁住两层可见面——el 层级键承诺（由你指定、写入即生效、同轮直接可用）与
    根/子/收尾文案承诺（一轮按顺序写完 + 同批收尾），防止文案漂移回"要等回执"。
    """
    tools = _tools(_ledger())
    event_params = convert_to_openai_tool(tools["write_event"])["function"]["parameters"]["properties"]
    el_description = event_params["el"]["description"]
    for fragment in ("由你指定", "树键/节点键", "写入即生效", "同轮"):
        assert fragment in el_description

    entity_params = convert_to_openai_tool(tools["write_entity"])["function"]["parameters"]["properties"]
    entity_el = entity_params["el"]["description"]
    for fragment in ("由你指定", "写入即生效", "同轮"):
        assert fragment in entity_el

    event_description = str(tools["write_event"].description)
    assert "整棵树可以在一轮里按顺序写完" in event_description
    assert "写入即生效，同轮后面的调用直接可用" in event_description
    finish_description = str(tools["finish_chapter"].description)
    assert "同一批调用里按顺序写完" in finish_description
    assert "finish_chapter" in event_description or "不等回执" in event_description


def test_tool_surface_carries_constraints_enforced_on_server() -> None:
    """2026-09-13 漂移守卫：服务端强制的约束必须出现在模型可见的工具参数说明里

    run 1b388eb3 第 2 章实锤：entity.tags 每标签 ≤5 字、关系两端实体类型约束都只在
    服务端校验，发给 provider 的工具签名里没有 ⇒ 模型只能靠被拒来猜（6 字标签被拒后
    原样重试一次），端点类型不符也只能反复试。约束一处在 schema 校验、一处在工具
    参数说明，本条护栏锁住后者，防再次退化成"只有服务端知道"。
    """
    tools = _tools(_ledger())

    relation_params = convert_to_openai_tool(tools["write_relation"])["function"]["parameters"]["properties"]
    relation_text = relation_params["relation_type"]["description"]
    for fragment in ("character → character", "character/organization → character/organization", "位于"):
        assert fragment in relation_text

    entity_params = convert_to_openai_tool(tools["write_entity"])["function"]["parameters"]["properties"]
    tags = entity_params["tags"]
    array_schema = tags["anyOf"][0]
    assert array_schema["maxItems"] == ENTITY_TAG_MAX_COUNT
    assert array_schema["items"]["maxLength"] == ENTITY_TAG_MAX_CHARS
    assert f"每个最多 {ENTITY_TAG_MAX_CHARS} 个字" in tags["description"]

    # 2026-09-14 tone 的取值域同样必须在模型可见面（预防），不是只在被拒回执里
    dialogue_params = convert_to_openai_tool(tools["write_dialogue"])["function"]["parameters"]["properties"]
    tone_any_of = dialogue_params["tone"]["anyOf"]
    tone_enum = next(branch["enum"] for branch in tone_any_of if "enum" in branch)
    assert len(tone_enum) >= 20 and "其他" in tone_enum
