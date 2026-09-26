"""章内三代理并发：单个 subagent 的构造器与程序面合同测试

覆盖 subagent_program 的模型可见面与 2026-09-18"写入生效"口径：

- 三个 subagent 的模型可见面逐字相同（绑定面只有 execute_code + finish），程序目录 =
  四个检索 + 五个案例 + finish + 八类构造器，五个 write_* 既不在可见面也不在命名空间；
- 八类构造器写入生效：构造器是纯校验器，运行时把那一笔经生产单条事务边界
  （graph._execute_call）当场落库，**写入成功才**回 `{status:"written", record, ref}`
  并把记录放进 subagent；共享章级账本（written_entities / entity_el_index /
  tree_key_index / written_relations / written_dialogues / metrics_payload /
  pushed_cases）当场可见；
- el 按角色命名空间化（实体 structure:a1、事件 structure:t1 与 structure:t1/e2），
  三个 subagent 的同名局部键不互相占用；同名实体由生产写入自己按名会合；
- 失败（构造器校验或生产面拒绝）一律结构化回执 record/field/code/expected，且
  subagent 的列表与共享账本都不变；
- 同键重写=更新语义（实体=本 subagent id、事件=el、对话=候选号、标签=段号）；
- subagent 的 finish 是面上一等工具（不是构造器），subagent_gap 的口径与之一致；
- 构造器目录与实际命名空间同源：目录里的每个名字都直接调得动，签名与参数说明同轮下发。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.schema import ChapterParagraphInfo, SearchResult
from src.agents.annotation.subagent_ir import SubagentAnnotation
from src.agents.annotation.subagent_program import (
    SubagentProgramRuntime,
    build_subagent_finish_tool,
    subagent_gap,
    subagent_gap_is_clean,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools

# 三段正文：¶1/¶2/¶3 各有一个引号对话候选，整章共 3 条候选（对话判定候选号 1..3）；
# "长刀" 在 ¶2，作为 item 实体与参与者测试的锚点
PARAGRAPHS: dict[int, str] = {
    1: "“站住！”沈遥喝道。",
    2: "“退下。”她收起长刀，转身走进雨里。",
    3: "“我走了。”沈遥回头。",
}
CHAPTER_TEXT = "".join(PARAGRAPHS.values())

# 2026-09-18 evidence 只按段号 id 锚定：单个段首可见号整数，不再带逐字引文
E_PERSON = 1
E_KNIFE = 2
E_SHOUT = 1
E_TALK = 1

_CHARACTER_ITEM = {"entity_id": "a1", "role": "主体", "narrative_role": "主体", "action": "喝止", "emotion": -1}

# 八类构造器全部走一遍：每条都能当场落库（a3 是 organization，"敌对" 允许 character→organization）
_WRITE_EVERYTHING = """
entity(id="a1", name="沈遥", entity_type="character", evidence=1)
entity(id="a2", name="长刀", entity_type="item", evidence=2)
entity(id="a3", name="剑宗", entity_type="organization", evidence=3)
relation(from_id="a1", to_id="a3", relation_type="敌对", evidence=2)
event(el="t1", isroot=True, description="沈遥喝止", evidence=1)
event(el="t1/e2", isroot=False, description="转身", type="main", evidence=2)
participants(el="t1", items=[{"entity_id": "a1", "role": "主体", "narrative_role": "主体",
"action": "喝止", "emotion": -1}])
dialogue(candidate_index=1, verdict="dialogue", speaker_id="a1", tone="愤怒", evidence=1)
label(paragraph_id=1, emotion=-1)
metric(summary="冲突", emotional_valence=-1, narrative_function="冲突")
pending(kind="case_clue", detail="长刀来路不明", evidence=2, keys=["a2"], case_id="case-abc")
"""


class _QueryService:
    """用于提供无数据库依赖的查询桩"""

    current_chapter_order = None

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """用于返回空案例检索结果"""
        del query, hidden_case_ids, case_type, limit, pending_cases
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        """用于返回空正文命中"""
        del query, range_name, limit
        return []

    def search_event_history(self, query, *, limit=50):
        """用于返回空历史事件树"""
        del query, limit
        return []


def _paragraph_info() -> ChapterParagraphInfo:
    """用于构造三段正文的整章段落坐标映射"""
    ids = sorted(PARAGRAPHS)
    offsets = 0
    spans: list[tuple[int, int]] = []
    texts: list[str] = []
    for paragraph_id in ids:
        text = PARAGRAPHS[paragraph_id]
        spans.append((offsets, offsets + len(text)))
        texts.append(text)
        offsets += len(text)
    return ChapterParagraphInfo(paragraph_ids=ids, char_spans=spans, texts=texts)


def _ledger(*, known_case_ids: set[str] | None = None) -> AnnotationToolLedger:
    """用于构造一个 subagent 的共享章级账本（整章正文、三段坐标、可选案例 id 授权）"""
    ledger = AnnotationToolLedger(
        run_scope="run-subagent-test",
        current_chapter_id=1,
        current_chapter_text=CHAPTER_TEXT,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=_paragraph_info(),
    )
    if known_case_ids:
        ledger.known_case_ids.update(known_case_ids)
    return ledger


def _tools(ledger: AnnotationToolLedger) -> dict[str, Any]:
    """用于按生产装配方式取工具名 → 工具表的映射（构造器要经它落库）"""
    return {str(tool.name): tool for tool in build_annotation_tools(_QueryService(), ledger)}


def _runtime(
    ledger: AnnotationToolLedger,
    subagent: SubagentAnnotation | None = None,
    *,
    tool_map: dict[str, Any] | None = None,
    **kwargs: Any,
) -> SubagentProgramRuntime:
    """用于按生产装配方式建一个 subagent 的程序面（共享账本 + 生产工具表）"""
    if subagent is None:
        subagent = SubagentAnnotation(role="structure")
    if tool_map is None:
        tool_map = _tools(ledger)
    return SubagentProgramRuntime(tool_map, ledger, subagent, **kwargs)


async def _run(runtime: SubagentProgramRuntime, code: str) -> dict[str, Any]:
    """用于走模型真实路径执行一段程序并解析压缩回执"""
    return json.loads(await runtime.execute(code))


def _failed_entry(receipt: dict[str, Any]) -> dict[str, Any]:
    """用于取压缩回执里唯一那条失败记录（并断言确实只有一条）"""
    failed = receipt.get("failed")
    assert isinstance(failed, list) and len(failed) == 1, receipt
    return failed[0]


async def _runtime_rejection(runtime: SubagentProgramRuntime, code: str) -> dict[str, Any]:
    """用于执行一段程序并断言唯一失败记录带齐模型可见的四个定位字段"""
    entry = _failed_entry(await _run(runtime, code))
    for key in ("record", "field", "code", "expected"):
        assert entry.get(key), entry
    return entry


def _finish_tool(subagent: SubagentAnnotation, *, candidate_total: int = 3):
    """用于按生产路径构造 subagent 的收尾工具（面上一等工具，不是构造器）"""
    return build_subagent_finish_tool(subagent, candidate_total=candidate_total)


# ----------------------------------------------------------------------
# 二、八类构造器：成功路径（写入生效，subagent 与共享账本同一条事实）


@pytest.mark.asyncio
async def test_eight_constructors_write_records_into_the_subagent_and_shared_ledger() -> None:
    """八类构造器逐一成功：记录当场进 subagent 与共享章级账本，回执/进度逐域可见"""
    ledger = _ledger(known_case_ids={"case-abc"})
    subagent = SubagentAnnotation(role="structure")
    runtime = _runtime(ledger, subagent)

    receipt = await _run(runtime, _WRITE_EVERYTHING)

    # 八类构造器共 11 条（实体 3 + 关系 1 + 事件 2 + 参与者 1 + 对话 1 + 标签 1 + 指标 1 + 待决 1）
    assert receipt["status"] == "applied"
    assert receipt["applied"] == 11
    assert "failed" not in receipt
    assert receipt["progress"] == subagent.counts() == {
        "entities": 3,
        "relations": 1,
        "events": 2,
        "dialogues": 1,
        "labels": 1,
        "metrics": 1,
        "pending": 1,
    }

    # 逐 op 记录：构造器名 + 角色命名空间化的记录键，全部成功
    records = [op["record"] for op in runtime.ops]
    assert all(op["status"] == "success" for op in runtime.ops)
    assert records[0] == "structure/entity/a1"
    assert "structure/relation/a1-a3" in records
    assert "structure/event/t1" in records
    assert "structure/event/t1/e2" in records
    assert "structure/participants/t1" in records
    assert "structure/dialogue/1" in records
    assert "structure/label/1" in records
    assert "structure/metric" in records
    assert "structure/pending/case_clue" in records

    # subagent 的产出记录
    assert [item.id for item in subagent.entities] == ["a1", "a2", "a3"]
    assert [item.name for item in subagent.entities] == ["沈遥", "长刀", "剑宗"]
    assert len(subagent.relations) == 1
    assert len(subagent.events) == 2
    assert [event.evidence_paragraph_id for event in ledger.bound_payloads["events"]] == [1, 2]
    assert subagent.event_keys()["t1"].participants[0].entity_id == "a1"
    assert subagent.dialogues[0].speaker_id == "a1"
    assert [item.paragraph_id for item in subagent.labels] == [1]
    assert subagent.metric is not None and subagent.metric.summary == "冲突"
    assert subagent.pending[0].keys == ["a2"]
    assert subagent.pending[0].case_id == "case-abc"

    # 共享章级账本：实体 el 索引、事件树键索引、关系、对话、指标都当场可见
    assert set(ledger.written_entities) == {"沈遥", "长刀", "剑宗"}
    assert ledger.entity_el_index["structure:a1"] == "沈遥"
    assert ledger.entity_el_index["structure:a2"] == "长刀"
    assert "structure:t1" in ledger.tree_key_index
    tree = ledger.event_trees[ledger.tree_key_index["structure:t1"]]
    assert set(tree["nodes"]) == {"root", "e2"}
    assert ledger.written_relations[("沈遥", "剑宗")].relation_type == "敌对"
    assert ledger.written_dialogues[1].speaker == "沈遥"
    assert ledger.written_dialogues[1].tone == "愤怒"
    assert ledger.metrics_payload is not None
    assert ledger.metrics_payload.summary == "冲突"
    # 标签与指标在生产面同属 write_metrics 一个域：metric 构造器不带 labels，标签留待章收尾链
    assert ledger.metrics_payload.labels == []
    assert set(ledger.observation_by_record) != set()

    # 构造器直接调用只产出计划对象（纯校验），不改任何已落账状态
    entity_plan = runtime.tools["entity"](id="a1", name="沈遥", entity_type="character", evidence=E_PERSON)
    assert entity_plan.record == "structure/entity/a1"
    assert entity_plan.ref == {"kind": "entity", "id": "a1", "name": "沈遥", "entity_type": "character"}
    relation_plan = runtime.tools["relation"](from_id="a1", to_id="a3", relation_type="敌对", evidence=E_KNIFE)
    assert relation_plan.ref == {
        "kind": "relation",
        "type": "敌对",
        "from_id": "a1",
        "to_id": "a3",
        "change_kind": None,
    }
    assert relation_plan.args == {
        "from_entity": "structure:a1",
        "to_entity": "structure:a3",
        "relation_type": "敌对",
    }
    root_plan = runtime.tools["event"](el="t1", isroot=True, description="沈遥喝止", evidence=E_SHOUT)
    assert root_plan.ref == {"kind": "event", "el": "t1", "isroot": True, "participants": 1}
    assert root_plan.args["evidence"] == E_SHOUT
    child_plan = runtime.tools["event"](el="t1/e2", isroot=False, description="转身", type="main", evidence=E_KNIFE)
    assert child_plan.ref == {"kind": "event", "el": "t1/e2", "isroot": False, "participants": 0}
    assert child_plan.args["evidence"] == E_KNIFE
    participants_plan = runtime.tools["participants"](el="t1", items=[_CHARACTER_ITEM])
    assert participants_plan.ref == {"kind": "participants", "el": "t1", "count": 1}
    dialogue_plan = runtime.tools["dialogue"](
        candidate_index=1, verdict="dialogue", speaker_id="a1", tone="愤怒", evidence=E_TALK
    )
    assert dialogue_plan.ref == {"kind": "dialogue", "candidate_index": 1, "verdict": "dialogue"}
    label_plan = runtime.tools["label"](paragraph_id=1, emotion=-1)
    assert label_plan.ref == {"kind": "label", "paragraph_id": 1, "emotion": -1}
    metric_plan = runtime.tools["metric"](summary="冲突", emotional_valence=-1, narrative_function="冲突")
    assert metric_plan.ref == {"kind": "metric", "summary": "冲突"}
    pending_plan = runtime.tools["pending"](
        kind="case_clue", detail="长刀来路不明", evidence=E_KNIFE, keys=["a2"], case_id="case-abc"
    )
    assert pending_plan.ref == {"kind": "pending", "pending_kind": "case_clue", "case_id": "case-abc"}
    # 直接调用没有落账：计数与计划调用前一致
    assert subagent.counts() == receipt["progress"]


@pytest.mark.asyncio
async def test_constructor_call_receipt_is_written_with_record_and_ref() -> None:
    """单条构造器调用成功时的回执 = {status:"written", record, ref}（写入成功才回）"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="structure")
    runtime = _runtime(ledger, subagent)
    receipt = await runtime._dispatch(
        "entity",
        {"id": "a1", "name": "沈遥", "entity_type": "character", "evidence": E_PERSON},
        line=None,
    )
    assert receipt["status"] == "written"
    assert receipt["record"] == "structure/entity/a1"
    assert receipt["ref"] == {"kind": "entity", "id": "a1", "name": "沈遥", "entity_type": "character"}
    assert [item.id for item in subagent.entities] == ["a1"]
    assert ledger.entity_el_index["structure:a1"] == "沈遥"


