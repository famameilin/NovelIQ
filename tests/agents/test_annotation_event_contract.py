"""事件层测试：write_event/search_event 树语义

覆盖：
- tools：write_event 返回 tree_id/root_node_id 并登记授权；isforeshadowing 自动生成伏笔绑定
- write_event.children：main 顺延主因链、secondary 挂当时主链尾
- write_event(cause_tree_id)：经 search_event 授权的历史树可作跨章因果前驱（根携带引用）
- 未授权 cause_tree_id 拒绝
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agents.annotation.errors import AnnotationInputError
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.schema import ChunkParagraphInfo, SearchResult, WriteEventPatchArgs
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools
from tests.agents.test_annotation_event_history_tools import (
    _EventHistoryService,
    _history_tree,
)
from tests.agents.test_annotation_evidence_tools import _call, _find_tool, _ledger


def _tools_with_entities_shim(ledger) -> list:
    """2026-08-22 用于构建已声明顾霜实体的工具集（无历史查询）"""
    tools = build_annotation_tools(_QueryServiceShim(), ledger)
    _call(tools, "write_entities", {"entities": [{"name": "顾霜", "entity_type": "character"}]})
    return tools


def _tools_with_entities_service(service, ledger) -> list:
    """2026-08-22 用于构建已声明顾霜实体并带历史查询服务的工具集"""
    tools = build_annotation_tools(service, ledger)
    _call(tools, "write_entities", {"entities": [{"name": "顾霜", "entity_type": "character"}]})
    return tools


def _create_args(**overrides) -> dict:
    """2026-08-30 用于构造携带人物动态状态的事件树输入"""
    payload = {
        "description": "顾霜拔剑",
        "finalize_events": True,
        "participants": [
            {
                "entity": 1,
                "role": "主体",
                "narrative_role": "主体",
                "action": "拔剑",
                "emotion": -1,
            }
        ],
    }
    # 非 isforeshadowing 的事件不需要两字段；isforeshadowing 时由调用方补
    if not overrides.get("isforeshadowing"):
        payload.update(overrides)
        return payload
    payload.update(
        {
            "expected_payoff_family": "身份揭露",
            "payoff_likelihood": "medium",
        }
    )
    payload.update(overrides)
    return payload


def test_write_event_returns_tree_and_authorizes_root() -> None:
    """2026-08-22创建返回服务端派发的 tree_id/root_node_id 并登记授权"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)

    receipt = _call(tools, "write_event", _create_args())

    tree_id = receipt["tree_id"]
    root_node_id = receipt["root_node_id"]
    assert receipt["accepted"] is True
    assert receipt["cause_role"] == "root"
    assert receipt["cross_chapter"] is False
    # 授权集合登记节点 id（伏笔 setup/payoff 用）；本章树 id 走 event_trees 查找
    assert root_node_id in ledger.authorized_event_ids
    bound = ledger.bound_payloads["events"]
    assert len(bound) == 1
    assert bound[0].node_id == root_node_id
    assert bound[0].tree_id == tree_id
    assert bound[0].cause_role == "root"
    assert "events" in ledger.domain_receipts
    assert "character_observations" in ledger.domain_receipts
    assert ledger.bound_payloads["character_observations"][0].action == "拔剑"


def test_write_event_requires_character_participant_state_fields() -> None:
    """2026-08-30 用于拒绝未携带人物动态状态的角色参与者"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)

    with pytest.raises(ValueError, match="必须同时提供 narrative_role/action/emotion"):
        _call(
            tools,
            "write_event",
            {
                "description": "顾霜拔剑",
                "participants": [{"entity": 1, "role": "主体"}],
                "finalize_events": True,
            },
        )

    assert ledger.event_trees == {}
    assert "events" not in ledger.domain_receipts
    assert "character_observations" not in ledger.domain_receipts


def test_write_event_without_participants_binds_empty_character_domain() -> None:
    """2026-08-30 用于允许无人物事件明确完成空人物动态领域"""
    ledger = _ledger()
    tools = build_annotation_tools(_QueryServiceShim(), ledger)

    receipt = _call(tools, "write_event", {"description": "山门夜雨", "finalize_events": True})

    assert receipt["character_observation_count"] == 0
    assert ledger.bound_payloads["character_observations"] == []
    assert ledger.domain_receipts >= {"events", "character_observations"}


def test_write_event_empty_completion_does_not_invent_event() -> None:
    """2026-08-30 用于允许无事件章节通过同一工具显式完成事件领域"""
    ledger = _ledger()
    tools = build_annotation_tools(_QueryServiceShim(), ledger)

    receipt = _call(
        tools,
        "write_event",
        {"description": None, "finalize_events": True},
    )

    assert receipt["accepted"] is True
    assert receipt["item_count"] == 0
    assert receipt["finalized"] is True
    assert ledger.bound_payloads["events"] == []
    assert ledger.bound_payloads["character_observations"] == []
    assert ledger.domain_receipts >= {"events", "character_observations"}


def test_write_event_isforeshadowing_creates_thread_binding() -> None:
    """2026-09-13 伏笔即事件树：isforeshadowing=true 根事件携带伏笔属性，回执暴露根节点 id"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)

    receipt = _call(tools, "write_event", _create_args(isforeshadowing=True))

    assert receipt["foreshadowing_root_node_id"] == receipt["root_node_id"]
    bound = ledger.bound_payloads["events"]
    root = next(node for node in bound if node.node_id == receipt["root_node_id"])
    assert root.is_foreshadow_setup is True
    assert root.expected_payoff_family == "身份揭露"
    assert root.payoff_likelihood == "medium"


