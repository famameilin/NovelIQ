"""标注回合降本五修复的合同测试（2026-09-14 写入面重构后的新契约）

背景：run 84866d6f 全程耗时分解显示思考占 83.1%，其中合同解码与绕行规划
约三成；五个修复全部针对"模型可见文本与报错路径"：
- 模型可见文案不得点名已删除或未注册的工具（09-12 起草、09-13 写者面全放开后
  不再有"隐藏工具名"一说：每轮工具面都是全集，注入文本照常点名各领域工具；
  09-14 写入面重构后写者面为五个领域工具 + 唯一 finish_chapter，
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
from typing import Any

import pytest

from src.agents.annotation.errors import AnnotationStageRejection
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import _invoke_tool, _missing_domains_reminder
from src.agents.annotation.prompts import (
    SYSTEM_PROMPT,
    build_case_pool_notice,
    build_chunk_message,
    build_writer_chapter_message,
)
from src.agents.annotation.reader_report import ReaderReport
from src.agents.annotation.schema import (
    CaseSearchResult,
    ChunkParagraphInfo,
    SearchResult,
)
from src.agents.annotation.tools import _DOMAIN_ORDER, AnnotationToolLedger, build_annotation_tools

# 五个领域写入小调用（2026-09-14 写入面重构：根/子/参与者合并进 write_event，
# 句标签并入 write_metrics；首轮起全部在工具面上）
_ALL_WRITE_TOOL_NAMES = (
    "write_entity",
    "write_metrics",
    "write_event",
    "write_relation",
    "write_dialogue",
)


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
    reader_reports: list[ReaderReport] | None = None,
) -> AnnotationToolLedger:
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text=text,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, len(text))],
            texts=[text],
        ),
        reader_reports=reader_reports,
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


# ---------------------------------------------------------------------------
# 修复一：写者面全放开（首轮即五个写入小调用）+ 缺内容提醒列全部缺内容域

def test_writer_surface_exposes_every_write_tool_at_first_turn() -> None:
    """2026-09-14 写者面全放开：首轮工具面就是五个写入小调用 + 唯一收尾 finish_chapter

    09-12 的"隐藏工具名清出注入面"是当时渐进解锁的配套；09-13 用户裁决全放开后
    隐藏集合消失；09-14 写入面重构（九工具→五工具、finish_chunk 更名
    finish_chapter）后，注入文本不得再点名任何已退役的旧工具名，工具面每轮都是全集。
    """
    ledger = _writer_ledger()
    visible_names = [tool.name for tool in _writer_tools(ledger).values()]
    for name in _ALL_WRITE_TOOL_NAMES:
        assert name in visible_names
    assert "finish_chapter" in visible_names

    chunk_message = build_chunk_message(
        chunk_index=1,
        chunk_total=1,
        chunk_text="正文",
        candidates=ledger.dialogue_candidates,
    )
    writer_message = build_writer_chapter_message(
        reader_reports_view="<ReaderReport>…</ReaderReport>",
        candidates=ledger.dialogue_candidates,
    )
    # 注入文本与工具描述不得点名已退役的写入工具（09-14 九工具面与旧收尾名的残留）
    stale_tool_names = (
        "write_sentence_label",
        "write_event_root",
        "write_event_child",
        "write_character_participation",
        "write_noncharacter_participation",
        "finish_chunk",
        "finish_domain",
        "create_event",
    )
    for surface in (SYSTEM_PROMPT, build_case_pool_notice(), chunk_message, writer_message):
        for stale in stale_tool_names:
            assert stale not in surface, f"注入文本引用已退役的工具 {stale}: {surface[:120]}"


def test_missing_domains_reminder_lists_every_missing_domain() -> None:
    """2026-09-14 缺域提醒列出全部缺内容域的补齐工具（不再按解锁面过滤）

    解锁窗口删除后，缺哪个域就报哪个域的工具名：实体未写时一并报出事件/关系/
    对话的写入小调用——它们此刻确实在工具面上（09-14 起事件域只有 write_event 一个入口）。
    """
    text = _missing_domains_reminder(list(_DOMAIN_ORDER))
    assert text is not None
    for name in ("write_entity", "write_metrics", "write_event", "write_relation", "write_dialogue"):
        assert name in text
    assert "finish_chapter" in text


def test_missing_domains_reminder_names_only_missing_domains() -> None:
    """缺域提醒只报缺失域的补齐工具：已写域不出现

    character_observations 随事件域经 write_event 的 characters 一并写入，不在
    missing_content_domains 的内容清单里（缺内容清单只含五域）。
    """
    text = _missing_domains_reminder(["events", "dialogues"])
    assert text is not None
    assert "write_event" in text and "write_dialogue" in text
    assert "write_entity" not in text
    assert "finish_chapter" in text


def test_missing_domains_reminder_falls_back_to_finish_chapter_when_nothing_missing() -> None:
    """无缺口时提醒退化为唯一收尾指引，返回 None 的旧行为已不存在

    finish_chapter 恒定开放：提醒始终给出收尾方式；本轮确实没有内容可写时，
    模型据此直接收尾即可。
    """
    text = _missing_domains_reminder([])
    assert text is not None
    assert "finish_chapter" in text
    assert "write_" not in text


# ---------------------------------------------------------------------------
# 修复二：写入调用校验失败翻成结构化拒绝（旧 write_event 翻译 + patches 链路已删除）


@pytest.mark.asyncio
async def test_child_arguments_exclude_foreshadowing_fields() -> None:
    """伏笔两字段只属于根事件：写到子事件上被整条拒绝，不会静默丢弃

    2026-09-14 写入面合并：根/子同走 write_event，参数面是全集（extra=forbid 不再
    区分根子入口）；子事件带伏笔属性由账本按 not_on_child 整条拒绝，字段名随回执
    回到模型；写入即生效，拒绝的那条不落树（根已写入，节点表只剩 root）。
    """
    ledger = _writer_ledger()
    tools = _writer_tools(ledger)
    assert set(tools["write_event"].args) == {
        "el",
        "isroot",
        "description",
        "isforeshadowing",
        "confidence",
        "type",
        "characters",
    }
    # 09-14 树内先后=调用顺序：序号参数已下线
    assert "order" not in tools["write_event"].args
    assert {"isforeshadowing", "confidence"} <= set(tools["write_event"].args)
    tools["write_entity"].invoke({"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    tools["write_event"].invoke({"el": "t1", "isroot": True, "description": "根事件"})
    receipt = await _write_rejection(
        tools,
        "write_event",
        {
            "el": "t1/e1",
            "isroot": False,
            "type": "main",
            "description": "子事件",
            "isforeshadowing": True,
            "confidence": "high",
        },
    )
    assert receipt["status"] == "rejected"
    assert receipt["record"] == "t1/e1"
    assert receipt["field"] == "isforeshadowing"
    assert receipt["code"] == "not_on_child"
    assert set(_tree(ledger, "t1")["nodes"]) == {"root"}
    assert _tree(ledger, "t1")["isforeshadowing"] is False


@pytest.mark.asyncio
async def test_child_arguments_exclude_nested_children() -> None:
    """子事件不得嵌套 children：write_event 参数面没有 children，嵌套提交被整条拒绝

    2026-09-14 取消暂存后子事件只能逐个 write_event 追加（每次一个节点），
    children 越界由参数面收紧成结构化拒绝，不会落成半个子节点。
    """
    ledger = _writer_ledger()
    tools = _writer_tools(ledger)
    assert "children" not in tools["write_event"].args
    tools["write_event"].invoke({"el": "t1", "isroot": True, "description": "根事件"})
    receipt = await _write_rejection(
        tools,
        "write_event",
        {
            "el": "t1/e1",
            "isroot": False,
            "type": "main",
            "description": "子事件",
            "children": [{"type": "main", "description": "孙事件"}],
        },
    )
    assert receipt["record"] == "t1/e1"
    assert receipt["field"] == "children"
    assert receipt["code"] == "unknown_field"
    assert set(_tree(ledger, "t1")["nodes"]) == {"root"}


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
                    "entityid": 1,
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
    assert "发送者" not in receipt["expected"]
    assert "主体" in receipt["expected"]
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


def test_isforeshadowing_root_missing_fields_keeps_chinese_receipt() -> None:
    """根级跨字段校验仍返回中文规则说明，不带 pydantic 样板

    2026-09-14 写入面收敛：伏笔属性只留 isforeshadowing+confidence，family/likelihood
    两字段退役；等价验证=isforeshadowing=true 缺 confidence 的结构化拒绝
    （field/code 定位缺失项，message 为中文可自纠说明，无文档链接）。
    """
    ledger = _writer_ledger()
    tools = _writer_tools(ledger)

    with pytest.raises(AnnotationStageRejection) as exc_info:
        tools["write_event"].invoke({"el": "t1", "isroot": True, "description": "根事件", "isforeshadowing": True})

    receipt = exc_info.value.receipt()
    assert receipt["record"] == "t1/root"
    assert receipt["field"] == "confidence"
    assert receipt["code"] == "missing"
    assert "必须提供 confidence" in receipt["message"]
    assert "https://" not in receipt["message"]
    assert "value_error" not in receipt["message"]


@pytest.mark.asyncio
async def test_rejection_expected_carries_occupied_record_example() -> None:
    """拒绝回执的 expected 携带可自纠示例（旧 patches 二元数组格式示例的替代）

    2026-09-14 变化点：order 参数随"树内先后=调用顺序"下线，旧 out_of_order 占用
    拒绝没有对应物；同一条"占用→换一个"的语义由 el 键空间承接——el 被另一实体
    占用即 duplicate_el，expected 给出"换一个 el 键"的可自纠指引（record 定位到
    被拒的那条实体记录），模型据此换一个未占用键。
    """
    ledger = _writer_ledger()
    tools = _writer_tools(ledger)
    first = json.loads(tools["write_entity"].invoke({"name": "顾霜", "entity_type": "character", "el": "a1"}))
    assert first == {
        "status": "written",
        "record": "entity/顾霜",
        "el": "a1",
        "n": 1,
        "content": {
            "name": "顾霜",
            "entity_type": "character",
            "tags": [],
            "description": None,
            "attributes": {},
            "n": 1,
        },
    }

    receipt = await _write_rejection(
        tools,
        "write_entity",
        {"name": "褚大山", "entity_type": "character", "el": "a1"},
    )

    assert receipt["record"] == "entity/褚大山"
    assert receipt["field"] == "el"
    assert receipt["code"] == "duplicate_el"
    assert "换一个 el 键" in receipt["expected"]
    assert "https://" not in receipt["expected"]
    assert "type=" not in receipt["expected"]


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
        chunk_id=5,
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
    assert match["n"] == 1
    assert match["alias_linked"] == [{"case_number": 1, "linked": [{"n": 2, "name": "第三铺"}]}]
    assert "alias_note" in response
    # 2026-09-13 文案纠偏：末句必须给两条具体动作，且不得再承诺"系统会自动合并"
    # （旧文案让模型以为什么都不用做 → 案例永挂、每章被反复点名）
    assert "write_relation" in response["alias_note"]
    assert "close_case" in response["alias_note"]
    assert "自动合并" not in response["alias_note"]
    # 展示即授权：案例编号已登记、源章已授权
    assert ledger.case_number_by_id["case-alias-1"] == 1
    assert 5 in ledger.authorized_chapter_ids


@pytest.mark.asyncio
async def test_search_graph_without_alias_hits_has_no_annotation() -> None:
    case = CaseSearchResult(
        id="case-alias-2",
        type="entity_alias",
        chunk_id=5,
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


# ---------------------------------------------------------------------------
# 修复四：两段式写者实体准入放宽为 报告并集 ∪ 图中已登记名 ∪ 章正文逐字命中


@pytest.mark.asyncio
async def test_entity_admission_accepts_literal_chapter_text_hits() -> None:
    """报告并集之外但正文逐字出现的实体名放行（ch26 实测损失面）

    2026-09-14 写入面重构：write_entity 单条登记必填自定 el 键，
    回执为 status=written/record/el/n（写入即生效），准入语义不变。
    """
    text = "峒河在月光下泛起白雾，铜台堡的角楼熄了灯。"
    report = ReaderReport(
        block_index=0,
        report={
            "entities": [
                {
                    "name": "顾霜",
                    "entity_type": "character",
                    "evidence": [{"paragraph_id": 0, "quote": "峒河在月光下泛起白雾"}],
                }
            ]
        },
        warnings=[],
    )
    ledger = _writer_ledger(text=text, reader_reports=[report])
    tools = _writer_tools(ledger)
    await tools["search_graph"].ainvoke({"entities": ["顾霜"]})

    receipt = json.loads(
        await tools["write_entity"].ainvoke({"name": "铜台堡", "entity_type": "location", "el": "铜台堡"})
    )
    assert receipt["status"] == "written"
    assert receipt["record"] == "entity/铜台堡"
    assert receipt["n"] == 1

    with pytest.raises(ValueError) as exc_info:
        await tools["write_entity"].ainvoke({"name": "凭空堡", "entity_type": "location", "el": "凭空堡"})
    assert "凭空堡" in str(exc_info.value)
    assert "本章正文" in str(exc_info.value)


@pytest.mark.asyncio
async def test_entity_admission_unaffected_for_single_block_chapters() -> None:
    """单块章（reader_reports=None）准入不受限，保持既有行为"""
    ledger = _writer_ledger()
    tools = _writer_tools(ledger)
    await tools["search_graph"].ainvoke({"entities": ["侯飞白"]})
    receipt = json.loads(
        await tools["write_entity"].ainvoke({"name": "任意新实体", "entity_type": "character", "el": "任意新实体"})
    )
    assert receipt["status"] == "written"
    assert receipt["record"] == "entity/任意新实体"
    assert receipt["el"] == "任意新实体"