@pytest.mark.asyncio
async def test_every_call_returns_one_of_the_three_receipt_shapes() -> None:
    """构造器与工具走同一条分发：回执只有写成/读到/被拒三种形状

    2026-09-18 之前构造器走 _run_constructor、检索与案例工具走 _run_tool，两边的成功回执
    各写一遍（构造器自己拼 {status, record, ref}、工具直接漏生产层的 {"accepted": ...}）、
    失败回执也各一套。现在一个 _dispatch 管所有名字：写类一律 {status:"written", record,
    ref}，检索类原样给数据，被拒一律 {status:"rejected", record, ...}。
    """
    ledger = _ledger()
    subagent = SubagentAnnotation(role="structure")
    runtime = _runtime(ledger, subagent)

    written = await runtime._dispatch(
        "entity", {"id": "a1", "name": "沈遥", "entity_type": "character", "evidence": E_PERSON}, line=None
    )
    assert written["status"] == "written"
    assert set(written) == {"status", "record", "ref"}

    read = await runtime._dispatch("search_text", {"query": "沈遥"}, line=None)
    assert isinstance(read, list)

    structured = await runtime._dispatch("relation", {"from_id": "a1", "to_id": "a9"}, line=None)
    assert structured["status"] == "rejected"
    assert structured["code"] == "invalid_call"
    # 校验没过就没有记录键可算（record 只能给调用名），自纠靠 expected 里的真实签名
    assert structured["record"] == "relation"
    assert structured["expected"].startswith("relation(")


