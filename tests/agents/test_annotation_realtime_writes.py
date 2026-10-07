"""2026-09-13 实时写入改造 / 2026-09-14 写入面重构后的合同测试（小调用写入即生效、唯一 finish 收尾）

覆盖用户裁定的必要行为边界：同轮多调用只计一轮、失败不丢失已写入记录、
逐条失败不阻塞已齐全产物的收尾、重试按记录更新不重复、关系写入即入图、
对话必须实际判定、事件实时按调用顺序生长。

2026-09-14 合同变化点（相对 09-13 九工具面，见 docs/write-surface-2026-0914-test-contract.md）：
- 写入面为五个领域工具（write_entity/write_metrics/write_event/write_relation/write_dialogue）
  + 唯一 finish；事件根/子/参与者折叠进单工具 write_event：
  el 层级键挂树（根 "t1"、子 "t1/e2"），树内先后=调用顺序，没有 order 参数；
- 句标签收编进 write_metrics(labels=[{paragraph_id, emotion}])，绑定载荷键
  sentence_labels → paragraph_labels；
- 参与写从独立工具改为 write_event 的 characters 数组（给出即整节点替换）；
  (人物, 动作) 重复、三态必填/非 character 不接受三态等校验全部保留；
- 收尾声明 ledger.finish_chunk() → ledger.finish_chapter()，chunk_finished → chapter_finished；
  快照/回滚语义保留（snapshot 含 entity_el_index，失败只回滚该条调用）。

此处以账本层为主（tools + ledger 直调 apply_* / finish），
回合计数的图循环语义用本文件末尾的真实 LangGraph 用例覆盖；
末尾另有一条漂移守卫：模型可见文案点名的工具必须在当前工具面上真实存在。
"""

from __future__ import annotations

import json

import pytest

from src.agents.annotation.errors import AnnotationStageRejection
from src.fact_graph.schema import ChapterParagraphInfo
from src.agents.annotation.tool_batch import _invoke_tool
from src.agents.annotation.tools import AnnotationToolLedger
from src.fact_graph.graph import FactGraph
from tests.support.annotation_work_tools import build_annotation_tools
from tests.support.model_stream_adapter import StreamedFakeModelMixin


class _QueryService:
    """2026-09-13 用于提供无数据库依赖的查询桩"""


    async def search_text(self, query, *, range_name, limit=50):
        """2026-09-13 用于返回空正文命中"""
        del query, range_name, limit
        return []


def _chapter_text() -> str:
    """2026-09-13 用于提供含两个对话候选的单段章文本"""
    return "“住手！”顾霜喝道。“退下。”众人散去，夜色渐深。"


