"""2026-09-14 写入面重构专项合同测试（五工具 + el 双命名空间 + 段落标签 + finish_chapter）

与逐轮/审计类测试互补，这里只测新写入面自身的结构性保证：
- EntityRef（int 编号 ∪ 章内 el 键）在参与者/引用面的同一条解析路径；
- write_event 单工具按调用顺序建树、characters 整节点替换语义；
- 伏笔根 confidence 三档（含 low）落进 payoff_likelihood；
- write_metrics(labels) 的段号归属闸与同段去重；
- finish_chapter 结算（missing_record 硬前提与各域计数）。
"""

from __future__ import annotations

import json

import pytest

from src.agents.annotation.errors import AnnotationStageRejection
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.schema import ChunkParagraphInfo, Confidence
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


class _QueryService:
    """无数据库依赖的新合同查询桩"""

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        del query, hidden_case_ids, case_type, limit, pending_cases
        from src.agents.annotation.schema import SearchResult

        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        del query, range_name, limit
        return []

    def fetch_active_case_details(self, case_id):
        del case_id
        return None


def _ledger(*, paragraph_ids: list[int] | None = None) -> AnnotationToolLedger:
    text = "顾霜喝止众人，刀光渐息。"
    ids = paragraph_ids if paragraph_ids is not None else [0]
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text=text,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=ids,
            char_spans=[(0, len(text))] * len(ids),
            texts=[text] * len(ids),
        ),
    )


def _tools(ledger: AnnotationToolLedger) -> dict:
    return {tool.name: tool for tool in build_annotation_tools(_QueryService(), ledger)}


async def _write_entity(tools: dict, *, name: str, el: str, entity_type: str = "character") -> dict:
    receipt = json.loads(
        await tools["write_entity"].ainvoke({"name": name, "entity_type": entity_type, "el": el})
    )
    assert receipt["status"] == "written"
    return receipt


@pytest.mark.asyncio
async def test_entity_ref_resolves_el_number_and_numeric_string_on_one_channel() -> None:
    """el 键、运行期编号 n、纯数字字符串三种引用形态走同一条解析路径"""
    ledger = _ledger()
    tools = _tools(ledger)
    gushuang = await _write_entity(tools, name="顾霜", el="gushuang")
    chu = await _write_entity(tools, name="褚大山", el="chudashan")

    root = await tools["write_event"].ainvoke(
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [
                {
                    "entityid": "gushuang",
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝止",
                    "emotion": -1,
                },
                {
                    "entityid": chu["n"],
                    "role": "客体",
                    "narrative_role": "反对者",
                    "action": "争执",
                    "emotion": -2,
                },
            ],
        }
    )
    assert json.loads(root)["status"] == "written"

    child = await tools["write_event"].ainvoke(
        {
            "el": "t1/e2",
            "isroot": False,
            "type": "main",
            "description": "顾霜收势",
            "characters": [
                {
                    "entityid": str(gushuang["n"]),
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "收势",
                    "emotion": 0,
                }
            ],
        }
    )
    assert json.loads(child)["status"] == "written"

    bound = {event.node_id: event for event in ledger.bound_payloads["events"]}
    root_event = next(event for event in bound.values() if event.cause_role == "root")
    assert {participant.entity for participant in root_event.participants} == {"顾霜", "褚大山"}
    child_event = next(event for event in bound.values() if event.cause_role == "main")
    assert [participant.entity for participant in child_event.participants] == ["顾霜"]


@pytest.mark.asyncio
async def test_unknown_el_rejected_with_known_keys() -> None:
    """未知 el 键结构化拒绝：列出本 chunk 已知 el，并引导历史实体改用编号 n"""
    tools = _tools(_ledger())
    await _write_entity(tools, name="顾霜", el="gushuang")
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await tools["write_event"].ainvoke(
            {
                "el": "t1",
                "isroot": True,
                "description": "顾霜喝止",
                "characters": [
                    {
                        "entityid": "miejing",
                        "role": "主体",
                        "narrative_role": "主体",
                        "action": "喝止",
                        "emotion": -1,
                    }
                ],
            }
        )
    rejection = excinfo.value
    assert rejection.record == "t1/root/participant/miejing"
    assert rejection.field == "entityid"
    assert rejection.code == "unknown_el"
    assert "gushuang" in str(rejection.expected)