# ----------------------------------------------------------------------
# 三、八类构造器：拒绝路径（结构化拒绝且 subagent 与共享账本都不变）


@pytest.mark.asyncio
async def test_entity_rejects_out_of_range_type_without_writing() -> None:
    """entity_type 越界：invalid_value/entity_type，subagent 与共享账本里都不留记录"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="structure")
    runtime = _runtime(ledger, subagent)
    entry = await _runtime_rejection(
        runtime, 'entity(id="a1", name="沈遥", entity_type="divinity", evidence=1)'
    )
    assert entry["code"] == "invalid_value"
    assert entry["field"] == "entity_type"
    assert subagent.entities == []
    assert ledger.written_entities == {} and ledger.entity_el_index == {}


@pytest.mark.asyncio
async def test_entity_rejects_evidence_that_is_not_a_single_in_chapter_id() -> None:
    """evidence 只收单个段号：多号数组与越界号都结构化拒绝，subagent 里不留记录"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="structure")
    runtime = _runtime(ledger, subagent)
    multiple = await _runtime_rejection(
        runtime,
        'entity(id="a1", name="沈遥", entity_type="character", evidence=[{"paragraph_id": 1}, {"paragraph_id": 2}])',
    )
    assert multiple["code"] == "multiple_evidence_ids"
    assert multiple["field"] == "evidence"
    assert "1..3" in multiple["expected"]
    out_of_range = await _runtime_rejection(
        runtime, 'entity(id="a1", name="沈遥", entity_type="character", evidence=99)'
    )
    assert out_of_range["code"] == "out_of_range"
    assert out_of_range["field"] == "evidence"
    assert "1..3" in out_of_range["expected"]
    assert subagent.entities == []
    assert ledger.written_entities == {} and ledger.entity_el_index == {}


