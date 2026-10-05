"""2026-10-04 拒绝回执点名违规记录：收尾期拒绝必须点名相撞记录键与字段值

run 4cb054dc ch12 实证："[3, 7] character_observations 重复语义项"这类只报下标+域名的
拒绝让模型烧 60%+ 思考逆向解读拒绝合同。本文件锁定三类收尾拒绝的点名行为——
判重（相撞各条的生产记录键+字段值）、端点校验（生产记录键替代裸下标）、挂起子事件
（节点键替代数量）。判重与端点校验在写入点校验之后属防御网，用账本白盒种子驱动；
写入期判重、schema 拒绝及跨章关联同时走公开工具与程序面，验证压缩回执仍保留定位事实。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.agents.annotation.errors import AnnotationStageRejection
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import _invoke_tool
from src.agents.annotation.program import ProgramRuntime
from src.agents.annotation.schema import (
    BoundCharacterObservation,
    BoundEvent,
    ChapterParagraphInfo,
    EntityDirectoryInput,
    RelationInput,
    RelationType,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


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
    ledger.observation_by_record["t1/e1/participant/lyr"] = BoundCharacterObservation(
        character="李瑜", action="推门"
    )
    ledger.observation_by_record["t2/e1/participant/李瑜"] = BoundCharacterObservation(
        character="李瑜", action="推门"
    )
    ledger.observation_by_record["t3/e1/participant/顾霜"] = BoundCharacterObservation(
        character="顾霜", action="守门"
    )
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
    ledger.bound_payloads["events"] = [
        BoundEvent(node_id="node-2", tree_id="tree-1", cause_role="main", description="李瑜推门"),
        BoundEvent(node_id="node-2", tree_id="tree-1", cause_role="main", description="李瑜推门"),
    ]
    with pytest.raises(ValueError) as excinfo:
        ledger._validate_domain_duplicates(_duplicate_payloads(ledger))
    message = str(excinfo.value)
    assert "events 重复语义项: t1/e2 与 t1/e2" in message
    assert "node-2" not in message


def test_duplicate_relation_rejection_names_edge_key() -> None:
    """关系判重点名 from-to/类型 边键"""
    ledger = _ledger()
    edge = RelationInput(from_entity="李瑜", to_entity="钱进", relation_type=RelationType.ALLY)
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
    ledger.domain_payloads["entities"] = EntityDirectoryInput(entities=[])
    ledger.domain_payloads["character_observations"] = list(ledger.observation_by_record.values())
    ledger.domain_payloads["dialogues"] = []
    ledger.domain_payloads["relations"] = [
        RelationInput(from_entity="未登记者", to_entity="李瑜", relation_type=RelationType.ALLY)
    ]
    with pytest.raises(ValueError) as excinfo:
        ledger._build_ready_chapter()
    message = str(excinfo.value)
    assert "端点校验失败" in message
    assert "t1/e1/participant/未登记者 character_observation.character 未在当前章 登记: 未登记者" in message
    assert "relation/未登记者-李瑜/盟友 relation.from_entity 未在当前章 登记: 未登记者" in message


@pytest.mark.asyncio
async def test_finish_rejection_names_pending_child_node_keys() -> None:
    """挂起子事件兜底拒绝点名各树挂起的节点键（原 "t1×2" 只有数量）

    finish 工具本身只回 pending 占位，收尾判定由回合末的 ledger.finish_chapter() 执行。
    """
    ledger = _ledger()
    tools = _tools(ledger)
    await _call(
        tools,
        "write_metrics",
        {"summary": "顾霜喝止众人", "emotional_valence": 0, "narrative_function": "冲突"},
    )
    for el in ("t1/e2", "t1/e3"):
        receipt = await _call(
            tools, "write_event", {"el": el, "isroot": False, "type": "main", "description": "李瑜推门"}
        )
        assert receipt.get("status") != "rejected"
    with pytest.raises(AnnotationStageRejection) as excinfo:
        ledger.finish_chapter()
    assert "子事件仍挂起等待建根: t1(e2, e3)" in str(excinfo.value)


@pytest.mark.asyncio
async def test_write_duplicate_rejection_names_both_records_in_program_receipt() -> None:
    ledger = _ledger()
    runtime = ProgramRuntime(build_annotation_tools(_QueryService(), ledger), ledger)
    receipt = json.loads(await runtime.execute('''
write_entity(el="a1", name="顾霜", entity_type="character")
write_event(el="t1", isroot=True, description="顾霜喝止", characters=[{"entityid": "a1", "action": "喝止"}])
write_event(el="t2", isroot=True, description="众人退下", characters=[{"entityid": "a1", "action": "喝止"}])
'''))
    assert receipt["status"] == "partial"
    (failed,) = receipt["failed"]
    assert failed["record"] == "t2/root/participant/a1"
    assert failed["code"] == "duplicate_observation"
    assert "t1/root/participant/a1(character=顾霜, action=喝止)" in failed["message"]
    assert "t2/root/participant/a1(character=顾霜, action=喝止)" in failed["message"]
    assert "相撞" in failed["message"]
    assert "改写" not in failed["expected"]
    assert set(ledger.tree_key_index) == {"t1"}
    assert set(ledger.observation_by_record) == {"t1/root/participant/a1"}


@pytest.mark.asyncio
async def test_schema_rejection_names_participant_key_and_submitted_value() -> None:
    ledger = _ledger()
    tools = _tools(ledger)
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _call(tools, "write_event", {
            "el": "t1", "isroot": True, "description": "顾霜喝止",
            "characters": [{"entityid": "a1", "emotion": "愤怒"}],
        })
    receipt = excinfo.value.receipt()
    assert receipt["record"] == "t1/root"
    assert receipt["field"] == "emotion"
    assert "characters.0.emotion='愤怒'" in receipt["message"]
    assert "t1/root/participant/a1" in receipt["message"]
    assert not ledger.tree_key_index


def test_endpoint_type_rejection_names_record_and_field_value() -> None:
    ledger = _ledger()
    tools = _tools(ledger)
    tools["write_entity"].invoke({"el": "a1", "name": "山门", "entity_type": "location"})
    tools["write_entity"].invoke({"el": "a2", "name": "顾霜", "entity_type": "character"})
    with pytest.raises(AnnotationStageRejection) as excinfo:
        tools["write_relation"].invoke({"from_entity": "a1", "to_entity": "a2", "relation_type": "盟友"})
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
        await _call(tools, "write_dialogue", {"candidate_index": 1, "verdict": "not_dialogue", "speaker": "a1"})
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
    prepared = json.loads(await runtime.execute('''
write_entity(el="a1", name="顾霜", entity_type="character")
write_entity(el="a2", name="众人", entity_type="character")
edge = write_relation(from_entity="a1", to_entity="a2", relation_type="盟友")
local = read_text(paragraph_id=1)
other = read_text(paragraph_id=20)
anchor_record(record_id=edge["record"], source_ref=local["source_ref"])
'''))
    assert prepared["status"] == "applied", prepared
    return ledger, runtime, {
        "record_id": runtime.env["edge"]["record"],
        "source_ref": runtime.env["local"]["source_ref"],
        "target_ref": runtime.env["other"]["source_ref"],
        "kind": "relation_change",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_null", [False, True])
async def test_missing_link_change_kind_names_record_value_and_allows_repair(explicit_null: bool) -> None:
    ledger, runtime, args = await _link_runtime()
    if explicit_null:
        args["change_kind"] = None
    code = "write_link(" + ", ".join(f"{key}={value!r}" for key, value in args.items()) + ")"
    receipt = json.loads(await runtime.execute(code))
    (failed,) = receipt["failed"]
    assert receipt["status"] == "partial"
    assert failed["record"] == "relation/顾霜-众人/盟友"
    assert failed["field"] == "change_kind"
    assert failed["code"] == "missing"
    assert "relation/顾霜-众人/盟友(kind=relation_change, change_kind=None)" in failed["message"]
    assert "reinforce" in failed["expected"]
    assert not ledger.cross_chapter_links
    assert ledger.source_anchors[args["record_id"]]
    args["change_kind"] = "reinforce"
    repaired = json.loads(await runtime.execute(
        "write_link(" + ", ".join(f"{key}={value!r}" for key, value in args.items()) + ")"
    ))
    assert repaired["status"] == "applied", repaired
    assert len(ledger.cross_chapter_links) == 1
    assert ledger.cross_chapter_links[0].change_kind == "reinforce"


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "value", "code"), [
    ("change_kind", "invented", "invalid_value"),
    ("change_kind", "null", "invalid_value"),
    ("kind", "invented", "invalid_value"),
    ("source_ref", "unread-source", "unauthorized_reference"),
    ("target_ref", "unread-target", "unauthorized_reference"),
    ("target_ref", None, "string_type"),
    ("record_id", "relation/不存在-众人/盟友", "unknown_record"),
])
async def test_link_rejection_names_record_and_invalid_field_value(field: str, value: Any, code: str) -> None:
    ledger, runtime, args = await _link_runtime()
    args[field] = value
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _call(runtime.tools, "write_link", args)
    receipt = excinfo.value.receipt()
    assert receipt["record"] == args["record_id"]
    assert receipt["field"] == field
    assert receipt["code"] == code
    assert args["record_id"] in receipt["message"]
    assert repr(value) in receipt["message"]
    assert not ledger.cross_chapter_links


@pytest.mark.asyncio
async def test_link_rejection_names_missing_schema_field_without_echoing_payload() -> None:
    ledger, runtime, args = await _link_runtime()
    del args["target_ref"]
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _call(runtime.tools, "write_link", args)
    receipt = excinfo.value.receipt()
    assert receipt["record"] == args["record_id"]
    assert receipt["field"] == "target_ref"
    assert "target_ref=<未提供>" in receipt["message"]
    assert args["source_ref"] not in receipt["message"]
    assert not ledger.cross_chapter_links


@pytest.mark.asyncio
async def test_link_same_chapter_rejection_names_actual_chapter_values() -> None:
    ledger, runtime, args = await _link_runtime()
    args.update(target_ref=args["source_ref"], change_kind="reinforce")
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _call(runtime.tools, "write_link", args)
    receipt = excinfo.value.receipt()
    assert receipt["record"] == args["record_id"]
    assert receipt["field"] == "target_ref"
    assert "source.chapter_id=1, target.chapter_id=1" in receipt["message"]
    assert not ledger.cross_chapter_links


@pytest.mark.asyncio
async def test_nonrelation_link_change_kind_rejection_names_both_field_values() -> None:
    ledger, runtime, args = await _link_runtime()
    entity_record = "entity/顾霜"
    await _call(runtime.tools, "anchor_record", {"record_id": entity_record, "source_ref": args["source_ref"]})
    args.update(record_id=entity_record, kind="same_entity", change_kind="reinforce")
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _call(runtime.tools, "write_link", args)
    receipt = excinfo.value.receipt()
    assert receipt["record"] == entity_record
    assert receipt["field"] == "change_kind"
    assert "entity/顾霜(kind=same_entity, change_kind=reinforce)" in receipt["message"]
    assert not ledger.cross_chapter_links


@pytest.mark.asyncio
async def test_link_domain_rejection_names_actual_record_and_kind() -> None:
    ledger, runtime, args = await _link_runtime()
    args["record_id"] = "entity/顾霜"
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _call(runtime.tools, "write_link", args)
    receipt = excinfo.value.receipt()
    assert receipt["record"] == "entity/顾霜"
    assert receipt["field"] == "kind"
    assert receipt["code"] == "domain_mismatch"
    assert "entity/顾霜(kind=relation_change)" in receipt["message"]
    assert not ledger.cross_chapter_links


@pytest.mark.asyncio
async def test_foreign_link_source_rejection_names_actual_source_ref() -> None:
    ledger, runtime, args = await _link_runtime()
    args["source_ref"] = args["target_ref"]
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _call(runtime.tools, "write_link", args)
    receipt = excinfo.value.receipt()
    assert receipt["record"] == args["record_id"]
    assert receipt["field"] == "source_ref"
    assert receipt["code"] == "chapter_mismatch"
    assert repr(args["source_ref"]) in receipt["message"]
    assert "source.chapter_id=2" in receipt["message"]
    assert not ledger.cross_chapter_links


@pytest.mark.asyncio
async def test_link_automatically_anchors_authorized_source_and_replay_is_idempotent() -> None:
    ledger, runtime, args = await _link_runtime()
    args.update(record_id="entity/顾霜", kind="same_entity")
    assert args["record_id"] not in ledger.source_anchors
    first = await _call(runtime.tools, "write_link", args)
    replay = await _call(runtime.tools, "write_link", args)
    assert first["accepted"] and replay["accepted"]
    assert ledger.source_anchors[args["record_id"]] == [ledger.text_references[args["source_ref"]]]
    assert len(ledger.cross_chapter_links) == 1


@pytest.mark.asyncio
async def test_rejected_relation_link_does_not_anchor_or_guess_change_direction() -> None:
    ledger, runtime, args = await _link_runtime()
    del ledger.source_anchors[args["record_id"]]
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _call(runtime.tools, "write_link", args)
    assert excinfo.value.field == "change_kind"
    assert not ledger.source_anchors
    assert not ledger.cross_chapter_links


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
    assert ledger.source_anchors == before["source_anchors"]


@pytest.mark.asyncio
async def test_anchor_schema_rejection_names_record_and_missing_field() -> None:
    _ledger_value, runtime, _args = await _link_runtime()
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _call(runtime.tools, "anchor_record", {"record_id": "entity/顾霜"})
    receipt = excinfo.value.receipt()
    assert receipt["record"] == "entity/顾霜"
    assert receipt["field"] == "source_ref"
    assert "entity/顾霜(source_ref=<未提供>)" in receipt["message"]
