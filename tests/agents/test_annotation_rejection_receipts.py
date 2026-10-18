"""拒绝回执点名违规记录：收尾期拒绝必须点名相撞记录键与字段值"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.agents.annotation.errors import AnnotationStageRejection
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.tool_batch import _invoke_tool
from src.event_trees.models import BoundEvent
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import BoundRelationInput, ChapterParagraphInfo, EntityDirectoryInput
from src.fact_graph.outputs import BoundCharacterObservation
from src.fact_graph.vocabulary import RelationType
from tests.support.annotation_work_tools import build_annotation_tools
from tests.support.annotation_work_tools import build_program_test_runtime as ProgramRuntime


class _QueryService:
    """用于提供无数据库依赖的查询桩"""

    async def search_text(self, query, *, range_name, limit=50):
        del query, range_name, limit
        return []

    async def read_paragraph(self, paragraph_id: int, *, allow_future_context: bool) -> dict[str, Any]:
        assert allow_future_context and paragraph_id == 20
        return {"chapter_id": 2, "paragraph_id": 20, "text": "顾霜与众人结盟。"}


def _chapter_text() -> str:
    """用于提供含单段正文的测试章文本"""
    return "“住手！”顾霜喝道。“退下。”众人散去，夜色渐深。"


def _ledger(**overrides) -> AnnotationToolLedger:
    """用于构造带事实图与段落坐标的账本"""
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
    """用于按工具名索引写面"""
    return {tool.name: tool for tool in build_annotation_tools(_QueryService(), ledger)}


async def _call(tools: dict, name: str, args: dict) -> dict:
    """用于按生产路径（graph._invoke_tool）执行单个小调用并解析回执"""
    call = {"name": name, "args": args, "id": f"call-{name}", "type": "tool_call"}
    return json.loads(await _invoke_tool(tools, call))


def _duplicate_payloads(ledger: AnnotationToolLedger) -> dict:
    """用于按账本现值组装判重载荷（与 _build_ready_chapter 传入的 domain_payloads 同源）"""
    return {
        "character_observations": list(ledger.observation_by_record.values()),
        "events": list(ledger.bound_payloads.get("events") or []),
        "relations": list(ledger.written_relations.values()),
    }


def test_duplicate_observation_rejection_names_records_and_values() -> None:
    """判重拒绝点名相撞双方的生产记录键与 (character, action) 值，未相撞条目不出现"""
    ledger = _ledger()
    ledger.observation_by_record["t1/e1/participant/lyr"] = BoundCharacterObservation(character="李瑜", action="推门")
    ledger.observation_by_record["t2/e1/participant/李瑜"] = BoundCharacterObservation(character="李瑜", action="推门")
    ledger.observation_by_record["t3/e1/participant/顾霜"] = BoundCharacterObservation(character="顾霜", action="守门")
    with pytest.raises(ValueError) as excinfo:
        ledger._validate_domain_duplicates(_duplicate_payloads(ledger))
    message = str(excinfo.value)
    assert "character_observations 重复语义项" in message
    assert "t1/e1/participant/lyr(character=李瑜, action=推门)" in message
    assert "t2/e1/participant/李瑜(character=李瑜, action=推门)" in message
    assert "t3/e1/participant/顾霜" not in message


def test_duplicate_event_rejection_names_local_node_key() -> None:
    """事件判重点名模型面局部键（树键/节点键），不露 uuid"""
    ledger = _ledger()
    ledger.tree_key_index["t1"] = "tree-1"
    ledger.event_trees["tree-1"] = {"nodes": {"root": "node-root", "e2": "node-2"}}
    ledger.events.bound_payloads["events"] = [
        BoundEvent(
            node_id="node-2",
            tree_id="tree-1",
            cause_role="main",
            description="李瑜推门",
            title="李瑜推门",
            problem="明确事件问题",
            summary="李瑜推门",
            event_type="行动",
            status="ongoing",
            declaration_id="node-2",
        ),
        BoundEvent(
            node_id="node-2",
            tree_id="tree-1",
            cause_role="main",
            description="李瑜推门",
            title="李瑜推门",
            problem="明确事件问题",
            summary="李瑜推门",
            event_type="行动",
            status="ongoing",
            declaration_id="node-2",
        ),
    ]
    with pytest.raises(ValueError) as excinfo:
        ledger._validate_domain_duplicates(_duplicate_payloads(ledger))
    message = str(excinfo.value)
    assert "events 重复语义项: t1/e2 与 t1/e2" in message
    assert "node-2" not in message


def test_duplicate_relation_rejection_names_edge_key() -> None:
    """关系判重点名 from-to/类型 边键"""
    ledger = _ledger()
    edge = BoundRelationInput(from_entity="李瑜", to_entity="钱进", relation_type=RelationType.ALLY)
    with pytest.raises(ValueError) as excinfo:
        ledger._validate_domain_duplicates({"character_observations": [], "events": [], "relations": [edge, edge]})
    message = str(excinfo.value)
    assert "relations 重复语义项: relation/李瑜-钱进/盟友 与 relation/李瑜-钱进/盟友" in message


def test_endpoint_error_names_record_key() -> None:
    """端点校验失败点名生产记录键（原 "[下标] 域.字段" 模型无法映射回具体记录）"""
    ledger = _ledger()
    ledger.observation_by_record["t1/e1/participant/未登记者"] = BoundCharacterObservation(
        character="未登记者", action="推门"
    )
    ledger.entities.domain_payloads["entities"] = EntityDirectoryInput(entities=[])
    ledger.events.domain_payloads["character_observations"] = list(ledger.observation_by_record.values())
    ledger.dialogue.domain_payloads["dialogues"] = []
    ledger.entities.domain_payloads["relations"] = [
        BoundRelationInput(from_entity="未登记者", to_entity="李瑜", relation_type=RelationType.ALLY)
    ]
    with pytest.raises(ValueError) as excinfo:
        ledger.validate_work_endpoints()
    message = str(excinfo.value)
    assert "端点校验失败" in message
    assert "t1/e1/participant/未登记者 character_observation.character 未在当前章 登记: 未登记者" in message
    assert "relation/未登记者-李瑜/盟友 relation.from_entity 未在当前章 登记: 未登记者" in message


@pytest.mark.asyncio
async def test_write_duplicate_rejection_names_both_records_in_program_receipt() -> None:
    ledger = _ledger()
    runtime = ProgramRuntime(build_annotation_tools(_QueryService(), ledger), ledger)
    receipt = json.loads(
        await runtime.execute(
            "write_entity(el='a1', name='顾霜', entity_type='character')\n"
            "write_event(el='t1', characters=[{'name': '顾霜', 'entity_type': 'c"
            "haracter', 'action': '喝止'}], title='顾霜喝止', problem='明确事件问题', summ"
            "ary='顾霜喝止', event_type='行动', status='ongoing', evidence=1)\n"
            "write_event(el='t2', characters=[{'name': '顾霜', 'entity_type': 'c"
            "haracter', 'action': '喝止'}], title='众人退下', problem='明确事件问题', summ"
            "ary='众人退下', event_type='行动', status='ongoing', evidence=1)"
        )
    )
    assert receipt["status"] == "partial"
    (failed,) = receipt["failed"]
    assert failed["record"] == "t2/root/participant/顾霜"
    assert failed["code"] == "duplicate_observation"
    assert "t1/root/participant/顾霜(character=顾霜, action=喝止)" in failed["message"]
    assert "t2/root/participant/顾霜(character=顾霜, action=喝止)" in failed["message"]
    assert "相撞" in failed["message"]
    assert "改写" not in failed["expected"]
    assert set(ledger.tree_key_index) == {"t1"}
    assert set(ledger.observation_by_record) == {"t1/root/participant/顾霜"}


@pytest.mark.asyncio
async def test_schema_rejection_names_participant_key_and_submitted_value() -> None:
    ledger = _ledger()
    tools = _tools(ledger)
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _call(
            tools,
            "write_event",
            {
                "el": "t1",
                "characters": [{"name": "顾霜", "entity_type": "character", "emotion": "愤怒"}],
                "title": "顾霜喝止",
                "problem": "明确事件问题",
                "summary": "顾霜喝止",
                "event_type": "行动",
                "status": "ongoing",
                "evidence": 1,
            },
        )
    receipt = excinfo.value.receipt()
    assert receipt["record"] == "t1"
    assert receipt["field"] == "emotion"
    assert "characters.0.emotion='愤怒'" in receipt["message"]
    assert "t1/participant/顾霜" in receipt["message"]
    assert not ledger.tree_key_index


def test_endpoint_type_rejection_names_record_and_field_value() -> None:
    ledger = _ledger()
    tools = _tools(ledger)
    tools["write_entity"].invoke({"el": "a1", "name": "山门", "entity_type": "location"})
    tools["write_entity"].invoke({"el": "a2", "name": "顾霜", "entity_type": "character"})
    with pytest.raises(AnnotationStageRejection) as excinfo:
        tools[("write_relation")].invoke(
            {
                ("from_entity"): {("name"): ("山门"), ("entity_type"): ("location")},
                ("to_entity"): {("name"): ("顾霜"), ("entity_type"): ("character")},
                ("relation_type"): ("盟友"),
            }
        )
    receipt = excinfo.value.receipt()
    assert receipt["record"] == "relation/山门-顾霜/盟友"
    assert "relation/山门-顾霜/盟友(from_entity='山门')" in receipt["message"]
    assert "location" in receipt["message"]
    assert not ledger.written_relations


@pytest.mark.asyncio
async def test_record_combination_rejection_names_actual_field_values() -> None:
    ledger = _ledger()
    tools = _tools(ledger)
    await _call(tools, "write_entity", {"el": "a1", "name": "顾霜", "entity_type": "character"})
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _call(
            tools,
            ("write_dialogue"),
            {
                ("candidate_index"): 1,
                ("verdict"): ("not_dialogue"),
                ("speaker"): {("name"): ("顾霜"), ("entity_type"): ("character")},
            },
        )
    receipt = excinfo.value.receipt()
    assert receipt["record"] == "dialogue/1"
    assert receipt["code"] == "invalid_combination"
    assert receipt["message"].startswith("dialogue/1(")
    assert "verdict='not_dialogue'" in receipt["message"]
    assert "speaker='顾霜'" in receipt["message"]
    assert "tone=None" in receipt["message"]
    assert not ledger.written_dialogues
    repaired = await _call(tools, "write_dialogue", {"candidate_index": 1, "verdict": "not_dialogue"})
    assert repaired["status"] == "written"


async def _link_runtime() -> tuple[AnnotationToolLedger, ProgramRuntime, dict[str, Any]]:
    ledger = _ledger(allow_future_context=True)
    runtime = ProgramRuntime(build_annotation_tools(_QueryService(), ledger), ledger)
    prepared = json.loads(
        await runtime.execute("""