@pytest.mark.asyncio
async def test_relation_rejects_out_of_range_type_without_writing() -> None:
    """relation_type 越界：invalid_value/relation_type，subagent 与共享账本里都不留记录"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="structure")
    runtime = _runtime(ledger, subagent)
    await _run(
        runtime,
        'entity(id="a1", name="沈遥", entity_type="character", evidence=1)\n'
        'entity(id="a2", name="长刀", entity_type="item", evidence=2)',
    )
    entry = await _runtime_rejection(
        runtime, 'relation(from_id="a1", to_id="a2", relation_type="父女", evidence=2)'
    )
    assert entry["code"] == "invalid_value"
    assert entry["field"] == "relation_type"
    assert subagent.relations == []
    assert ledger.written_relations == {}


@pytest.mark.parametrize(
    ("kwargs", "expected_field", "expected_code"),
    [
        ({"el": "t1/e2", "isroot": True, "description": "x", "evidence": E_SHOUT}, "el", "bad_el"),
        ({"el": "t2", "isroot": False, "description": "x", "evidence": E_SHOUT, "type": "main"}, "el", "bad_el"),
        ({"el": "t1/e2", "isroot": False, "description": "x", "evidence": E_SHOUT}, "type", "missing_field"),
        ({"el": "t1", "isroot": True, "description": "x", "evidence": E_SHOUT, "type": "main"}, "type", "not_on_root"),
        (
            {"el": "t1", "isroot": True, "description": "x", "evidence": E_SHOUT, "isforeshadowing": True},
            "confidence",
            "missing_field",
        ),
        (
            {
                "el": "t1/e2",
                "isroot": False,
                "description": "x",
                "evidence": E_SHOUT,
                "type": "main",
                "isforeshadowing": True,
            },
            "isforeshadowing",
            "not_on_child",
        ),
    ],
    ids=[
        "root-with-slash",
        "child-without-slash",
        "child-missing-type",
        "root-with-type",
        "foreshadow-no-confidence",
        "child-with-foreshadow",
    ],
)
@pytest.mark.asyncio
async def test_event_el_forms_are_rejected(kwargs: dict, expected_field: str, expected_code: str) -> None:
    """el 形态非法（含根带 type、子缺 type、伏笔属性错位）一律结构化拒绝且不建树"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="event")
    runtime = _runtime(ledger, subagent)
    args_text = ", ".join(f"{key}={value!r}" for key, value in kwargs.items())
    entry = await _runtime_rejection(runtime, f"event({args_text})")
    assert entry["field"] == expected_field
    assert entry["code"] == expected_code
    assert subagent.events == []
    assert ledger.tree_key_index == {} and ledger.event_trees == {}


