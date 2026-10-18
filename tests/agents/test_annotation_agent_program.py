"""章内三代理并发：单个 agent 的构造器与程序面合同测试

覆盖 agent_program 的模型可见面与 "写入生效"口径：

- 三个 agent 的模型可见面逐字相同（绑定面只有 execute_code + finish），程序目录 =
  search_text + push_case + finish + 八类构造器，五个 write_* 既不在可见面也不在命名空间；
- 八类构造器写入生效：构造器是纯校验器，运行时把那一笔经生产单条事务边界
  （graph._execute_call）当场落库，**写入成功才**回 `{status:"written", record, ref}`
  并把记录放进 agent；共享章级账本（written_entities / entity_el_index /
  tree_key_index / written_relations / written_dialogues / metrics_payload /
  pushed_cases）当场可见；
- el 按角色命名空间化（实体 entity:a1、事件 entity:t1 与 entity:t1/e2），
  三个 agent 的同名局部键不互相占用；同名实体由生产写入自己按名会合；
- 失败（构造器校验或生产面拒绝）一律结构化回执 record/field/code/expected，且
  agent 的列表与共享账本都不变；
- 同键重写=更新语义（实体=本 agent id、事件=el、对话=候选号、标签=段号）；
- agent 的 finish 是面上一等工具（不是构造器），agent_gap 的口径与之一致；
- 构造器目录与实际命名空间同源：目录里的每个名字都直接调得动，签名与参数说明同轮下发。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.annotation.agent_ir import AgentAnnotation
from src.agents.annotation.agent_program import agent_gap
from src.agents.annotation.agent_runtime import AgentProgramRuntime
from src.agents.annotation.errors import AnnotationDependencyError, AnnotationInvariantError
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.text_search import TextSearchService
from src.agents.annotation.tool_batch import _execute_call
from src.agents.turn_observer import AgentTurnObserver
from src.embedding import EmbeddingConnectionError, EmbeddingServiceError, EmbeddingTimeoutError
from src.fact_graph.graph import FactGraph, entity_key
from src.fact_graph.inputs import ChapterParagraphInfo
from tests.support.annotation_work_tools import build_annotation_tools
from tests.support.storage_fixtures import fixture_id, storage_for

# 三段正文：¶1/¶2/¶3 各有一个引号对话候选，整章共 3 条候选（对话判定候选号 1..3）；
# "长刀" 在 ¶2，作为 item 实体与参与者测试的锚点
PARAGRAPHS: dict[int, str] = {
    1: "“站住！”沈遥喝道。",
    2: "“退下。”她收起长刀，转身走进雨里。",
    3: "“我走了。”沈遥回头。",
}
CHAPTER_TEXT = "".join(PARAGRAPHS.values())

# evidence 只按段号 id 锚定：单个段首可见号整数，不再带逐字引文
E_PERSON = 1
E_KNIFE = 2
E_SHOUT = 1
E_TALK = 1

_CHARACTER_ITEM = {
    "name": "沈遥",
    "entity_type": "character",
    "role": "主体",
    "narrative_role": "主体",
    "action": "喝止",
    "emotion": -1,
}

# 八类构造器全部走一遍：每条都能当场落库（a3 是 organization，"敌对" 允许 character→organization）
_WRITE_EVERYTHING = (
    "entity(id='a1', name='沈遥', entity_type='character', evidence=1)\n"
    "entity(id='a2', name='长刀', entity_type='item', evidence=2)\n"
    "entity(id='a3', name='剑宗', entity_type='organization', evidence=3"
    ")\n"
    "relation(from_entity={'name': '沈遥', 'entity_type': 'character'}, "
    "to_entity={'name': '剑宗', 'entity_type': 'organization'}, relation"
    "_type='敌对', evidence=2)\n"
    "event(el='t1', evidence=1, title='沈遥喝止', problem='明确事件问题', summar"
    "y='沈遥喝止', event_type='行动', status='ongoing')\n"
    "event(el='t1/e2', evidence=2, title='转身', problem='明确事件问题', summa"
    "ry='转身', event_type='行动', status='ongoing')\n"
    "participants(el='t1', items=[{'name': '沈遥', 'entity_type': 'chara"
    "cter', 'role': '主体', 'narrative_role': '主体', 'action': '喝止', 'emo"
    "tion': -1}])\n"
    "dialogue(candidate_index=1, verdict='dialogue', speaker={'name': "
    "'沈遥', 'entity_type': 'character'}, tone='愤怒', evidence=1)\n"
    "label(paragraph_id=1, emotion=-1)\n"
    "metric(summary='冲突', emotional_valence=-1, narrative_function='冲突"
    "')\n"
    "pending(case_type='character', description='长刀来路不明')"
)


class _QueryService:
    """用于提供无数据库依赖的查询桩（0.2.0 标注面只检索原文）"""

    current_chapter_order = None

    async def search_text(self, query, *, range_name, limit=50):
        """用于返回空正文命中"""
        del query, range_name, limit
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


def _ledger() -> AnnotationToolLedger:
    """用于构造一个 agent 的共享章级账本（整章正文、三段坐标）"""
    return AnnotationToolLedger(
        run_scope="run-agent-test",
        current_chapter_id=1,
        current_chapter_text=CHAPTER_TEXT,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=_paragraph_info(),
    )


def _tools(ledger: AnnotationToolLedger) -> dict[str, Any]:
    """用于按生产装配方式取工具名 → 工具表的映射（构造器要经它落库）"""
    return {str(tool.name): tool for tool in build_annotation_tools(_QueryService(), ledger)}


def _runtime(
    ledger: AnnotationToolLedger,
    agent: AgentAnnotation | None = None,
    *,
    tool_map: dict[str, Any] | None = None,
    **kwargs: Any,
) -> AgentProgramRuntime:
    """用于按生产装配方式建一个 agent 的程序面（共享账本 + 生产工具表）"""
    if agent is None:
        agent = AgentAnnotation(role="entity")
    if tool_map is None:
        tool_map = _tools(ledger)
    ledger.role = agent.role
    ledger.finish_work.__self__.agent = agent
    return AgentProgramRuntime(tool_map, ledger, agent, **kwargs)


async def _run(runtime: AgentProgramRuntime, code: str) -> dict[str, Any]:
    """用于走模型真实路径执行一段程序并解析压缩回执"""
    return json.loads(await runtime.execute(code))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_type", [EmbeddingConnectionError, EmbeddingTimeoutError, EmbeddingServiceError])
async def test_embedding_failure_aborts_program_after_auditing_both_call_levels(failure_type) -> None:
    """真实程序与工具边界：失败检索和 execute_code 都留审计，后续写入和 finish 不执行"""
    client = SimpleNamespace(get_embedding=AsyncMock(side_effect=failure_type("嵌入服务不可用")))
    search = TextSearchService(
        storage_for(MagicMock()), run_id=fixture_id(__name__, "run-agent-test"), embedding_client=client
    )

    class FailingQuery(_QueryService):
        async def search_text(self, query, *, range_name, limit=50):
            return await search.search(query, limit=limit)

    ledger = _ledger()
    tools = {tool.name: tool for tool in build_annotation_tools(FailingQuery(), ledger)}
    recorder = MagicMock()
    recorder.start_turn.return_value = 1
    observer = AgentTurnObserver(recorder, invocation_id=fixture_id(__name__, "1"), context={})
    observer.begin_provider_turn(context_summary={}, request_messages=[], provider_request={}, started_ns=1)
    observer.complete_provider_turn(
        response_message=AIMessage(content="", tool_calls=[{"name": "execute_code", "args": {}, "id": "code"}]),
        timing=SimpleNamespace(ttft_ms=0, first_visible_ms=0, reasoning_ms=0, model_ms=0, timing_notes=[]),
    )
    runtime = _runtime(ledger, tool_map=tools, observer=observer)
    program = runtime.build_tool()
    code = 'search_text(query="沈遥")\nentity(id="late", name="迟到", entity_type="character")\nfinish()'
    with (
        patch("src.storage.access.ParagraphAccess.search_paragraphs_by_keywords", return_value=[]),
        pytest.raises(AnnotationDependencyError, match="嵌入服务不可用"),
    ):
        await _execute_call(
            {"name": program.name, "id": "code", "args": {"code": code}},
            tool_map={program.name: program},
            ledger=ledger,
            observer=observer,
            call_index=0,
        )
    calls = [call.kwargs for call in recorder.record_tool_call.call_args_list]
    assert [call["tool_name"] for call in calls] == ["search_text", "execute_code"]
    assert all(call["status"] == "error" for call in calls)
    assert calls[0]["request_args"]["_program"]["source_line"] == 1
    assert calls[0]["receipt"]["code"] == "dependency_unavailable"
    recorder.update_turn_timings.assert_called_once()
    assert not runtime.agent.entities and not ledger.chapter_finished
    assert client.get_embedding.await_count == 1


def _failed_entry(receipt: dict[str, Any]) -> dict[str, Any]:
    """用于取压缩回执里唯一那条失败记录（并断言确实只有一条）"""
    failed = receipt.get("failed")
    assert isinstance(failed, list) and len(failed) == 1, receipt
    return failed[0]


async def _runtime_rejection(runtime: AgentProgramRuntime, code: str) -> dict[str, Any]:
    """用于执行一段程序并断言唯一失败记录带齐模型可见的四个定位字段"""
    entry = _failed_entry(await _run(runtime, code))
    for key in ("record", "field", "code", "expected"):
        assert entry.get(key), entry
    return entry


@pytest.mark.asyncio
async def test_pending_rejects_removed_structured_parameters() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = _failed_entry(await _run(runtime, 'pending(kind="case_clue", detail="疑点", evidence=1)'))
    assert receipt["code"] == "invalid_call"
    assert "kind" in receipt["message"]
    assert "pending(case_type:" in receipt["expected"]
    assert runtime.agent.pending == []


def test_runtime_rejects_missing_work_finish_validation() -> None:
    """没有独立 work 校验时直接失败，不再创建旧角色收尾工具"""
    ledger = _ledger()
    tools = _tools(ledger)
    ledger.finish_work = None
    with pytest.raises(AnnotationInvariantError, match="work 收尾校验未装配"):
        AgentProgramRuntime(tools, ledger, AgentAnnotation(role="entity"))


# ----------------------------------------------------------------------
# 二、八类构造器：成功路径（写入生效，agent 与共享账本同一条事实）


@pytest.mark.asyncio
async def test_eight_constructors_write_records_into_the_agent_and_shared_ledger() -> None:
    """八类构造器逐一成功：记录当场进 agent 与共享章级账本，回执/进度逐域可见"""
    ledger = _ledger()
    agent = AgentAnnotation(role="entity")
    runtime = _runtime(ledger, agent)

    receipt = await _run(runtime, _WRITE_EVERYTHING)

    # 八类构造器共 11 条（实体 3 + 关系 1 + 事件 2 + 参与者 1 + 对话 1 + 标签 1 + 指标 1 + 待决 1）
    assert receipt["status"] == "applied"
    assert receipt["applied"] == 11
    assert "failed" not in receipt
    assert (
        receipt["progress"]
        == agent.counts()
        == {
            "entities": 3,
            "relations": 1,
            "events": 2,
            "dialogues": 1,
            "labels": 1,
            "metrics": 1,
            "pending": 1,
            "plotlines": 0,
            "foreshadow_actions": 0,
        }
    )

    # 逐 op 记录：构造器名 + 角色命名空间化的记录键，全部成功
    records = [op["record"] for op in runtime.ops]
    assert all(op["status"] == "success" for op in runtime.ops)
    assert records[0] == "entity/a1"
    assert "entity/relation/沈遥-剑宗" in records
    assert "entity/event/t1" in records
    assert "entity/event/t1/e2" in records
    assert "entity/participants/t1" in records
    assert "entity/dialogue/1" in records
    assert "entity/label/1" in records
    assert "entity/metric" in records
    assert "entity/pending" in records

    # agent 的产出记录
    assert [item.id for item in agent.entities] == ["a1", "a2", "a3"]
    assert [item.name for item in agent.entities] == ["沈遥", "长刀", "剑宗"]
    assert len(agent.relations) == 1
    assert len(agent.events) == 2
    assert [event.evidence_paragraph_id for event in ledger.bound_payloads["events"]] == [1, 2]
    assert agent.event_keys()["t1"].participants[0].name == "沈遥"
    assert agent.dialogues[0].speaker.name == "沈遥"
    assert [item.paragraph_id for item in agent.labels] == [1]
    assert agent.metric is not None and agent.metric.summary == "冲突"
    assert agent.pending[0].description == "长刀来路不明"

    # 共享章级账本：实体 el 索引、事件树键索引、关系、对话、指标都当场可见
    assert set(ledger.written_entities) == {
        entity_key("沈遥", "character"),
        entity_key("长刀", "item"),
        entity_key("剑宗", "organization"),
    }
    assert ledger.entity_el_index["entity:a1"] == entity_key("沈遥", "character")
    assert ledger.entity_el_index["entity:a2"] == entity_key("长刀", "item")
    assert "entity:t1" in ledger.tree_key_index
    tree = ledger.event_trees[ledger.tree_key_index["entity:t1"]]
    assert set(tree["nodes"]) == {"root", "e2"}
    relation = ledger.written_relations[(entity_key("沈遥", "character"), entity_key("剑宗", "organization"))]
    assert relation.relation_type == "敌对"
    assert ledger.written_dialogues[1].speaker == "沈遥"
    assert ledger.written_dialogues[1].tone == "愤怒"
    assert ledger.metrics_payload is not None
    assert ledger.metrics_payload.summary == "冲突"
    # 标签与指标在生产面同属 write_metrics 一个域：metric 构造器不带 labels，标签留待章收尾链
    assert ledger.metrics_payload.labels == []
    assert set(ledger.observation_by_record) != set()

    # 构造器直接调用只产出计划对象（纯校验），不改任何已落账状态
    entity_plan = runtime.tools["entity"](id="a1", name="沈遥", entity_type="character", evidence=E_PERSON)
    assert entity_plan.record == "entity/a1"
    assert entity_plan.ref == {"kind": "entity", "id": "a1", "name": "沈遥", "entity_type": "character"}
    relation_plan = runtime.tools["relation"](
        from_entity={"name": "沈遥", "entity_type": "character"},
        to_entity={"name": "剑宗", "entity_type": "organization"},
        relation_type="敌对",
        evidence=E_KNIFE,
    )
    assert relation_plan.ref == {
        "kind": "relation",
        "type": "敌对",
        "from_entity": {"name": "沈遥", "entity_type": "character"},
        "to_entity": {"name": "剑宗", "entity_type": "organization"},
    }
    assert relation_plan.args == {
        "from_entity": {"name": "沈遥", "entity_type": "character"},
        "to_entity": {"name": "剑宗", "entity_type": "organization"},
        "relation_type": "敌对",
    }
    root_plan = runtime.tools["event"](
        el="t1",
        title="沈遥喝止",
        problem="明确事件问题",
        summary="沈遥喝止",
        event_type="行动",
        status="ongoing",
        evidence=E_SHOUT,
    )
    assert root_plan.ref == {"kind": "declaration", "el": "t1"}
    assert root_plan.args["evidence"] == E_SHOUT
    child_plan = runtime.tools["event"](
        el="t1/e2",
        title="转身",
        problem="明确事件问题",
        summary="转身",
        event_type="行动",
        status="ongoing",
        evidence=E_KNIFE,
    )
    assert child_plan.ref == {"kind": "declaration", "el": "t1/e2"}
    assert child_plan.args["evidence"] == E_KNIFE
    participants_plan = runtime.tools["participants"](el="t1", items=[_CHARACTER_ITEM])
    assert participants_plan.ref == {"kind": "participants", "el": "t1", "count": 1}
    dialogue_plan = runtime.tools["dialogue"](
        candidate_index=1,
        verdict="dialogue",
        speaker={"name": "沈遥", "entity_type": "character"},
        tone="愤怒",
        evidence=E_TALK,
    )
    assert dialogue_plan.ref == {"kind": "dialogue", "candidate_index": 1, "verdict": "dialogue"}
    label_plan = runtime.tools["label"](paragraph_id=1, emotion=-1)
    assert label_plan.ref == {"kind": "label", "paragraph_id": 1, "emotion": -1}
    metric_plan = runtime.tools["metric"](summary="冲突", emotional_valence=-1, narrative_function="冲突")
    assert metric_plan.ref == {"kind": "metric", "summary": "冲突"}
    pending_plan = runtime.tools["pending"](case_type="character", description="长刀来路不明")
    assert pending_plan.ref == {"kind": "pending"}
    # 直接调用没有落账：计数与计划调用前一致
    assert agent.counts() == receipt["progress"]


@pytest.mark.asyncio
async def test_constructor_call_receipt_is_written_with_record_and_ref() -> None:
    """单条构造器调用成功时的回执 = {status:"written", record, ref}（写入成功才回）"""
    ledger = _ledger()
    agent = AgentAnnotation(role="entity")
    runtime = _runtime(ledger, agent)
    receipt = await runtime._dispatch(
        "entity",
        {"id": "a1", "name": "沈遥", "entity_type": "character", "evidence": E_PERSON},
        line=None,
    )
    assert receipt["status"] == "written"
    assert receipt["record"] == "entity/a1"
    assert receipt["ref"] == {"kind": "entity", "id": "a1", "name": "沈遥", "entity_type": "character"}
    assert [item.id for item in agent.entities] == ["a1"]
    assert ledger.entity_el_index["entity:a1"] == entity_key("沈遥", "character")


@pytest.mark.asyncio
async def test_every_call_returns_one_of_the_three_receipt_shapes() -> None:
    """构造器与工具走同一条分发：回执只有写成/读到/被拒三种形状"""
    ledger = _ledger()
    agent = AgentAnnotation(role="entity")
    runtime = _runtime(ledger, agent)

    written = await runtime._dispatch(
        "entity", {"id": "a1", "name": "沈遥", "entity_type": "character", "evidence": E_PERSON}, line=None
    )
    assert written["status"] == "written"
    assert set(written) == {"status", "record", "ref"}

    read = await runtime._dispatch("search_text", {"query": "沈遥"}, line=None)
    assert isinstance(read, list)

    structured = await runtime._dispatch(
        ("relation"),
        {("from_entity"): {("name"): ("沈遥"), ("entity_type"): ("character")}, ("to_id"): ("a9")},
        line=None,
    )
    assert structured["status"] == "rejected"
    assert structured["code"] == "invalid_call"
    # 校验没过就没有记录键可算（record 只能给调用名），自纠靠 expected 里的真实签名
    assert structured["record"] == "relation"
    assert structured["expected"].startswith("relation(")


# ----------------------------------------------------------------------
# 三、八类构造器：拒绝路径（结构化拒绝且 agent 与共享账本都不变）


@pytest.mark.asyncio
async def test_entity_rejects_out_of_range_type_without_writing() -> None:
    """entity_type 越界：invalid_value/entity_type，agent 与共享账本里都不留记录"""
    ledger = _ledger()
    agent = AgentAnnotation(role="entity")
    runtime = _runtime(ledger, agent)
    entry = await _runtime_rejection(runtime, 'entity(id="a1", name="沈遥", entity_type="divinity", evidence=1)')
    assert entry["code"] == "invalid_value"
    assert entry["field"] == "entity_type"
    assert agent.entities == []
    assert ledger.written_entities == {} and ledger.entity_el_index == {}


@pytest.mark.asyncio
async def test_entity_rejects_evidence_that_is_not_a_single_in_chapter_id() -> None:
    """evidence 只收单个段号：多号数组与越界号都结构化拒绝，agent 里不留记录"""
    ledger = _ledger()
    agent = AgentAnnotation(role="entity")
    runtime = _runtime(ledger, agent)
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
    assert agent.entities == []
    assert ledger.written_entities == {} and ledger.entity_el_index == {}


@pytest.mark.asyncio
async def test_relation_rejects_out_of_range_type_without_writing() -> None:
    """relation_type 越界：invalid_value/relation_type，agent 与共享账本里都不留记录"""
    ledger = _ledger()
    agent = AgentAnnotation(role="entity")
    runtime = _runtime(ledger, agent)
    await _run(
        runtime,
        'entity(id="a1", name="沈遥", entity_type="character", evidence=1)\n'
        'entity(id="a2", name="长刀", entity_type="item", evidence=2)',
    )
    entry = await _runtime_rejection(
        runtime,
        (
            'relation(from_entity={"name": "沈遥", "entity_type": "character"}, '
            'to_entity={"name": "长刀", "entity_type": "item"}, relation_type="父'
            '女", evidence=2)'
        ),
    )
    assert entry["code"] == "invalid_value"
    assert entry["field"] == "relation_type"
    assert agent.relations == []
    assert ledger.written_relations == {}


@pytest.mark.parametrize(
    "field,value", [("title", ""), ("problem", ""), ("summary", ""), ("event_type", ""), ("status", "finished")]
)
@pytest.mark.asyncio
async def test_event_business_fields_are_rejected_without_writing(field: str, value: str) -> None:
    ledger = _ledger()
    agent = AgentAnnotation(role="event")
    runtime = _runtime(ledger, agent)
    kwargs = {
        "el": "e1",
        "title": "事件",
        "problem": "问题",
        "summary": "概要",
        "event_type": "行动",
        "status": "ongoing",
        "evidence": 1,
    }
    kwargs[field] = value
    args = ", ".join(f"{key}={item!r}" for key, item in kwargs.items())
    entry = await _runtime_rejection(runtime, f"event({args})")
    assert entry["field"] == field
    assert not agent.events
    assert not ledger.bound_payloads.get("events")


@pytest.mark.asyncio
async def test_event_accepts_foreshadowing_property_on_child() -> None:
    """任意有原文依据的实际过程可以埋设，根和子过程都保持准确身份"""
    ledger = _ledger()
    agent = AgentAnnotation(role="event")
    runtime = _runtime(ledger, agent)
    receipt = await _run(
        runtime,
        (
            "event(el='t1', evidence=2, title='转身', problem='明确事件问题', summary="
            "'转身', event_type='行动', status='ongoing')\n"
            "event(el='t1/e2', isforeshadowing=True, confidence='high', eviden"
            "ce=2, title='发现线索', problem='明确事件问题', summary='发现线索', event_type="
            "'行动', status='ongoing')"
        ),
    )
    assert receipt.get("failed", []) == []
    child = next(value for value in ledger.bound_payloads["events"] if value.is_foreshadow_setup)
    assert child.cause_role == "root"
    assert child.parent_node_id is None
    assert child.payoff_likelihood == "high"


@pytest.mark.asyncio
async def test_participants_rejects_unknown_event_and_lands_partial_three_state() -> None:
    """participants 引用不存在的事件 el 拒绝；三态只给一半照常落账

    未登记实体引用一律拒绝（引用面不放开）；叙事功能近义词归一、emotion 钳制
    在构造层完成，生产面按实体登记大类给 role 缺省。
    """
    ledger = _ledger()
    agent = AgentAnnotation(role="event")
    runtime = _runtime(ledger, agent)
    unknown = await _runtime_rejection(
        runtime, 'participants(el="t9", items=[{"name": "沈遥", "entity_type": "character", "role": "主体"}])'
    )
    assert unknown["code"] == "unknown_reference"
    assert unknown["field"] == "el"
    await _run(
        runtime,
        (
            "event(el='t1', evidence=1, title='喝止', problem='明确事件问题', summary="
            "'喝止', event_type='行动', status='ongoing')\n"
            "entity(id='a1', name='沈遥', entity_type='character', evidence=1)"
        ),
    )
    await _run(
        runtime,
        (
            'participants(el="t1", items=[{"name": "沈遥", "entity_type": "chara'
            'cter", "role": "主体", "narrative_role": "主角", "emotion": 9}])'
        ),
    )
    (participant,) = agent.event_keys()["t1"].participants
    assert participant.role == "主体"
    assert participant.narrative_role == "主体"
    assert participant.emotion == 2
    assert participant.action is None
    unregistered = await _runtime_rejection(
        runtime, 'participants(el="t1", items=[{"entity_id": "a9", "role": "主体"}])'
    )
    assert unregistered["code"] == "invalid_value"
    assert unregistered["field"] == "participants[0]"


@pytest.mark.asyncio
async def test_dialogue_rejections_do_not_write() -> None:
    """候选号越界、not_dialogue 带说话人、非 not_dialogue 缺引文、说话人键含斜杠都拒绝"""
    ledger = _ledger()
    agent = AgentAnnotation(role="metric")
    runtime = _runtime(ledger, agent)
    out_of_range = await _run(runtime, 'dialogue(candidate_index=9, verdict="dialogue", evidence=1)')
    assert out_of_range["status"] == "rejected"
    assert out_of_range["applied"] == 0
    assert out_of_range["error"]["type"] == "candidate_index_out_of_range"
    assert "total=3" in out_of_range["error"]["message"]
    assert "dialogue/9(candidate_index=9)" in out_of_range["error"]["message"]
    assert runtime.ops == []
    not_dialogue = await _runtime_rejection(
        runtime,
        'dialogue(candidate_index=1, verdict="not_dialogue", speaker={"name": "沈遥", "entity_type": "character"})',
    )
    assert not_dialogue["code"] == "invalid_value"
    assert not_dialogue["field"] == "verdict"
    missing_evidence = await _runtime_rejection(runtime, 'dialogue(candidate_index=1, verdict="dialogue")')
    assert missing_evidence["code"] == "missing_evidence"
    assert missing_evidence["field"] == "evidence"
    bad_speaker = await _runtime_rejection(
        runtime,
        'dialogue(candidate_index=1, verdict="dialogue", '
        'speaker={"name": "沈遥", "entity_type": "invalid"}, evidence=1)',
    )
    assert bad_speaker["code"] == "invalid_value"
    assert bad_speaker["field"] == "speaker"
    assert agent.dialogues == []
    assert ledger.written_dialogues == {}


@pytest.mark.asyncio
async def test_label_rejections_do_not_write() -> None:
    """段号不属于本章、emotion 越界（如 3）都拒绝，agent 里不留标签"""
    ledger = _ledger()
    agent = AgentAnnotation(role="metric")
    runtime = _runtime(ledger, agent)
    foreign = await _runtime_rejection(runtime, "label(paragraph_id=99, emotion=0)")
    assert foreign["code"] == "out_of_range"
    assert foreign["field"] == "paragraph_id"
    out_of_range = await _runtime_rejection(runtime, "label(paragraph_id=1, emotion=3)")
    assert out_of_range["code"] == "invalid_value"
    assert out_of_range["field"] == "emotion"
    assert agent.labels == []
    assert ledger.metrics_payload is None


@pytest.mark.asyncio
async def test_metric_rejects_out_of_range_narrative_function() -> None:
    """narrative_function 越界：invalid_value/narrative_function，agent 里不留指标"""
    ledger = _ledger()
    agent = AgentAnnotation(role="metric")
    runtime = _runtime(ledger, agent)
    entry = await _runtime_rejection(runtime, 'metric(summary="x", emotional_valence=0, narrative_function="高潮")')
    assert entry["code"] == "invalid_value"
    assert entry["field"] == "narrative_function"
    assert agent.metric is None
    assert ledger.metrics_payload is None


# ----------------------------------------------------------------------
# 四、生产面拒绝：写入被生产单条事务边界拒下，agent 与共享账本都不变


@pytest.mark.asyncio
async def test_event_orphan_defers_until_root_arrives() -> None:
    """子事件先于树根构造：树键在生产面校验，挂起而非拒绝

    子事件写入即时生效（回执 written、构造器记入 plan），等根建好后按到达顺序
    冲账进正式事件树；根始终不建时由 finish 拒绝收尾，不静默丢数据。
    """
    ledger = _ledger()
    agent = AgentAnnotation(role="event")
    runtime = _runtime(ledger, agent)
    await _run(
        runtime,
        (
            "event(el='t1/e2', evidence=2, title='转身', problem="  # 同一程序文本
            "'明确事件问题', summary='转身', event_type='行动', status='o"  # 同一程序文本
            "ngoing')"  # 同一程序文本
        ),
    )

    assert "t1/e2" in agent.event_keys()
    # 构造器 el 经角色命名空间化后才进生产面：挂起键是 event:t1
    assert ledger.pending_child_events == {}
    assert ledger.bound_payloads["events"][0].parent_node_id is None

    await _run(
        runtime,
        (
            "event(el='t1', evidence=1, title='喝止', problem='明确"  # 同一程序文本
            "事件问题', summary='喝止', event_type='行动', status='ongo"  # 同一程序文本
            "ing')"  # 同一程序文本
        ),
    )
    tree = ledger.event_trees[ledger.tree_key_index["event:t1"]]
    assert sorted(tree["nodes"]) == ["e2", "root"]
    assert ledger.pending_child_events == {}


@pytest.mark.asyncio
async def test_entity_duplicate_el_is_rejected_by_production_without_trace() -> None:
    """同一 el 已绑定另一实体：第二笔写入被生产面以 duplicate_el 拒绝，只保留第一笔"""
    ledger = _ledger()
    agent = AgentAnnotation(role="entity")
    runtime = _runtime(ledger, agent)
    entry = await _runtime_rejection(
        runtime,
        'entity(id="a1", name="沈遥", entity_type="character", evidence=1)\n'
        'entity(id="a1", name="长刀", entity_type="item", evidence=2)',
    )
    assert entry["code"] == "duplicate_el"
    assert entry["field"] == "el"
    assert [item.name for item in agent.entities] == ["沈遥"]
    assert set(ledger.written_entities) == {entity_key("沈遥", "character")}
    assert ledger.entity_el_index == {"entity:a1": entity_key("沈遥", "character")}


@pytest.mark.asyncio
async def test_dialogue_non_character_speaker_is_rejected_by_production() -> None:
    """说话人非 character：构造器放行、生产面以 not_character 拒绝，对话账本不动"""
    ledger = _ledger()
    agent = AgentAnnotation(role="metric")
    runtime = _runtime(ledger, agent)
    entry = await _runtime_rejection(
        runtime,
        'entity(id="a2", name="长刀", entity_type="item", evidence=2)\n'
        'dialogue(candidate_index=1, verdict="dialogue", sp'  # 同一程序文本
        'eaker={"name": "长刀", "entity_type": "item"}, evide'  # 同一程序文本
        "nce=1)",
    )
    assert entry["code"] == "not_character"
    assert entry["field"] == "speaker"
    assert agent.dialogues == []
    assert ledger.written_dialogues == {}


@pytest.mark.asyncio
async def test_participants_non_character_observation_is_ignored_by_production() -> None:
    """非 character 参与者带三态：生产面忽略三态、保留 entityid/role，不产人物动态状态"""
    ledger = _ledger()
    agent = AgentAnnotation(role="event")
    runtime = _runtime(ledger, agent)
    await _run(
        runtime,
        (
            "entity(id='a2', name='长刀', entity_type='item', evidence=2)\n"
            "event(el='t1', evidence=1, title='喝止', problem='明确事件问题', summary="
            "'喝止', event_type='行动', status='ongoing')\n"
            "participants(el='t1', items=[{'name': '长刀', 'entity_type': 'item'"
            ", 'role': '客体', 'narrative_role': '客体', 'action': '被喝', 'emotion'"
            ": -1}])"
        ),
    )
    (ir_participant,) = agent.event_keys()["t1"].participants
    assert ir_participant.name == "长刀"
    event = next(value for value in ledger.bound_payloads["events"] if value.description == "喝止")
    (participant,) = event.participants
    assert (ledger.graph.display_name(participant.entity), participant.role) == ("长刀", "客体")
    assert (participant.narrative_role, participant.action, participant.emotion) == (None, None, None)
    assert ledger.observation_by_record == {}


# ----------------------------------------------------------------------
# 五、同 id 不互相占用：三个 agent 各用局部键，落库按角色命名空间化


@pytest.mark.asyncio
async def test_same_local_id_across_agents_does_not_collide() -> None:
    """entity 与 event 各自的 a1 是两条实体：落库 el 不同名，互不占用"""
    ledger = _ledger()
    entity_lane = AgentAnnotation(role="entity")
    event = AgentAnnotation(role="event")
    entity_runtime = _runtime(ledger, entity_lane)
    event_runtime = _runtime(ledger, event)
    await _run(entity_runtime, 'entity(id="a1", name="沈遥", entity_type="character", evidence=1)')
    await _run(event_runtime, 'entity(id="a1", name="长刀", entity_type="item", evidence=2)')
    assert set(ledger.written_entities) == {entity_key("沈遥", "character"), entity_key("长刀", "item")}
    assert ledger.entity_el_index == {
        "entity:a1": entity_key("沈遥", "character"),
        "event:a1": entity_key("长刀", "item"),
    }


@pytest.mark.asyncio
async def test_same_name_across_agents_merges_into_one_entity() -> None:
    """entity 与 event 各自的 a1 同名：生产面按名会合，账本里只有一条实体"""
    ledger = _ledger()
    entity_lane = AgentAnnotation(role="entity")
    event = AgentAnnotation(role="event")
    entity_runtime = _runtime(ledger, entity_lane)
    event_runtime = _runtime(ledger, event)
    await _run(entity_runtime, 'entity(id="a1", name="沈遥", entity_type="character", evidence=1)')
    await _run(event_runtime, 'entity(id="a1", name="沈遥", entity_type="character", evidence=1)')
    assert set(ledger.written_entities) == {entity_key("沈遥", "character")}
    assert ledger.entity_el_index == {
        "entity:a1": entity_key("沈遥", "character"),
        "event:a1": entity_key("沈遥", "character"),
    }


# ----------------------------------------------------------------------
# 六、pending 进案例池：keys 是登记名（不是局部 id）


# ----------------------------------------------------------------------
# 七、标签只在 journal、指标当场落 write_metrics 域


@pytest.mark.asyncio
async def test_label_only_lands_in_journal_and_metric_hits_ledger() -> None:
    """label 只落 agent 的 journal（不单独落库）；metric 当场写 write_metrics（不带 labels）"""
    ledger = _ledger()
    agent = AgentAnnotation(role="metric")
    runtime = _runtime(ledger, agent)
    await _run(runtime, "label(paragraph_id=1, emotion=-1)\nlabel(paragraph_id=2, emotion=2)")
    assert [item.paragraph_id for item in agent.labels] == [1, 2]
    # 标签与指标同属 write_metrics 一个域：没有指标时标签也不单独落库
    assert ledger.metrics_payload is None
    await _run(runtime, 'metric(summary="冲突", emotional_valence=0, narrative_function="冲突")')
    assert ledger.metrics_payload is not None
    assert ledger.metrics_payload.labels == []
    assert agent.metric is not None and agent.metric.summary == "冲突"


# ----------------------------------------------------------------------
# 八、同键重写=更新语义


@pytest.mark.asyncio
async def test_entity_same_id_rewrite_is_update_not_new_entry() -> None:
    """实体同 id 重写只留一条，字段按最后一次为准（name 只是展示字段）"""
    ledger = _ledger()
    agent = AgentAnnotation(role="entity")
    runtime = _runtime(ledger, agent)
    await _run(
        runtime,
        'entity(id="a1", name="沈遥", entity_type="character", evidence=1)\n'
        'entity(id="a1", name="沈遥", entity_type="character", evidence=1, description="持刀剑客")',
    )
    assert len(agent.entities) == 1
    assert agent.entities[0].id == "a1"
    assert agent.entities[0].description == "持刀剑客"
    assert set(ledger.written_entities) == {entity_key("沈遥", "character")}
    assert ledger.written_entities[entity_key("沈遥", "character")].description == "持刀剑客"


@pytest.mark.asyncio
async def test_event_same_el_rewrite_keeps_participants() -> None:
    """事件同 el 重写保留已挂的参与者（只更新描述与伏笔属性）"""
    ledger = _ledger()
    agent = AgentAnnotation(role="event")
    runtime = _runtime(ledger, agent)
    await _run(
        runtime,
        (
            "event(el='t1', evidence=1, title='喝止', problem='明确事件问题', summary="
            "'喝止', event_type='行动', status='ongoing')\n"
            "entity(id='a1', name='沈遥', entity_type='character', evidence=1)\n"
            "participants(el='t1', items=[{'name': '沈遥', 'entity_type': 'chara"
            "cter', 'role': '主体', 'narrative_role': '主体', 'action': '喝止', 'emo"
            "tion': -1}])\n"
            "event(el='t1', evidence=1, title='改述', problem='明确事件问题', summary="
            "'改述', event_type='行动', status='ongoing')"
        ),
    )
    assert len(agent.events) == 1
    assert agent.events[0].description == "喝止"
    assert len(agent.events[0].participants) == 1
    tree = ledger.event_trees[ledger.tree_key_index["event:t1"]]
    assert set(tree["nodes"]) == {"root"}  # 重写没新建节点
    assert len(ledger.observation_by_record) == 1  # 生产面的参与者动态状态原样保留


@pytest.mark.asyncio
async def test_dialogue_same_candidate_rewrite_is_update() -> None:
    """对话同候选号重写只留一条，判定按最后一次为准"""
    ledger = _ledger()
    agent = AgentAnnotation(role="metric")
    runtime = _runtime(ledger, agent)
    await _run(
        runtime,
        """
