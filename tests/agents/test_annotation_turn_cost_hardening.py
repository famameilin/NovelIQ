"""标注回合降本五修复的合同测试（2026-09-12 方案落地）

背景：run 84866d6f 全程耗时分解显示思考占 83.1%，其中合同解码与绕行规划
约三成；五个修复全部针对"模型可见文本与报错路径"：
- 隐藏工具名不得出现在未解锁时刻的任何注入文本（09-12 裁决：工具相关内容
  只在工具暴露时进入上下文）；
- write_event 参数校验失败翻译成中文规则报错（草稿缓存与 patches 提示由
  工具批次层统一追加）；
- search_graph 回执标注未决实体别名案例的关联节点；
- 两段式写者实体准入放宽为 报告并集 ∪ 图中已登记名 ∪ 章正文逐字命中；
- 读者面 candidate_index 明确为块内 1 基编号（读者面测试见
  test_annotation_reader.py）。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from src.agents.annotation.errors import AnnotationInputError
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import _invoke_tool, _missing_domains_reminder, _tools_for_turn
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
    WriteEventArg,
    WriteEventPatchArgs,
)
from src.agents.annotation.tools import (
    AnnotationToolLedger,
    build_annotation_tools,
    translate_event_validation_error,
)

# 实体回执之前锁定的三个正式写入工具：解锁前任何注入文本都不得出现其名字
_HIDDEN_PRE_UNLOCK_TOOL_NAMES = ("write_event", "write_relations", "write_dialogues")


class _QueryServiceStub:
    """2026-09-12 用于无数据库依赖的空查询桩"""

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50):
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

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50):
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


# ---------------------------------------------------------------------------
# 修复一：隐藏工具名清出常驻文本 + 缺域提醒只列已解锁域


def test_pre_unlock_surfaces_do_not_leak_hidden_tool_names() -> None:
    """解锁前可见的工具描述、参数 schema 与全部注入消息不得出现隐藏写入工具名"""
    ledger = _writer_ledger()
    visible_tools = _tools_for_turn(list(_writer_tools(ledger).values()), ledger)
    visible_names = [tool.name for tool in visible_tools]
    assert "write_entities" in visible_names and "write_metrics" in visible_names
    for banned in _HIDDEN_PRE_UNLOCK_TOOL_NAMES:
        assert banned not in visible_names
    for tool in visible_tools:
        surface = (tool.description or "") + json.dumps(tool.args, ensure_ascii=False, default=str)
        for banned in _HIDDEN_PRE_UNLOCK_TOOL_NAMES:
            assert banned not in surface, f"工具 {tool.name} 的可见文本越界引用 {banned}"
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
    for surface in (SYSTEM_PROMPT, build_case_pool_notice(), chunk_message, writer_message):
        for banned in _HIDDEN_PRE_UNLOCK_TOOL_NAMES:
            assert banned not in surface, f"注入文本越界引用 {banned}: {surface[:120]}"


def test_missing_domains_reminder_only_lists_unlocked_domains() -> None:
    """缺域提醒只提补齐工具已解锁的域：entities 未写时不得报 events/dialogues 的工具名"""
    text = _missing_domains_reminder(
        ["entities", "metrics", "events", "character_observations", "relations", "dialogues"],
        unlocked_domains=frozenset({"entities", "metrics"}),
    )
    assert text is not None
    assert "write_entities" in text and "write_metrics" in text
    for banned in _HIDDEN_PRE_UNLOCK_TOOL_NAMES:
        assert banned not in text


def test_missing_domains_reminder_lists_all_domains_after_entities_receipt() -> None:
    unlocked = frozenset({"entities", "metrics", "events", "character_observations", "relations", "dialogues"})
    text = _missing_domains_reminder(["events", "character_observations", "dialogues"], unlocked_domains=unlocked)
    assert text is not None
    assert "write_event" in text and "write_dialogues" in text


def test_missing_domains_reminder_returns_none_when_unlocked_domains_absent() -> None:
    assert _missing_domains_reminder(["dialogues"], unlocked_domains=frozenset()) is None


# ---------------------------------------------------------------------------
# 修复二：write_event 校验失败翻译成中文规则报错


def _translated_write_event_error(args: dict[str, Any]) -> str:
    try:
        WriteEventArg.model_validate(args)
    except ValidationError as exc:
        return str(translate_event_validation_error(exc))
    raise AssertionError("预期 write_event 参数校验失败")


def test_translate_foreshadowing_fields_on_children() -> None:
    text = _translated_write_event_error(
        {
            "description": "根事件",
            "finalize_events": False,
            "children": [
                {
                    "type": "main",
                    "description": "子事件",
                    "isforeshadowing": True,
                    "setup_kind": "悬念",
                    "expected_payoff_family": "回收",
                }
            ],
        }
    )
    assert "children.0.isforeshadowing" in text
    assert "伏笔字段只能放在根事件上" in text
    assert "https://" not in text and "extra_forbidden" not in text


def test_translate_nested_children_forbidden() -> None:
    text = _translated_write_event_error(
        {
            "description": "根事件",
            "finalize_events": False,
            "children": [
                {
                    "type": "main",
                    "description": "子事件",
                    "children": [{"type": "main", "description": "孙事件"}],
                }
            ],
        }
    )
    assert "children.0.children" in text
    assert "子事件不得嵌套 children" in text


def test_translate_role_enum_rejects_narrative_role_word() -> None:
    text = _translated_write_event_error(
        {
            "description": "根事件",
            "finalize_events": False,
            "participants": [{"entity": 1, "role": "发送者"}],
        }
    )
    assert "participants.0.role" in text
    assert "role 只能取" in text
    assert "发送者等人物功能词是 narrative_role 的取值" in text


def test_translate_missing_child_type() -> None:
    text = _translated_write_event_error(
        {
            "description": "根事件",
            "finalize_events": False,
            "children": [{"description": "子事件"}],
        }
    )
    assert "children.0.type" in text
    assert "type 只能是" in text


def test_translate_keeps_chinese_root_validator_message() -> None:
    text = _translated_write_event_error({"description": None, "finalize_events": False})
    assert "description=null 只能用于" in text
    assert "https://" not in text and "value_error" not in text


def test_translate_patches_arity_carries_format_example() -> None:
    bad_patches = {"patches": [["children.1.2.action", "注视", "多余"]], "finalize_events": False}
    try:
        WriteEventPatchArgs.model_validate(bad_patches)
    except ValidationError as exc:
        text = str(translate_event_validation_error(exc))
    else:
        raise AssertionError("预期 patches 校验失败")
    assert "patches.0" in text
    assert "二元数组" in text
    assert '["children.1.2.action", "注视"]' in text


@pytest.mark.asyncio
async def test_write_event_schema_layer_failure_translated_via_invoke_tool() -> None:
    """langchain 工具 schema 层的 pydantic 失败（先于函数体）同样翻译成中文规则报错"""
    ledger = _writer_ledger()
    tools = _writer_tools(ledger)
    call = {
        "name": "write_event",
        "args": {"children": [{"description": "子事件"}], "finalize_events": False},
        "id": "call-1",
        "type": "tool_call",
    }
    with pytest.raises(AnnotationInputError) as exc_info:
        await _invoke_tool(tools, call)
    assert "write_event 参数不符合合同" in str(exc_info.value)
    assert "children.0.type" in str(exc_info.value)


@pytest.mark.asyncio
async def test_write_event_patches_branch_failure_translated() -> None:
    ledger = _writer_ledger()
    ledger.stash_event_draft({"description": None, "finalize_events": True})
    call = {
        "name": "write_event",
        "args": {"patches": [["children", [{"description": "子事件"}]]]},
        "id": "call-2",
        "type": "tool_call",
    }
    with pytest.raises(AnnotationInputError) as exc_info:
        await _invoke_tool(_writer_tools(ledger), call)
    assert "children.0.type" in str(exc_info.value)
    # 合并结果已回写草稿（补丁链可继续）
    assert ledger.pending_event_draft is not None
    assert ledger.pending_event_draft["children"] == [{"description": "子事件"}]


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
    # 解锁 write_entities 的检索门并登记两个别名实体
    await tools["search_graph"].ainvoke({"entities": ["蓟州驿道"]})
    await tools["write_entities"].ainvoke(
        {
            "entities": [
                {"name": "蓟州驿道", "entity_type": "location"},
                {"name": "第三铺", "entity_type": "location"},
            ]
        }
    )

    response = json.loads(await tools["search_graph"].ainvoke({"entities": ["蓟州驿道"]}))
    match = response["matches"][0]
    assert match["n"] == 1
    assert match["alias_linked"] == [{"case_number": 1, "linked": [{"n": 2, "name": "第三铺"}]}]
    assert "alias_note" in response
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
    await tools["write_entities"].ainvoke(
        {
            "entities": [
                {"name": "蓟州驿道", "entity_type": "location"},
                {"name": "第三铺", "entity_type": "location"},
            ]
        }
    )

    response = json.loads(await tools["search_graph"].ainvoke({"entities": ["侯飞白"]}))
    assert response["matches"] == []
    assert "alias_note" not in response


# ---------------------------------------------------------------------------
# 修复四：两段式写者实体准入放宽为 报告并集 ∪ 图中已登记名 ∪ 章正文逐字命中


@pytest.mark.asyncio
async def test_entity_admission_accepts_literal_chapter_text_hits() -> None:
    """报告并集之外但正文逐字出现的实体名放行（ch26 实测损失面）"""
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
        await tools["write_entities"].ainvoke({"entities": [{"name": "铜台堡", "entity_type": "location"}]})
    )
    assert receipt["accepted"] is True

    with pytest.raises(ValueError) as exc_info:
        await tools["write_entities"].ainvoke({"entities": [{"name": "凭空堡", "entity_type": "location"}]})
    assert "凭空堡" in str(exc_info.value)
    assert "本章正文" in str(exc_info.value)


@pytest.mark.asyncio
async def test_entity_admission_unaffected_for_single_block_chapters() -> None:
    """单块章（reader_reports=None）准入不受限，保持既有行为"""
    ledger = _writer_ledger()
    tools = _writer_tools(ledger)
    await tools["search_graph"].ainvoke({"entities": ["侯飞白"]})
    receipt = json.loads(
        await tools["write_entities"].ainvoke({"entities": [{"name": "任意新实体", "entity_type": "character"}]})
    )
    assert receipt["accepted"] is True