@pytest.mark.asyncio
async def test_event_rejects_foreshadowing_property_on_child() -> None:
    """伏笔属性只属于根：子事件带 isforeshadowing 被拒且不写入"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="event")
    runtime = _runtime(ledger, subagent)
    entry = await _runtime_rejection(
        runtime,
        'event(el="t1/e2", isroot=False, description="转身", type="main", '
        'isforeshadowing=True, confidence="high", evidence=2)',
    )
    assert entry["code"] == "not_on_child"
    assert entry["field"] == "isforeshadowing"
    assert subagent.events == []
    assert ledger.tree_key_index == {}


@pytest.mark.asyncio
async def test_participants_rejects_unknown_event_and_partial_three_state() -> None:
    """participants 引用不存在的事件 el、三态只给一半都拒绝，事件上头不留参与者"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="event")
    runtime = _runtime(ledger, subagent)
    unknown = await _runtime_rejection(
        runtime, 'participants(el="t9", items=[{"entity_id": "a1", "role": "主体"}])'
    )
    assert unknown["code"] == "unknown_reference"
    assert unknown["field"] == "el"
    await _run(
        runtime,
        'event(el="t1", isroot=True, description="喝止", evidence=1)\n'
        'entity(id="a1", name="沈遥", entity_type="character", evidence=1)',
    )
    partial = await _runtime_rejection(
        runtime,
        'participants(el="t1", items=[{"entity_id": "a1", "role": "主体", "narrative_role": "主体"}])',
    )
    assert partial["code"] == "missing_field"
    assert partial["field"] == "participants[0].narrative_role"
    unregistered = await _runtime_rejection(
        runtime, 'participants(el="t1", items=[{"entity_id": "a9", "role": "主体"}])'
    )
    assert unregistered["code"] == "unknown_reference"
    assert unregistered["field"] == "participants[0].entity_id"
    assert subagent.event_keys()["t1"].participants == []
    assert ledger.observation_by_record == {}


@pytest.mark.asyncio
async def test_dialogue_rejections_do_not_write() -> None:
    """候选号越界、not_dialogue 带说话人、非 not_dialogue 缺引文、说话人键含斜杠都拒绝"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="evidence")
    runtime = _runtime(ledger, subagent)
    out_of_range = await _runtime_rejection(
        runtime, 'dialogue(candidate_index=9, verdict="dialogue", evidence=1)'
    )
    assert out_of_range["code"] == "out_of_range"
    assert out_of_range["field"] == "candidate_index"
    not_dialogue = await _runtime_rejection(
        runtime, 'dialogue(candidate_index=1, verdict="not_dialogue", speaker_id="a1")'
    )
    assert not_dialogue["code"] == "invalid_value"
    assert not_dialogue["field"] == "verdict"
    missing_evidence = await _runtime_rejection(runtime, 'dialogue(candidate_index=1, verdict="dialogue")')
    assert missing_evidence["code"] == "missing_evidence"
    assert missing_evidence["field"] == "evidence"
    bad_speaker = await _runtime_rejection(
        runtime, 'dialogue(candidate_index=1, verdict="dialogue", speaker_id="a/1", evidence=1)'
    )
    assert bad_speaker["code"] == "invalid_value"
    assert bad_speaker["field"] == "speaker_id"
    assert subagent.dialogues == []
    assert ledger.written_dialogues == {}


@pytest.mark.asyncio
async def test_label_rejections_do_not_write() -> None:
    """段号不属于本章、emotion 越界（如 3）都拒绝，subagent 里不留标签"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="evidence")
    runtime = _runtime(ledger, subagent)
    foreign = await _runtime_rejection(runtime, 'label(paragraph_id=99, emotion=0)')
    assert foreign["code"] == "out_of_range"
    assert foreign["field"] == "paragraph_id"
    out_of_range = await _runtime_rejection(runtime, 'label(paragraph_id=1, emotion=3)')
    assert out_of_range["code"] == "invalid_value"
    assert out_of_range["field"] == "emotion"
    assert subagent.labels == []
    assert ledger.metrics_payload is None