def test_write_event_exposes_pydantic_schema_and_creates_ordered_children() -> None:
    """2026-08-30 用于验证工具公开真实 Pydantic 合同并原子创建有序子节点"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)

    event_tool = _find_tool(tools, "write_event")
    assert event_tool.args_schema is WriteEventPatchArgs
    created = _call(
        tools,
        "write_event",
        {
            **_create_args(),
            "children": [
                {
                    "type": "main",
                    "description": "顾霜收势",
                    "participants": [
                        {
                            "entity": 1,
                            "role": "主体",
                            "narrative_role": "主体",
                            "action": "收势",
                            "emotion": 0,
                        }
                    ],
                },
                {"type": "secondary", "description": "旁观者惊呼"},
                {"type": "main", "description": "顾霜离开山门"},
            ],
        },
    )

    main_node, secondary_node, final_main_node = (item["node_id"] for item in created["children"])
    assert created["trunk_tail"] == final_main_node
    bound = ledger.bound_payloads["events"]
    by_node = {item.node_id: item for item in bound}
    assert by_node[main_node].parent_node_id == created["root_node_id"]
    assert by_node[main_node].cause_role == "main"
    assert by_node[secondary_node].parent_node_id == main_node
    assert by_node[secondary_node].cause_role == "secondary"
    assert by_node[final_main_node].parent_node_id == main_node
    assert by_node[final_main_node].cause_role == "main"
    assert by_node[main_node].participants[0].action == "收势"
    assert [item.action for item in ledger.bound_payloads["character_observations"]] == ["拔剑", "收势"]
    assert [event.node_id for event in bound] == [created["root_node_id"], main_node, secondary_node, final_main_node]
    assert len([record for record in ledger.write_records if record["domain"] == "events"]) == 1


def test_write_event_rejects_invalid_children_without_mutating_ledger() -> None:
    """2026-08-30 用于验证子节点合同失败时不会留下半棵事件树"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)

    # 直连 .invoke 走 langchain schema 层（args_schema=WriteEventPatchArgs），保持裸
    # ValidationError；生产路径经 graph._invoke_tool 时才翻译成中文规则报错（修复二）
    with pytest.raises(ValidationError, match="children"):
        _call(
            tools,
            "write_event",
            {**_create_args(), "children": [{"type": "invalid", "description": "续写"}]},
        )
    assert ledger.event_trees == {}
    assert ledger.bound_payloads.get("events") is None
    assert ledger.authorized_event_ids == set()


def test_write_event_rejects_duplicate_character_action_atomically() -> None:
    """2026-08-30 用于保证重复人物动作不会部分写入第二棵事件树"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)
    first = _call(tools, "write_event", _create_args(finalize_events=False))
    original_event_ids = set(ledger.authorized_event_ids)

    with pytest.raises(ValueError, match="人物动态状态重复"):
        _call(tools, "write_event", _create_args(finalize_events=True))

    assert list(ledger.event_trees) == [first["tree_id"]]
    assert len(ledger.bound_payloads["events"]) == 1
    assert len(ledger.bound_payloads["character_observations"]) == 1
    assert ledger.authorized_event_ids == original_event_ids


def test_write_event_accepts_authorized_cause_tree() -> None:
    """2026-08-22search_event 授权后的历史树可作跨章因果前驱"""
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "前章旧事")])
    ledger = _ledger()
    tools = _tools_with_entities_service(service, ledger)
    _find_tool(tools, "search_event").invoke({"keyword": "旧事"})

    receipt = _call(tools, "write_event", _create_args(cause_tree_id="tree-h"))

    assert receipt["cross_chapter"] is True
    bound = ledger.bound_payloads["events"][0]
    assert bound.causal_event_refs == ["node-h-root"]
    assert bound.cause_role == "root"


def test_write_event_rejects_unauthorized_cause_tree() -> None:
    """2026-08-22未经 write_event 回执或 search_event 授权的 cause_tree_id 拒绝"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)

    with pytest.raises(ValueError, match="cause_tree_id"):
        _call(tools, "write_event", _create_args(cause_tree_id="unknown-tree"))