def _ledger(**overrides) -> AnnotationToolLedger:
    """2026-09-14 用于构造带事实图与段落坐标的账本（labels 段号校验依赖 paragraph_info）"""
    text = _chapter_text()
    kwargs = {
        "run_scope": "run-1",
        "current_chapter_id": 1,
        "current_chapter_text": text,
        "allow_future_context": False,
        "graph": FactGraph(),
        "paragraph_info": ChapterParagraphInfo(
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


async def _register_entities(tools: dict) -> dict[str, str]:
    """2026-09-19 用于登记测试用实体并返回 id 表（run 级 uuid/el 键供关系、对话、事件引用）"""
    ids = {}
    for name, entity_type in (("顾霜", "character"), ("众人", "organization"), ("山门", "location")):
        receipt = await _call(
            tools,
            "write_entity",
            {"name": name, "entity_type": entity_type, "el": name},
        )
        ids[name] = receipt["id"]
    return ids


async def _seed_metrics(tools: dict) -> None:
    """2026-09-13 用于提交最小指标载荷（收尾前置条件）"""
    await _call(
        tools,
        "write_metrics",
        {"summary": "顾霜喝止众人", "emotional_valence": 0, "narrative_function": "冲突"},
    )


async def _judge_dialogues(tools: dict) -> None:
    """事件及关系测试明确提交样本文本中两条真实对话的判定"""
    for candidate_index in (1, 2):
        await _call(tools, "write_dialogue", {"candidate_index": candidate_index, "verdict": "dialogue"})




# ---------------------------------------------------------------------------
# 事件：实时生长、三态与重复动态
# ---------------------------------------------------------------------------




@pytest.mark.asyncio
async def test_character_participation_defaults_partial_state_fields() -> None:
    """2026-10-04 合同放开：三态字段缺省/越界不再拒绝

    character 条目缺三态→不产动态状态行（同日补裁决：全空行会撞收尾重复语义，
    参与者仍落账）、role 缺省按登记大类取（character→主体）；
    只给部分三态→原样落账；emotion 越界→按边界钳制；
    非 character 带三态→observation_on_noncharacter（字段误用仍拒）。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    numbers = await _register_entities(tools)
    await _call(tools, "write_event", {"el": "t1", "isroot": True, "description": "顾霜喝止众人"})

    missing = await _call(
        tools,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [{"entityid": numbers["顾霜"]}],
        },
    )
    assert missing["status"] == "written"
    assert f"t1/root/participant/{numbers['顾霜']}" not in ledger.observation_by_record
    (participant,) = ledger.bound_payloads["events"][0].participants
    assert participant.role == "主体"

    partial = await _call(
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
    assert partial["status"] == "written"

    clamped = await _call(
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
    assert clamped["status"] == "written"
    assert ledger.observation_by_record[f"t1/root/participant/{numbers['顾霜']}"].emotion == 2

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
    """2026-09-14 同一章内 (人物, 动作) 重复：只拒绝后写的那一条，先写的照常保留

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
    子缺 type→missing；t1/root 占用保留键→reserved；
    根带路径→bad_el（2026-10-04 起未建树的子事件改为挂起，不再即时拒绝）。任一失败都不得动到同树已写入的根。
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
async def test_dialogue_replay_updates_verdict_in_place() -> None:
    """2026-09-13 同序号重交按更新语义（旧契约的"candidate_index 重复"报错已退役）"""
    ledger = _ledger()
    tools = _tools(ledger)
    await _register_entities(tools)
    await _call(
        tools, "write_dialogue", {"candidate_index": 1, "verdict": "dialogue", "speaker": "顾霜", "tone": "平静"}
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
async def test_dialogue_speaker_nullish_string_is_read_as_unattributed() -> None:
    """2026-09-14 null 字面串统一容错（run a8c29ec8 实锤：ch1 t6/ch4 t6/t7 白烧 3 个调用）

    模型把 JSON null 写成字符串 "null"，落到实体引用校验面报 unknown_entity_id，白烧一回合才自愈。
    转换收口在生产调用入口（graph._invoke_tool）：可空参数一律按留空读取，
    必填参数不改、仍严格拒绝。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    await _register_entities(tools)

    receipt = await _call(
        tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": "null", "tone": "平静"},
    )
    assert receipt["status"] == "written"
    assert ledger.written_dialogues[1].speaker is None
    assert receipt["content"]["speaker"] is None
    assert receipt["content"]["tone"] == "平静"

    # 大小写与可空枚举参数同受转换（tone 不再以 null 串撞 enum 校验）
    second = await _call(
        tools,
        "write_dialogue",
        {"candidate_index": 2, "verdict": "dialogue", "speaker": "None", "tone": "null"},
    )
    assert second["content"]["speaker"] is None
    assert second["content"]["tone"] is None

    strict = await _rejection(
        tools,
        "write_relation",
        {"from_entity": "null", "to_entity": "顾霜", "relation_type": "敌对"},
    )
    assert (strict.field, strict.code) == ("from_entity", "unknown_entity_id")


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
        {"candidate_index": 1, "verdict": "dialogue", "speaker": "顾霜", "tone": "平静"},
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
        "id": first["id"],
    }
    assert ledger.written_entities["顾霜"].tags == ["冷面"]

    cleared = await _call(tools, "write_entity", {
        "name": "顾霜", "entity_type": "character", "el": "a", "tags": [],
    })
    assert cleared["content"]["tags"] == []
    assert cleared["content"]["description"] == "护院教头"
    assert cleared["content"]["attributes"] == {"兵器": "刀", "佩饰": "玉"}


# ---------------------------------------------------------------------------
# 收尾：唯一 finish 的判定边界
# ---------------------------------------------------------------------------








@pytest.mark.asyncio
async def test_write_entity_no_longer_requires_search_graph_gate() -> None:
    """2026-09-14 删除"提交 write_entity 前必须先 search_graph"硬闸

    旧行为：图中已有登记实体时首笔登记必须先检索。闸门删净后省去 search_graph
    直接写入即生效，同轮多条登记照常各自独立。
    """
    ledger = _ledger(graph=FactGraph())
    tools = _tools(ledger)
    await _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    await _call(tools, "write_entity", {"name": "众人", "entity_type": "organization", "el": "众人"})
    assert set(ledger.written_entities) == {"顾霜", "众人"}


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


class _SingleReplyLLM(StreamedFakeModelMixin):
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




# ---------------------------------------------------------------------------
# 2026-09-13 根因修复：可见约束 / 登记即进池
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_program_registers_written_records_for_case_links() -> None:
    """2026-09-20 写者面程序里的成功写入同样登记记录键（案例工具的授权面）

    走 agent 路径的程序面（`ProgramRuntime._run_op` → `_execute_call`）而不是直接调工具
    函数：登记发生在事务边界上，模型跨程序引用"我刚写的 t1/root"要能命中
    （run 54a72932：写者面这条路没登记，promise_case 两次引用本章写出的事件树根全被拒）。
    """
    from tests.support.annotation_work_tools import build_program_test_runtime as ProgramRuntime

    ledger = _ledger()
    runtime = ProgramRuntime(list(_tools(ledger).values()), ledger)
    receipt = json.loads(
        await runtime.execute(
            'write_event(el="t1", isroot=True, description="顾霜喝止众人")\n'
            'write_entity(name="顾霜", entity_type="character", el="a1")'
        )
    )

    assert receipt["applied"] == 2
    assert ledger.written_record_keys == {"t1/root", "entity/顾霜"}


@pytest.mark.asyncio
async def test_unknown_entity_reference_lists_chapter_el_keys() -> None:
    """2026-09-20 引用写错时回执给出本章的"el=名字"对照，模型照抄即可自纠

    run 54a72932：135 次把实体名称当引用填；此前的回执只给 uuid 示例，名称到 uuid 要
    跨一层翻译，模型于是照原样重试。判据落在回执文本的数据面（键与登记名的对应）。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    await _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "a1"})

    rejected = await _rejection(
        tools,
        "write_relation",
        {"from_entity": "顾霜", "to_entity": "山门", "relation_type": "位于"},
    )

    assert "a1=顾霜" in rejected.expected


@pytest.mark.asyncio
async def test_relation_rejects_undeclared_evidence_argument() -> None:
    """2026-09-20 evidence 只收段首号：引文这类自由文本在参数校验处就被拒

    run 54a72932：160 次 write_relation 把引文填进 evidence（159 次在新增分支，
    那条分支本来不消费它），整笔写入按 schema 校验失败作废——字段口径统一为
    "段落开头的段首号（整数）"，说明与拒绝都按同一口径给。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    ids = await _register_entities(tools)

    rejected = await _rejection(
        tools,
        "write_relation",
        {
            "from_entity": ids["顾霜"],
            "to_entity": ids["众人"],
            "relation_type": "敌对",
            "evidence": "顾霜喝道",
        },
    )

    assert rejected.field == "evidence"


@pytest.mark.asyncio
async def test_entity_ledger_rows_carry_entity_type() -> None:
    """2026-09-20 账本实体行带大类：实体大类一经登记不可变更，重写只能照它来

    注入块按该行渲染（el=name(大类；id=…)），模型凭记忆重写时写错大类会被拒
    （run 54a72932：10 次 entity_type 类拒绝）。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    await _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "a1"})

    assert [row["entity_type"] for row in ledger.entity_ledger()] == ["character"]