@pytest.mark.asyncio
async def test_metric_rejects_out_of_range_narrative_function() -> None:
    """narrative_function 越界：invalid_value/narrative_function，subagent 里不留指标"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="evidence")
    runtime = _runtime(ledger, subagent)
    entry = await _runtime_rejection(
        runtime, 'metric(summary="x", emotional_valence=0, narrative_function="高潮")'
    )
    assert entry["code"] == "invalid_value"
    assert entry["field"] == "narrative_function"
    assert subagent.metric is None
    assert ledger.metrics_payload is None


@pytest.mark.asyncio
async def test_pending_rejects_case_clue_without_evidence_and_unauthorized_case_id() -> None:
    """case_clue 缺引文、case_id 未由 search_pool 授权都拒绝，subagent 里不留待决项

    2026-09-19 案例 id 纪律：pending 的 case_id 必须是 search_pool 回执里的案例 id
    字符串（运行期编号已删），未授权拒绝 code=unauthorized_case、field=case_id。
    """
    ledger = _ledger()
    subagent = SubagentAnnotation(role="evidence")
    runtime = _runtime(ledger, subagent)
    missing_evidence = await _runtime_rejection(runtime, 'pending(kind="case_clue", detail="长刀来路不明")')
    assert missing_evidence["code"] == "missing_evidence"
    assert missing_evidence["field"] == "evidence"
    unauthorized = await _runtime_rejection(
        runtime, 'pending(kind="case_clue", detail="长刀来路不明", evidence=2, case_id="case-abc")'
    )
    assert unauthorized["code"] == "unauthorized_case"
    assert unauthorized["field"] == "case_id"
    assert "search_pool" in unauthorized["expected"]
    assert subagent.pending == []
    assert ledger.pushed_cases == []


# ----------------------------------------------------------------------
# 四、生产面拒绝：写入被生产单条事务边界拒下，subagent 与共享账本都不变


@pytest.mark.asyncio
async def test_event_orphan_is_rejected_by_production_without_trace() -> None:
    """子事件先于树根构造：write_event 被生产面以 unknown_tree 拒绝，不建树不留记录

    2026-09-18 删除 _tree_ordered 后孤儿不再靠落库相位重排：那笔写入当场被拒，
    构造器返回的拒绝回执就是模型可见的失败。
    """
    ledger = _ledger()
    subagent = SubagentAnnotation(role="event")
    runtime = _runtime(ledger, subagent)
    entry = await _runtime_rejection(
        runtime, 'event(el="t1/e2", isroot=False, description="转身", type="main", evidence=2)'
    )
    assert entry["code"] == "unknown_tree"
    assert entry["field"] == "el"
    assert entry["record"] == "event:t1/e2"  # 落库记录键 = 角色命名空间化的 el
    assert subagent.events == []
    assert ledger.tree_key_index == {} and ledger.event_trees == {}


@pytest.mark.asyncio
async def test_entity_duplicate_el_is_rejected_by_production_without_trace() -> None:
    """同一 el 已绑定另一实体：第二笔写入被生产面以 duplicate_el 拒绝，只保留第一笔"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="structure")
    runtime = _runtime(ledger, subagent)
    entry = await _runtime_rejection(
        runtime,
        'entity(id="a1", name="沈遥", entity_type="character", evidence=1)\n'
        'entity(id="a1", name="长刀", entity_type="item", evidence=2)',
    )
    assert entry["code"] == "duplicate_el"
    assert entry["field"] == "el"
    assert [item.name for item in subagent.entities] == ["沈遥"]
    assert set(ledger.written_entities) == {"沈遥"}
    assert ledger.entity_el_index == {"structure:a1": "沈遥"}


@pytest.mark.asyncio
async def test_dialogue_non_character_speaker_is_rejected_by_production() -> None:
    """说话人非 character：构造器放行、生产面以 not_character 拒绝，对话账本不动"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="evidence")
    runtime = _runtime(ledger, subagent)
    entry = await _runtime_rejection(
        runtime,
        'entity(id="a2", name="长刀", entity_type="item", evidence=2)\n'
        'dialogue(candidate_index=1, verdict="dialogue", speaker_id="a2", evidence=1)',
    )
    assert entry["code"] == "not_character"
    assert entry["field"] == "speaker"
    assert subagent.dialogues == []
    assert ledger.written_dialogues == {}


@pytest.mark.asyncio
async def test_participants_observation_on_non_character_is_rejected_by_production() -> None:
    """非 character 参与者带三态：生产面以 observation_on_noncharacter 拒绝，参与者列表不动"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="event")
    runtime = _runtime(ledger, subagent)
    entry = await _runtime_rejection(
        runtime,
        'entity(id="a2", name="长刀", entity_type="item", evidence=2)\n'
        'event(el="t1", isroot=True, description="喝止", evidence=1)\n'
        "participants(el=\"t1\", items=[{\"entity_id\": \"a2\", \"role\": \"客体\", "
        '"narrative_role": "客体", "action": "被喝", "emotion": -1}])',
    )
    assert entry["code"] == "observation_on_noncharacter"
    assert entry["field"] == "narrative_role"
    assert subagent.event_keys()["t1"].participants == []
    assert ledger.observation_by_record == {}


# ----------------------------------------------------------------------
# 五、同 id 不互相占用：三个 subagent 各用局部键，落库按角色命名空间化


@pytest.mark.asyncio
async def test_same_local_id_across_subagents_does_not_collide() -> None:
    """structure 与 event 各自的 a1 是两条实体：落库 el 不同名，互不占用"""
    ledger = _ledger()
    structure = SubagentAnnotation(role="structure")
    event = SubagentAnnotation(role="event")
    structure_runtime = _runtime(ledger, structure)
    event_runtime = _runtime(ledger, event)
    await _run(structure_runtime, 'entity(id="a1", name="沈遥", entity_type="character", evidence=1)')
    await _run(event_runtime, 'entity(id="a1", name="长刀", entity_type="item", evidence=2)')
    assert set(ledger.written_entities) == {"沈遥", "长刀"}
    assert ledger.entity_el_index == {"structure:a1": "沈遥", "event:a1": "长刀"}