@pytest.mark.asyncio
async def test_duplicate_el_binds_one_to_one_by_rejection() -> None:
    """el 在 chunk 内一对一绑定实体：同键换实体在登记点即拒"""
    tools = _tools(_ledger())
    await _write_entity(tools, name="顾霜", el="a")
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await _write_entity(tools, name="褚大山", el="a")
    assert excinfo.value.code == "duplicate_el"
    assert excinfo.value.field == "el"


@pytest.mark.asyncio
async def test_event_tree_order_is_call_order_and_children_attach_to_trunk_tail() -> None:
    """树内先后=调用顺序：main 顺延主链，secondary 挂当时主链尾；无 order 参数"""
    ledger = _ledger()
    tools = _tools(ledger)
    await _write_entity(tools, name="顾霜", el="gushuang")
    for call in (
        {"el": "t1", "isroot": True, "description": "顾霜喝止众人"},
        {"el": "t1/e2", "isroot": False, "type": "main", "description": "顾霜逼近"},
        {"el": "t1/e3", "isroot": False, "type": "secondary", "description": "旁人劝阻"},
    ):
        assert json.loads(await tools["write_event"].ainvoke(call))["status"] == "written"

    tree = next(iter(ledger.event_trees.values()))
    assert set(tree["nodes"]) == {"root", "e2", "e3"}
    bound = {event.node_id: event for event in ledger.bound_payloads["events"]}
    root_id = tree["nodes"]["root"]
    assert bound[root_id].cause_role == "root"
    assert bound[root_id].parent_node_id is None
    # main 顺延：e2 挂根；secondary 挂当时主链尾（即 e2）
    assert bound[tree["nodes"]["e2"]].parent_node_id == root_id
    assert bound[tree["nodes"]["e2"]].cause_role == "main"
    assert bound[tree["nodes"]["e3"]].parent_node_id == tree["nodes"]["e2"]
    assert bound[tree["nodes"]["e3"]].cause_role == "secondary"
    # 链尾已被 main 推进到 e2（secondary 不推进）
    assert tree["trunk_tail"] == tree["nodes"]["e2"]


@pytest.mark.asyncio
async def test_characters_full_replacement_clears_stale_observations() -> None:
    """characters 给出即整节点替换：被删人物的动态状态同点清除"""
    ledger = _ledger()
    tools = _tools(ledger)
    gushuang = await _write_entity(tools, name="顾霜", el="gushuang")
    await _write_entity(tools, name="褚大山", el="chudashan")
    await tools["write_event"].ainvoke(
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [
                {
                    "entityid": "gushuang",
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝止",
                    "emotion": -1,
                },
                {
                    "entityid": "chudashan",
                    "role": "客体",
                    "narrative_role": "反对者",
                    "action": "争执",
                    "emotion": -2,
                },
            ],
        }
    )
    assert len(ledger.observation_by_record) == 2
    await tools["write_event"].ainvoke(
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [
                {
                    "entityid": gushuang["n"],
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝止",
                    "emotion": -1,
                }
            ],
        }
    )
    root_event = next(event for event in ledger.bound_payloads["events"] if event.cause_role == "root")
    assert [participant.entity for participant in root_event.participants] == ["顾霜"]
    assert list(ledger.observation_by_record) == ["t1/root/participant/1"]
    assert ledger.domain_payloads["character_observations"] == [
        ledger.observation_by_record["t1/root/participant/1"]
    ]