class _QueryServiceShim:
    """2026-08-19 用于为事件写入提供最小查询服务（无需检索历史）"""

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50):
        del query, hidden_case_ids, case_type, limit
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        del query, range_name, limit
        return []

    def thread_exists(self, setup_id):
        del setup_id
        return False

    def fetch_active_case_details(self, case_id):
        del case_id
        return None


def _offset_paragraph_ledger() -> AnnotationToolLedger:
    """2026-08-22 用于构造全局段落 id 与 0 基局部下标错位的账本（复现第 2 章坐标场景）"""
    chunk_text = "\u201c住手\u201d回荡"
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=2,
        current_chunk_id=20,
        current_chunk_text=chunk_text,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[44, 45],
            char_spans=[(0, 4), (4, len(chunk_text))],
            texts=["\u201c住手\u201d", "回荡"],
        ),
    )


def test_write_event_does_not_require_local_paragraph_indices() -> None:
    """2026-08-22 回归：write_event 不再按段落锚点派生证据

    节点不携带锚点/字符区间/哈希/证据；章级证据由持久化层盖章。
    全局 paragraph_id 与局部下标错位时，write_event 仍应成功。
    """
    ledger = _offset_paragraph_ledger()
    tools = _tools_with_entities_shim(ledger)

    receipt = _call(tools, "write_event", _create_args())

    assert receipt["accepted"] is True
    bound = ledger.bound_payloads["events"][0]
    dumped = bound.model_dump()
    assert "anchor_paragraph_ids" not in dumped
    assert "evidence" not in dumped
    assert "char_start" not in dumped
    assert dumped["description"] == "顾霜拔剑"


def test_write_event_failure_stashes_draft_and_patch_repairs() -> None:
    """2026-09-11 草稿补丁：校验失败后缓存草稿，patches 只修正错误字段，不整树重发"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)
    bad_args = _create_args()
    bad_args["participants"][0]["entity"] = 999

    with pytest.raises(ValueError, match="write_event.participants.0 实体编号 999 未登记"):
        _call(tools, "write_event", bad_args)

    # graph 层失败即缓存草稿（此处模拟其行为后走补丁链路）
    ledger.stash_event_draft(bad_args)
    receipt = _call(tools, "write_event", {"patches": [["participants.0.entity", 1]]})

    assert receipt["accepted"] is True
    assert receipt["draft_repaired"] is True
    assert receipt["finalized"] is True
    assert list(ledger.event_trees) == [receipt["tree_id"]]
    # 修复周期结束，草稿清空
    assert ledger.pending_event_draft is None


def test_write_event_patch_failure_keeps_merged_draft_as_new_base() -> None:
    """2026-09-11 补丁后仍失败：合并结果成为新草稿基线，继续增量修正不丢已输出内容"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)
    bad_args = _create_args()
    bad_args["participants"][0]["entity"] = 999
    bad_args["participants"][0]["emotion"] = "愤怒"
    ledger.stash_event_draft(bad_args)

    # 第一次补丁修正实体编号但情绪仍填语气词 → 校验报错且报错路径指向分值字段
    # （2026-09-12 修复二：write_event 边界的 pydantic 失败统一翻译成中文规则报错）
    with pytest.raises(AnnotationInputError, match="emotion 不接受 愤怒"):
        _call(tools, "write_event", {"patches": [["participants.0.entity", 1]]})

    # 合并结果已回写草稿：第二次补丁只需补情绪分值
    receipt = _call(tools, "write_event", {"patches": [["participants.0.emotion", -2]]})

    assert receipt["accepted"] is True
    bound = ledger.bound_payloads["events"][0]
    assert bound.participants[0].entity == "顾霜"
    assert bound.participants[0].emotion == -2
    assert ledger.pending_event_draft is None


def test_merge_event_patches_rejects_bad_paths_without_draft() -> None:
    """2026-09-11 补丁路径合同：无草稿、非法路径、越界路径均报错且不破坏原草稿"""
    from src.agents.annotation.errors import AnnotationInputError

    ledger = _ledger()

    with pytest.raises(AnnotationInputError, match="没有可修正的 write_event 草稿"):
        ledger.merge_event_patches([["description", "x"]])

    draft = _create_args()
    ledger.stash_event_draft(draft)

    with pytest.raises(AnnotationInputError, match="必须是"):
        ledger.merge_event_patches([["description"]])
    with pytest.raises(AnnotationInputError, match="路径不存在"):
        ledger.merge_event_patches([["children.9.participants.0.emotion", -1]])
    with pytest.raises(AnnotationInputError, match="路径不存在"):
        ledger.merge_event_patches([["nested.missing.key", -1]])

    # 带 write_event. 前缀的报错路径可剥前缀后命中；补丁失败不改变原草稿
    ledger.merge_event_patches([["write_event.description", "顾霜收剑入鞘"]])
    assert ledger.pending_event_draft["description"] == "顾霜收剑入鞘"
    assert draft["description"] == "顾霜拔剑"
