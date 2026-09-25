"""标注回合降本五修复的合同测试（2026-09-14 写入面重构后的新契约）

背景：run 84866d6f 全程耗时分解显示思考占 83.1%，其中合同解码与绕行规划
约三成；五个修复全部针对"模型可见文本与报错路径"：
- 模型可见文案不得点名已删除或未注册的工具（09-12 起草、09-13 写者面全放开后
  不再有"隐藏工具名"一说：每轮工具面都是全集，注入文本照常点名各领域工具；
  09-14 写入面重构后写者面为五个领域工具 + 唯一 finish，
  注入文本点名旧九工具/旧收尾名的残留同样违约）；
- 写入小调用参数校验失败翻译成结构化拒绝（record/field/code/expected），
  旧 write_event 整树翻译与草稿 patches 链路已删除；09-14 根/子/参与者合并为
  write_event（el 层级键挂树、无 order），句标签收编进 write_metrics.labels；
- search_graph 回执标注未决实体别名案例的关联节点；
- 两段式写者实体准入=报告并集 ∪ 图中已登记名 ∪ 章正文逐字命中；
- 读者面 candidate_index 明确为块内 1 基编号（读者面测试见
  test_annotation_reader.py）。
"""

from __future__ import annotations

import json
import unicodedata
from typing import Any
from uuid import NAMESPACE_DNS, uuid5

import pytest

from src.agents.annotation.errors import AnnotationStageRejection
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import _invoke_tool
from src.agents.annotation.schema import (
    CaseSearchResult,
    ChapterParagraphInfo,
    SearchResult,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


class _QueryServiceStub:
    """2026-09-12 用于无数据库依赖的空查询桩"""

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        del query, hidden_case_ids, case_type, limit
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        del query, range_name, limit
        return []

    def fetch_active_case_details(self, case_id):
        del case_id
        return None


class _AliasCaseQueryService(_QueryServiceStub):
    """2026-09-12 用于返回固定 entity_alias 案例的查询桩"""

    def __init__(self, cases: list[CaseSearchResult]) -> None:
        self.cases = cases

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        del query, limit
        if case_type == "entity_alias":
            return SearchResult(results=[case for case in self.cases if case.id not in hidden_case_ids])
        return SearchResult()


def _writer_ledger(
    *,
    text: str = "“住手”回荡",
) -> AnnotationToolLedger:
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chapter_text=text,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChapterParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, len(text))],
            texts=[text],
        ),
    )


def _writer_tools(ledger: AnnotationToolLedger, query_service: Any = None) -> dict[str, Any]:
    return {
        tool.name: tool
        for tool in build_annotation_tools(query_service or _QueryServiceStub(), ledger)
    }


def _write_call(name: str, args: dict, *, call_id: str) -> dict:
    """2026-09-13 用于构造经 graph._invoke_tool 的生产调用（含 schema 层失败翻译）"""
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


async def _write_rejection(tools: dict[str, Any], name: str, args: dict) -> dict[str, Any]:
    """2026-09-13 用于取得单条记录的结构化拒绝回执（record/field/code/expected）"""
    with pytest.raises(AnnotationStageRejection) as exc_info:
        await _invoke_tool(tools, _write_call(name, args, call_id="call-rejected"))
    return exc_info.value.receipt()


def _tree(ledger: AnnotationToolLedger, tree_key: str) -> dict[str, Any]:
    """2026-09-13 用于按章内局部键取已落账事件树（真实 uuid 只在账本内部）"""
    return ledger.event_trees[ledger.tree_key_index[tree_key]]


def _entity_id(name: str) -> str:
    """2026-09-19 用于按 FactGraph 同款算法铸造实体 run 级 uuid（uuid5(run_scope+归一化名)）

    本文件的 FactGraph() 用默认 run_scope=""（uuid 命名空间键 = "novel-annotation-entity::名"）。
    """
    key = unicodedata.normalize("NFC", name).strip().casefold()
    return str(uuid5(NAMESPACE_DNS, f"novel-annotation-entity::{key}"))