entity(id="a1", name="沈遥", entity_type="character", evidence=1)
dialogue(candidate_index=1, verdict="not_dialogue")
dialogue(candidate_index=1, verdict="dialogue", speaker={"name": "沈遥", "entity_type": "character"}, evidence=1)
""",
    )
    assert len(agent.dialogues) == 1
    assert agent.dialogues[0].verdict == "dialogue"
    assert agent.dialogues[0].speaker.name == "沈遥"
    assert ledger.written_dialogues[1].speaker == "沈遥"


@pytest.mark.asyncio
async def test_label_same_paragraph_rewrite_is_update() -> None:
    """标签同段号重写只留一条，分值按最后一次为准"""
    ledger = _ledger()
    agent = AgentAnnotation(role="metric")
    runtime = _runtime(ledger, agent)
    await _run(runtime, "label(paragraph_id=1, emotion=-1)\nlabel(paragraph_id=1, emotion=2)")
    assert len(agent.labels) == 1
    assert agent.labels[0].emotion == 2


# ----------------------------------------------------------------------
# 九、finish 工具与 agent_gap


def test_agent_gap_for_entity_agent_only_looks_at_finished() -> None:
    """实体/事件 agent 的缺口只看 finished；候选与指标不属于它的口径"""
    agent = AgentAnnotation(role="entity")
    gap = agent_gap(agent, candidate_total=0)
    assert gap == {"finished": False, "missing_candidates": [], "missing_metric": False}
    agent.finished = True
    gap = agent_gap(agent, candidate_total=3)
    assert gap == {"finished": True, "missing_candidates": [], "missing_metric": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["annotation", "metric"])
async def test_agent_gap_for_metric_agent_also_looks_at_candidates_and_metric(role: str) -> None:
    """整章与指标角色都必须齐备候选判定和指标，不能默认放行"""
    ledger = _ledger()
    agent = AgentAnnotation(role=role)
    runtime = _runtime(ledger, agent)
    agent.finished = True
    gap = agent_gap(agent, candidate_total=3)
    assert gap == {"finished": True, "missing_candidates": [1, 2, 3], "missing_metric": True}

    await _run(
        runtime,
        'dialogue(candidate_index=1, verdict="not_dialogue")\n'
        'dialogue(candidate_index=2, verdict="not_dialogue")\n'
        'dialogue(candidate_index=3, verdict="not_dialogue")',
    )
    gap = agent_gap(agent, candidate_total=3)
    assert gap["missing_candidates"] == []
    assert gap["missing_metric"] is True

    await _run(runtime, 'metric(summary="冲突", emotional_valence=0, narrative_function="冲突")')
    gap = agent_gap(agent, candidate_total=3)
    assert gap == {"finished": True, "missing_candidates": [], "missing_metric": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["annotation", "metric"])
async def test_agent_gap_metric_agent_is_incomplete_without_finish_declaration(role: str) -> None:
    """整章与指标角色未成功收尾时不能算完成"""
    ledger = _ledger()
    agent = AgentAnnotation(role=role)
    runtime = _runtime(ledger, agent)
    await _run(
        runtime,
        'dialogue(candidate_index=1, verdict="not_dialogue")\n'
        'dialogue(candidate_index=2, verdict="not_dialogue")\n'
        'dialogue(candidate_index=3, verdict="not_dialogue")\n'
        'metric(summary="冲突", emotional_valence=0, narrative_function="冲突")',
    )
    gap = agent_gap(agent, candidate_total=3)
    assert gap["finished"] is False
    assert gap["missing_candidates"] == []
    assert gap["missing_metric"] is False