write_entity(el="a1", name="顾霜", entity_type="character")
write_entity(el="a2", name="众人", entity_type="character")
edge = write_relation(
    from_entity={"name": "顾霜", "entity_type": "character"},
    to_entity={"name": "众人", "entity_type": "character"},
    relation_type="盟友",
)
local = read_text(paragraph_id=1)
other = read_text(paragraph_id=20)
anchor_record(record_id=edge["record"], source_ref=local["source_ref"])
""")
    )
    assert prepared["status"] == "applied", prepared
    return (
        ledger,
        runtime,
        {
            "record_id": runtime.env["edge"]["record"],
            "source_ref": runtime.env["local"]["source_ref"],
            "target_ref": runtime.env["other"]["source_ref"],
            "kind": "relation_change",
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reference_name", "code"), [("other", "chapter_mismatch"), ("unread", "unauthorized_reference")]
)
async def test_anchor_rejection_names_record_and_invalid_reference(reference_name: str, code: str) -> None:
    ledger, runtime, _args = await _link_runtime()
    before = ledger.snapshot()
    source_ref = runtime.env["other"]["source_ref"] if reference_name == "other" else "unread"
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _call(runtime.tools, "anchor_record", {"record_id": "entity/顾霜", "source_ref": source_ref})
    receipt = excinfo.value.receipt()
    assert receipt["record"] == "entity/顾霜"
    assert receipt["field"] == "source_ref"
    assert receipt["code"] == code
    assert source_ref in receipt["message"]
    assert ledger.source_anchors == before["dialogue"].source_anchors


@pytest.mark.asyncio
async def test_anchor_schema_rejection_names_record_and_missing_field() -> None:
    _ledger_value, runtime, _args = await _link_runtime()
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _call(runtime.tools, "anchor_record", {"record_id": "entity/顾霜"})
    receipt = excinfo.value.receipt()
    assert receipt["record"] == "entity/顾霜"
    assert receipt["field"] == "source_ref"
    assert "entity/顾霜(source_ref=<未提供>)" in receipt["message"]