@pytest.mark.asyncio
async def test_same_name_across_subagents_merges_into_one_entity() -> None:
    """structure 与 event 各自的 a1 同名：生产面按名会合，账本里只有一条实体"""
    ledger = _ledger()
    structure = SubagentAnnotation(role="structure")
    event = SubagentAnnotation(role="event")
    structure_runtime = _runtime(ledger, structure)
    event_runtime = _runtime(ledger, event)
    await _run(structure_runtime, 'entity(id="a1", name="沈遥", entity_type="character", evidence=1)')
    await _run(event_runtime, 'entity(id="a1", name="沈遥", entity_type="character", evidence=1)')
    assert set(ledger.written_entities) == {"沈遥"}
    assert ledger.entity_el_index == {"structure:a1": "沈遥", "event:a1": "沈遥"}


# ----------------------------------------------------------------------
# 六、pending 进案例池：keys 是登记名（不是局部 id）


@pytest.mark.asyncio
async def test_pending_pool_keys_are_registered_names() -> None:
    """pending 的案例池 keys 取本 subagent 的登记名，且这条当场进共享账本的案例池"""
    ledger = _ledger(known_case_ids={"case-abc"})
    subagent = SubagentAnnotation(role="evidence")
    runtime = _runtime(ledger, subagent)
    receipt = await _run(
        runtime,
        'entity(id="a2", name="长刀", entity_type="item", evidence=2)\n'
        'pending(kind="case_clue", detail="长刀来路不明", evidence=2, keys=["a2"], case_id="case-abc")',
    )
    assert receipt["status"] == "applied"
    # subagent 里记的是局部引用键；案例池里记的是登记名
    assert subagent.pending[0].keys == ["a2"]
    assert ledger.pushed_cases[0].keys == ["长刀"]
    assert ledger.pushed_cases[0].type == "伏笔疑点"

    # 没有 keys 时案例池登记名退化为 kind，type 取 PENDING_CASE_TYPES 映射
    await _run(runtime, 'pending(kind="other", detail="存疑")')
    assert ledger.pushed_cases[1].keys == ["other"]
    assert ledger.pushed_cases[1].type == "其他疑点"


# ----------------------------------------------------------------------
# 七、标签只在 journal、指标当场落 write_metrics 域


@pytest.mark.asyncio
async def test_label_only_lands_in_journal_and_metric_hits_ledger() -> None:
    """label 只落 subagent 的 journal（不单独落库）；metric 当场写 write_metrics（不带 labels）"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="evidence")
    runtime = _runtime(ledger, subagent)
    await _run(runtime, 'label(paragraph_id=1, emotion=-1)\nlabel(paragraph_id=2, emotion=2)')
    assert [item.paragraph_id for item in subagent.labels] == [1, 2]
    # 标签与指标同属 write_metrics 一个域：没有指标时标签也不单独落库
    assert ledger.metrics_payload is None
    await _run(runtime, 'metric(summary="冲突", emotional_valence=0, narrative_function="冲突")')
    assert ledger.metrics_payload is not None
    assert ledger.metrics_payload.labels == []
    assert subagent.metric is not None and subagent.metric.summary == "冲突"


# ----------------------------------------------------------------------
# 八、同键重写=更新语义


@pytest.mark.asyncio
async def test_entity_same_id_rewrite_is_update_not_new_entry() -> None:
    """实体同 id 重写只留一条，字段按最后一次为准（name 只是展示字段）"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="structure")
    runtime = _runtime(ledger, subagent)
    await _run(
        runtime,
        'entity(id="a1", name="沈遥", entity_type="character", evidence=1)\n'
        'entity(id="a1", name="沈遥", entity_type="character", evidence=1, description="持刀剑客")',
    )
    assert len(subagent.entities) == 1
    assert subagent.entities[0].id == "a1"
    assert subagent.entities[0].description == "持刀剑客"
    assert set(ledger.written_entities) == {"沈遥"}
    assert ledger.written_entities["沈遥"].description == "持刀剑客"


@pytest.mark.asyncio
async def test_event_same_el_rewrite_keeps_participants() -> None:
    """事件同 el 重写保留已挂的参与者（只更新描述与伏笔属性）"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="event")
    runtime = _runtime(ledger, subagent)
    await _run(
        runtime,
        'event(el="t1", isroot=True, description="喝止", evidence=1)\n'
        'entity(id="a1", name="沈遥", entity_type="character", evidence=1)\n'
        'participants(el="t1", items=[{"entity_id": "a1", "role": "主体", '
        '"narrative_role": "主体", "action": "喝止", "emotion": -1}])\n'
        'event(el="t1", isroot=True, description="改述", evidence=1)',
    )
    assert len(subagent.events) == 1
    assert subagent.events[0].description == "改述"
    assert len(subagent.events[0].participants) == 1
    tree = ledger.event_trees[ledger.tree_key_index["event:t1"]]
    assert set(tree["nodes"]) == {"root"}  # 重写没新建节点
    assert len(ledger.observation_by_record) == 1  # 生产面的参与者动态状态原样保留


@pytest.mark.asyncio
async def test_dialogue_same_candidate_rewrite_is_update() -> None:
    """对话同候选号重写只留一条，判定按最后一次为准"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="evidence")
    runtime = _runtime(ledger, subagent)
    await _run(
        runtime,
        'entity(id="a1", name="沈遥", entity_type="character", evidence=1)\n'
        'dialogue(candidate_index=1, verdict="not_dialogue")\n'
        'dialogue(candidate_index=1, verdict="dialogue", speaker_id="a1", evidence=1)',
    )
    assert len(subagent.dialogues) == 1
    assert subagent.dialogues[0].verdict == "dialogue"
    assert subagent.dialogues[0].speaker_id == "a1"
    assert ledger.written_dialogues[1].speaker == "沈遥"