# ---------------------------------------------------------------------------
# 修复二：写入调用校验失败翻成结构化拒绝（旧 write_event 翻译 + patches 链路已删除）


@pytest.mark.asyncio
async def test_participation_role_rejects_narrative_role_word() -> None:
    """role 与 narrative_role 是两套词表：人物功能词不得写进参与角色

    2026-09-14：参与条目并入 write_event 的 characters 数组；非法枚举值由 schema 层
    收紧成结构化拒绝，给出定位（record=t1/root, field=role, code=invalid_value）与
    合法取值清单；被拒的整条不落账（根已写入，参与者仍为空）。
    """
    ledger = _writer_ledger()
    tools = _writer_tools(ledger)
    tools["write_entity"].invoke({"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    tools["write_event"].invoke({"el": "t1", "isroot": True, "description": "根事件"})

    receipt = await _write_rejection(
        tools,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "根事件",
            "characters": [
                {
                    "entityid": "顾霜",
                    "role": "发送者",
                    "narrative_role": "主体",
                    "action": "喝止",
                    "emotion": -1,
                }
            ],
        },
    )

    assert receipt["record"] == "t1/root"
    assert receipt["field"] == "role"
    assert receipt["code"] == "invalid_value"
    assert "https://" not in receipt["message"]
    # 被拒的整条不落账：根节点保留、参与者未被写入
    tree = _tree(ledger, "t1")
    assert set(tree["nodes"]) == {"root"}
    root_event = next(event for event in ledger.bound_payloads["events"] if event.node_id == tree["root_node_id"])
    assert root_event.participants == []


@pytest.mark.asyncio
async def test_missing_child_type_receipt_points_at_record_field() -> None:
    """缺 type 的子事件调用返回带记录键与字段名的结构化拒绝（旧 children.0.type 断言替代）"""
    ledger = _writer_ledger()
    tools = _writer_tools(ledger)
    tools["write_event"].invoke({"el": "t1", "isroot": True, "description": "根事件"})

    receipt = await _write_rejection(
        tools,
        "write_event",
        {"el": "t1/e1", "isroot": False, "description": "子事件"},
    )

    assert receipt["record"] == "t1/e1"
    assert receipt["field"] == "type"
    assert receipt["code"] == "missing"
    assert '"main"' in receipt["expected"] and '"secondary"' in receipt["expected"]
    assert set(_tree(ledger, "t1")["nodes"]) == {"root"}


@pytest.mark.asyncio
async def test_write_tool_schema_layer_failure_translated_via_invoke_tool() -> None:
    """langchain 工具 schema 层的 pydantic 失败（先于函数体）同样翻成结构化拒绝

    2026-09-13：翻译汇点从 translate_event_validation_error 改为
    translate_write_validation_error（record 由原始参数拼装），不再抛裸 ValidationError。
    """
    ledger = _writer_ledger()
    tools = _writer_tools(ledger)
    call = _write_call(
        "write_event",
        {"el": "t1/e1", "description": "子事件"},
        call_id="call-1",
    )

    with pytest.raises(AnnotationStageRejection) as exc_info:
        await _invoke_tool(tools, call)

    receipt = exc_info.value.receipt()
    assert "write_event" in str(exc_info.value)
    assert receipt["record"] == "t1/e1"
    assert receipt["field"] == "isroot"
    assert receipt["code"] == "missing"
    assert "https://" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_failed_record_keeps_prior_written_records_repairable() -> None:
    """草稿缓存 + patches 链路删除（2026-09-13 取消暂存）；等价验证：

    单条记录失败只回滚该调用，先前已写入的记录保留（旧 pending_event_draft
    回写语义没有对应物）；重交该记录即修复，写入即生效。
    """
    ledger = _writer_ledger()
    tools = _writer_tools(ledger)
    tools["write_entity"].invoke({"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    tools["write_event"].invoke({"el": "t1", "isroot": True, "description": "根事件"})

    with pytest.raises(AnnotationStageRejection):
        await _invoke_tool(
            tools,
            _write_call(
                "write_event",
                {"el": "t1/e1", "isroot": False, "type": "invalid", "description": "子事件"},
                call_id="call-2",
            ),
        )

    tree = _tree(ledger, "t1")
    root_event = next(
        event for event in ledger.bound_payloads["events"] if event.node_id == tree["root_node_id"]
    )
    assert root_event.description == "根事件"
    assert set(tree["nodes"]) == {"root"}

    tools["write_event"].invoke({"el": "t1/e1", "isroot": False, "type": "main", "description": "子事件"})
    assert set(_tree(ledger, "t1")["nodes"]) == {"root", "e1"}


# ---------------------------------------------------------------------------
# 修复三：search_graph 回执标注未决别名案例的关联节点


@pytest.mark.asyncio
async def test_search_graph_annotates_alias_linked_nodes() -> None:
    case = CaseSearchResult(
        id="case-alias-1",
        type="entity_alias",
        chapter_id=5,
        created_chapter=3,
        keys=["蓟州驿道", "第三铺"],
        description="蓟州驿道与第三铺疑为同一地点",
    )
    ledger = _writer_ledger()
    tools = _writer_tools(ledger, _AliasCaseQueryService([case]))
    # 先查图（写者习惯路径），再逐个登记两个别名实体（2026-09-14：el 键当场绑定）
    await tools["search_graph"].ainvoke({"entities": ["蓟州驿道"]})
    await tools["write_entity"].ainvoke({"name": "蓟州驿道", "entity_type": "location", "el": "蓟州驿道"})
    await tools["write_entity"].ainvoke({"name": "第三铺", "entity_type": "location", "el": "第三铺"})

    response = json.loads(await tools["search_graph"].ainvoke({"entities": ["蓟州驿道"]}))
    match = response["matches"][0]
    # 2026-09-19 id 纪律：图视图与关联标注全部带 run 级 uuid id（编号 n/case_number 已删）
    assert match["id"] == _entity_id("蓟州驿道")
    assert match["alias_linked"] == [
        {"case_id": "case-alias-1", "linked": [{"id": _entity_id("第三铺"), "name": "第三铺"}]}
    ]
    assert "alias_note" in response
    # 2026-09-13 文案纠偏：末句必须给两条具体动作（案例 id 见 case_id / close_case 关掉该 id），
    # 且不得再承诺"系统会自动合并"（旧文案让模型以为什么都不用做 → 案例永挂、每章被反复点名）
    assert "write_relation" in response["alias_note"]
    # 展示即授权：案例 id 已登记进授权面、源章已授权
    assert "case-alias-1" in ledger.known_case_ids
    assert 5 in ledger.authorized_chapter_ids


@pytest.mark.asyncio
async def test_search_graph_without_alias_hits_has_no_annotation() -> None:
    case = CaseSearchResult(
        id="case-alias-2",
        type="entity_alias",
        chapter_id=5,
        created_chapter=3,
        keys=["蓟州驿道", "第三铺"],
        description="蓟州驿道与第三铺疑为同一地点",
    )
    ledger = _writer_ledger()
    tools = _writer_tools(ledger, _AliasCaseQueryService([case]))
    await tools["search_graph"].ainvoke({"entities": ["蓟州驿道"]})
    await tools["write_entity"].ainvoke({"name": "蓟州驿道", "entity_type": "location", "el": "蓟州驿道"})
    await tools["write_entity"].ainvoke({"name": "第三铺", "entity_type": "location", "el": "第三铺"})

    response = json.loads(await tools["search_graph"].ainvoke({"entities": ["侯飞白"]}))
    assert response["matches"] == []
    assert "alias_note" not in response