@pytest.mark.asyncio
async def test_foreshadow_root_low_confidence_written_as_payoff_likelihood() -> None:
    """伏笔根 confidence=low 直接落 payoff_likelihood；缺 confidence 在根上拒绝"""
    ledger = _ledger()
    tools = _tools(ledger)
    await _write_entity(tools, name="顾霜", el="gushuang")
    assert json.loads(
        await tools["write_event"].ainvoke(
            {
                "el": "t1",
                "isroot": True,
                "description": "顾霜立誓复仇",
                "isforeshadowing": True,
                "confidence": "low",
            }
        )
    )["status"] == "written"
    root_event = next(event for event in ledger.bound_payloads["events"] if event.cause_role == "root")
    assert root_event.is_foreshadow_setup is True
    # StrictModel use_enum_values：载荷里按值存（Confidence 是 StrEnum，按值相等）
    assert root_event.payoff_likelihood == Confidence.LOW
    tree = next(iter(ledger.event_trees.values()))
    assert tree["isforeshadowing"] is True

    with pytest.raises(AnnotationStageRejection) as excinfo:
        await tools["write_event"].ainvoke(
            {"el": "t9", "isroot": True, "description": "残缺令牌", "isforeshadowing": True}
        )
    assert excinfo.value.record == "t9/root"
    assert excinfo.value.field == "confidence"
    assert excinfo.value.code == "missing"

    with pytest.raises(AnnotationStageRejection) as excinfo:
        await tools["write_event"].ainvoke(
            {
                "el": "t1/e2",
                "isroot": False,
                "type": "main",
                "description": "顾霜离去",
                "confidence": "high",
            }
        )
    assert excinfo.value.code == "not_on_child"


@pytest.mark.asyncio
async def test_paragraph_labels_membership_gate_and_same_paragraph_dedupe() -> None:
    """labels 段号必须属于本 chunk；同段号重复提交后到覆盖（载荷一条）"""
    ledger = _ledger(paragraph_ids=[0, 1, 2])
    tools = _tools(ledger)
    base = {"summary": "测试章", "emotional_valence": 0, "narrative_function": "铺垫"}
    with pytest.raises(AnnotationStageRejection) as excinfo:
        await tools["write_metrics"].ainvoke(
            {**base, "labels": [{"paragraph_id": 0, "emotion": 2}, {"paragraph_id": 5, "emotion": -1}]}
        )
    assert excinfo.value.record == "metrics"
    assert excinfo.value.field == "paragraph_id"
    assert excinfo.value.code == "out_of_range"
    assert "0, 1, 2" in str(excinfo.value.expected)

    assert json.loads(
        await tools["write_metrics"].ainvoke(
            {**base, "labels": [{"paragraph_id": 0, "emotion": 2}, {"paragraph_id": 0, "emotion": -1}]}
        )
    )["status"] == "written"
    assert [(label.paragraph_id, label.emotion) for label in ledger.bound_payloads["paragraph_labels"]] == [(0, -1)]


@pytest.mark.asyncio
async def test_finish_chapter_settlement_requires_metrics_then_reports_counts() -> None:
    """finish_chapter 无参数：唯一硬前提是指标已提交；完成回执按域计数"""
    ledger = _ledger()
    tools = _tools(ledger)
    with pytest.raises(AnnotationStageRejection) as excinfo:
        ledger.finish_chapter()
    assert excinfo.value.record == "finish_chapter"
    assert excinfo.value.code == "missing_record"

    await _write_entity(tools, name="顾霜", el="gushuang")
    await tools["write_metrics"].ainvoke(
        {
            "summary": "顾霜喝止众人",
            "emotional_valence": -1,
            "narrative_function": "冲突",
            "labels": [{"paragraph_id": 0, "emotion": -1}],
        }
    )
    await tools["write_event"].ainvoke({"el": "t1", "isroot": True, "description": "顾霜喝止众人"})
    assert json.loads(await tools["finish_chapter"].ainvoke({}))["status"] == "pending"
    receipt = ledger.finish_chapter()
    assert ledger.chapter_finished is True
    assert receipt["status"] == "completed"
    assert receipt["records"]["entities"] == 1
    assert receipt["records"]["events"] == 1
    assert receipt["records"]["paragraph_labels"] == 1
