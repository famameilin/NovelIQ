"""章级声明写入合同：姓名引用、局部寻址、参与者替换、伏笔与段落校验"""

from __future__ import annotations

import json

import pytest

from src.agents.annotation.errors import AnnotationStageRejection
from src.agents.annotation.ledger import AnnotationToolLedger
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import ChapterParagraphInfo
from src.fact_graph.vocabulary import Confidence
from tests.support.annotation_work_tools import build_annotation_tools


class _QueryService:
    """无数据库依赖的新合同查询桩"""

    async def search_text(self, query, *, range_name, limit=50):
        del query, range_name, limit
        return []


def _ledger(*, paragraph_ids: list[int] | None = None) -> AnnotationToolLedger:
    text = "顾霜喝止众人，刀光渐息。"
    ids = paragraph_ids if paragraph_ids is not None else [0]
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chapter_text=text,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChapterParagraphInfo(
            paragraph_ids=ids,
            char_spans=[(0, len(text))] * len(ids),
            texts=[text] * len(ids),
        ),
    )


def _tools(ledger: AnnotationToolLedger) -> dict:
    return {tool.name: tool for tool in build_annotation_tools(_QueryService(), ledger)}


async def _write_entity(tools: dict, *, name: str, el: str, entity_type: str = "character") -> dict:
    receipt = json.loads(await tools["write_entity"].ainvoke({"name": name, "entity_type": entity_type, "el": el}))
    assert receipt["status"] == "written"
    return receipt


@pytest.mark.asyncio
async def test_participants_use_names_and_types_for_independent_declarations() -> None:
    """参与者以正文名字和类型自动登记，局部路径不形成正式包含"""
    ledger = _ledger()
    tools = _tools(ledger)
    await _write_entity(tools, name="顾霜", el="gushuang")
    await _write_entity(tools, name="褚大山", el="chudashan")

    root = await tools["write_event"].ainvoke(
        {
            "el": "t1",
            "characters": [
                {
                    "name": "顾霜",
                    "entity_type": "character",
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝止",
                    "emotion": -1,
                },
                {
                    "name": "褚大山",
                    "entity_type": "character",
                    "role": "客体",
                    "narrative_role": "反对者",
                    "action": "争执",
                    "emotion": -2,
                },
            ],
            "title": "顾霜喝止众人",
            "problem": "行动目标",
            "summary": "顾霜喝止众人",
            "event_type": "行动",
            "status": "ongoing",
            "evidence": 1,
        }
    )
    assert json.loads(root)["status"] == "written"

    child = await tools["write_event"].ainvoke(
        {
            "el": "t1/e2",
            "characters": [
                {
                    "name": "顾霜",
                    "entity_type": "character",
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "收势",
                    "emotion": 0,
                }
            ],
            "title": "顾霜收势",
            "problem": "行动目标",
            "summary": "顾霜收势",
            "event_type": "行动",
            "status": "ongoing",
            "evidence": 1,
        }
    )
    assert json.loads(child)["status"] == "written"

    bound = {event.node_id: event for event in ledger.bound_payloads["events"]}
    root_event = next(event for event in bound.values() if event.title == "顾霜喝止众人")
    assert {ledger.graph.display_name(participant.entity) for participant in root_event.participants} == {
        "顾霜",
        "褚大山",
    }
    child_event = next(event for event in bound.values() if event.title == "顾霜收势")
    assert [ledger.graph.display_name(participant.entity) for participant in child_event.participants] == ["顾霜"]


@pytest.mark.asyncio
async def test_old_id_reference_is_rejected() -> None:
    from pydantic import ValidationError

    tools = _tools(_ledger())
    with pytest.raises(ValidationError):
        await tools["write_event"].ainvoke(
            {
                "el": "t1",
                "characters": [{"entityid": "gushuang", "role": "主体"}],
                "title": "顾霜喝止",
                "problem": "行动目标",
                "summary": "顾霜喝止",
                "event_type": "行动",
                "status": "ongoing",
                "evidence": 1,
            }
        )


@pytest.mark.asyncio
async def test_duplicate_el_binds_one_to_one_by_rejection() -> None:
    """el 在章内一对一绑定实体：同键换实体在登记点即拒"""
    tools = _tools(_ledger())
    await _write_entity(tools, name="顾霜", el="a")
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _write_entity(tools, name="褚大山", el="a")
    assert excinfo.value.code == "duplicate_el"
    assert excinfo.value.field == "el"


@pytest.mark.asyncio
async def test_event_declarations_do_not_infer_containment_from_call_order() -> None:
    """同一局部路径可以先子后根创建，每项声明仍保持独立来源"""
    ledger = _ledger()
    tools = _tools(ledger)
    for el, summary in (("t1/e2", "顾霜逼近"), ("t1", "顾霜喝止众人"), ("t1/e3", "旁人劝阻")):
        call = {
            "el": el,
            "title": summary,
            "problem": "劝阻是否奏效",
            "summary": summary,
            "event_type": "冲突",
            "status": "ongoing",
            "evidence": 1,
        }
        assert json.loads(await tools["write_event"].ainvoke(call))["status"] == "written"
    declarations = ledger.bound_payloads["events"]
    assert len(declarations) == 3
    assert len({event.declaration_id for event in declarations}) == 3
    assert all(event.parent_node_id is None for event in declarations)
    assert ledger.events.contribution_payloads()["relations"] == {}