@pytest.mark.asyncio
async def test_label_same_paragraph_rewrite_is_update() -> None:
    """标签同段号重写只留一条，分值按最后一次为准"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="evidence")
    runtime = _runtime(ledger, subagent)
    await _run(runtime, 'label(paragraph_id=1, emotion=-1)\nlabel(paragraph_id=1, emotion=2)')
    assert len(subagent.labels) == 1
    assert subagent.labels[0].emotion == 2


# ----------------------------------------------------------------------
# 九、finish 工具与 subagent_gap


@pytest.mark.asyncio
async def test_finish_tool_marks_subagent_finished_and_reports_counts_and_gap() -> None:
    """finish 置 finished=True，回执给出各域计数与未判候选号"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="evidence")
    runtime = _runtime(ledger, subagent)
    await _run(
        runtime,
        'dialogue(candidate_index=1, verdict="not_dialogue")\n'
        'dialogue(candidate_index=2, verdict="dialogue", evidence=1)',
    )
    receipt = json.loads(_finish_tool(subagent).invoke({}))
    assert subagent.finished is True
    assert receipt["status"] == "written"
    reference = receipt["ref"]
    assert reference["role"] == "evidence"
    assert reference["finished"] is True
    assert reference["candidate_total"] == 3
    assert reference["unjudged_candidates"] == [3]
    assert reference["counts"]["dialogues"] == 2
    assert reference["counts"]["metrics"] == 0


def test_subagent_gap_for_non_evidence_subagent_only_looks_at_finished() -> None:
    """非证据 subagent 的缺口只看 finished；候选与指标不属于它的口径"""
    subagent = SubagentAnnotation(role="structure")
    gap = subagent_gap(subagent, candidate_total=0)
    assert gap == {"finished": False, "missing_candidates": [], "missing_metric": False}
    assert subagent_gap_is_clean(gap) is False
    subagent.finished = True
    gap = subagent_gap(subagent, candidate_total=3)
    assert gap == {"finished": True, "missing_candidates": [], "missing_metric": False}
    assert subagent_gap_is_clean(gap) is True


@pytest.mark.asyncio
async def test_subagent_gap_for_evidence_subagent_also_looks_at_candidates_and_metric() -> None:
    """证据 subagent 的缺口还要看未判候选与 missing_metric，两者未消即不 clean"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="evidence")
    runtime = _runtime(ledger, subagent)
    subagent.finished = True
    gap = subagent_gap(subagent, candidate_total=3)
    assert gap == {"finished": True, "missing_candidates": [1, 2, 3], "missing_metric": True}
    assert subagent_gap_is_clean(gap) is False

    await _run(
        runtime,
        'dialogue(candidate_index=1, verdict="not_dialogue")\n'
        'dialogue(candidate_index=2, verdict="not_dialogue")\n'
        'dialogue(candidate_index=3, verdict="not_dialogue")',
    )
    gap = subagent_gap(subagent, candidate_total=3)
    assert gap["missing_candidates"] == []
    assert gap["missing_metric"] is True
    assert subagent_gap_is_clean(gap) is False

    await _run(runtime, 'metric(summary="冲突", emotional_valence=0, narrative_function="冲突")')
    gap = subagent_gap(subagent, candidate_total=3)
    assert gap == {"finished": True, "missing_candidates": [], "missing_metric": False}
    assert subagent_gap_is_clean(gap) is True


@pytest.mark.asyncio
async def test_subagent_gap_evidence_subagent_is_incomplete_without_finish_declaration() -> None:
    """证据 subagent 未声明收尾：即使候选判完、指标交了，也不算 clean"""
    ledger = _ledger()
    subagent = SubagentAnnotation(role="evidence")
    runtime = _runtime(ledger, subagent)
    await _run(
        runtime,
        'dialogue(candidate_index=1, verdict="not_dialogue")\n'
        'dialogue(candidate_index=2, verdict="not_dialogue")\n'
        'dialogue(candidate_index=3, verdict="not_dialogue")\n'
        'metric(summary="冲突", emotional_valence=0, narrative_function="冲突")',
    )
    gap = subagent_gap(subagent, candidate_total=3)
    assert gap["finished"] is False
    assert gap["missing_candidates"] == []
    assert gap["missing_metric"] is False
    assert subagent_gap_is_clean(gap) is False