@pytest.mark.asyncio
async def test_characters_full_replacement_clears_stale_observations() -> None:
    """characters 给出即整节点替换：被删人物的动态状态同点清除"""
    ledger = _ledger()
    tools = _tools(ledger)
    await _write_entity(tools, name="顾霜", el="gushuang")
    await _write_entity(tools, name="褚大山", el="chudashan")
    await tools["write_event"].ainvoke(
        {
            "el": "t1",
            "characters": [
                {
                    "name": "顾霜",
                    "entity_type": "character",
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝止",
                    "emotion": -1,
                },
                {
                    "name": "褚大山",
                    "entity_type": "character",
                    "role": "客体",
                    "narrative_role": "反对者",
                    "action": "争执",
                    "emotion": -2,
                },
            ],
            "title": "顾霜喝止众人",
            "problem": "行动目标",
            "summary": "顾霜喝止众人",
            "event_type": "行动",
            "status": "ongoing",
            "evidence": 1,
        }
    )
    assert len(ledger.observation_by_record) == 2
    await tools["write_event"].ainvoke(
        {
            "el": "t1",
            "characters": [
                {
                    "name": "顾霜",
                    "entity_type": "character",
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝止",
                    "emotion": -1,
                }
            ],
            "title": "顾霜喝止众人",
            "problem": "行动目标",
            "summary": "顾霜喝止众人",
            "event_type": "行动",
            "status": "ongoing",
            "evidence": 1,
        }
    )
    root_event = next(event for event in ledger.bound_payloads["events"] if event.cause_role == "root")
    assert [ledger.graph.display_name(participant.entity) for participant in root_event.participants] == ["顾霜"]
    # 参与者记录键按模型提交的引用原样构造（2026-09-19：uuid id 引用即进键）
    uuid_record = "t1/root/participant/顾霜"
    assert list(ledger.observation_by_record) == [uuid_record]
    assert ledger.domain_payloads["character_observations"] == [ledger.observation_by_record[uuid_record]]


@pytest.mark.asyncio
async def test_foreshadow_root_low_confidence_written_as_payoff_likelihood() -> None:
    """伏笔根 confidence=low 直接落 payoff_likelihood；缺 confidence 在根上拒绝"""
    ledger = _ledger()
    tools = _tools(ledger)
    await _write_entity(tools, name="顾霜", el="gushuang")
    assert (
        json.loads(
            await tools["write_event"].ainvoke(
                {
                    "el": "t1",
                    "isforeshadowing": True,
                    "confidence": "low",
                    "title": "顾霜立誓复仇",
                    "problem": "行动目标",
                    "summary": "顾霜立誓复仇",
                    "event_type": "行动",
                    "status": "ongoing",
                    "evidence": 1,
                }
            )
        )["status"]
        == "written"
    )
    root_event = next(event for event in ledger.bound_payloads["events"] if event.cause_role == "root")
    assert root_event.is_foreshadow_setup is True
    # StrictModel use_enum_values：载荷里按值存（Confidence 是 StrEnum，按值相等）
    assert root_event.payoff_likelihood == Confidence.LOW
    tree = next(iter(ledger.event_trees.values()))
    assert tree["isforeshadowing"] is True

    with pytest.raises(AnnotationStageRejection) as excinfo:
        await tools["write_event"].ainvoke(
            {
                "el": "t9",
                "isforeshadowing": True,
                "title": "残缺令牌",
                "problem": "行动目标",
                "summary": "残缺令牌",
                "event_type": "行动",
                "status": "ongoing",
                "evidence": 1,
            }
        )
    assert excinfo.value.record == "t9/root"
    assert excinfo.value.field == "confidence"
    assert excinfo.value.code == "missing"

    receipt = json.loads(
        await tools["write_event"].ainvoke(
            {
                "el": "t1/e2",
                "isforeshadowing": True,
                "confidence": "high",
                "title": "顾霜离去",
                "problem": "行动目标",
                "summary": "顾霜离去",
                "event_type": "行动",
                "status": "ongoing",
                "evidence": 1,
            }
        )
    )
    assert receipt["status"] == "written"
    child = next(item for item in ledger.bound_payloads["events"] if item.description == "顾霜离去")
    assert child.is_foreshadow_setup and child.payoff_likelihood == "high"


@pytest.mark.asyncio
async def test_paragraph_labels_membership_gate_and_same_paragraph_dedupe() -> None:
    """labels 段号必须属于本章；同段号重复提交后到覆盖（载荷一条）"""
    ledger = _ledger(paragraph_ids=[0, 1, 2])
    tools = _tools(ledger)
    base = {"summary": "测试章", "emotional_valence": 0, "narrative_function": "铺垫"}
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await tools["write_metrics"].ainvoke(
            {**base, "labels": [{"paragraph_id": 1, "emotion": 2}, {"paragraph_id": 5, "emotion": -1}]}
        )
    assert excinfo.value.record == "metrics"
    assert excinfo.value.field == "paragraph_id"
    assert excinfo.value.code == "out_of_range"
    assert "1, 2, 3" in str(excinfo.value.expected)

    assert (
        json.loads(
            await tools["write_metrics"].ainvoke(
                {**base, "labels": [{"paragraph_id": 1, "emotion": 2}, {"paragraph_id": 1, "emotion": -1}]}
            )
        )["status"]
        == "written"
    )
    assert [(label.paragraph_id, label.emotion) for label in ledger.bound_payloads["paragraph_labels"]] == [(0, -1)]
