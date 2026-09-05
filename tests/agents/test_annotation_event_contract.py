"""事件层测试：create_event/search_event 树语义

覆盖：
- tools：create_event 返回 tree_id/root_node_id 并登记授权；isforeshadowing 自动生成伏笔绑定
- create_event.children：main 顺延主因链、secondary 挂当时主链尾
- create_event(cause_tree_id)：经 search_event 授权的历史树可作跨章因果前驱（根携带引用）
- 未授权 cause_tree_id 拒绝
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.schema import ChunkParagraphInfo, CreateEventInput
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
                "entity": "顾霜",
                "role": "主体",
                "narrative_role": "主体",
                "action": "拔剑",
                "emotion": "mild_negative",
            }
        ],
    }
    # 非 isforeshadowing 的事件不需要三字段；isforeshadowing 时由调用方补
    if not overrides.get("isforeshadowing"):
        payload.update(overrides)
        return payload
    payload.update(
        {
            "setup_kind": "悬念",
            "expected_payoff_family": "身份揭露",
            "payoff_likelihood": "medium",
        }
    )
    payload.update(overrides)
    return payload


def test_create_event_returns_tree_and_authorizes_root() -> None:
    """2026-08-22创建返回服务端派发的 tree_id/root_node_id 并登记授权"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)

    receipt = _call(tools, "create_event", _create_args())

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


def test_create_event_requires_character_participant_state_fields() -> None:
    """2026-08-30 用于拒绝未携带人物动态状态的角色参与者"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)

    with pytest.raises(ValueError, match="必须同时提供 narrative_role/action/emotion"):
        _call(
            tools,
            "create_event",
            {
                "description": "顾霜拔剑",
                "participants": [{"entity": "顾霜", "role": "主体"}],
                "finalize_events": True,
            },
        )

    assert ledger.event_trees == {}
    assert "events" not in ledger.domain_receipts
    assert "character_observations" not in ledger.domain_receipts


def test_create_event_without_participants_binds_empty_character_domain() -> None:
    """2026-08-30 用于允许无人物事件明确完成空人物动态领域"""
    ledger = _ledger()
    tools = build_annotation_tools(_QueryServiceShim(), ledger)

    receipt = _call(tools, "create_event", {"description": "山门夜雨", "finalize_events": True})

    assert receipt["character_observation_count"] == 0
    assert ledger.bound_payloads["character_observations"] == []
    assert ledger.domain_receipts >= {"events", "character_observations"}


def test_create_event_empty_completion_does_not_invent_event() -> None:
    """2026-08-30 用于允许无事件章节通过同一工具显式完成事件领域"""
    ledger = _ledger()
    tools = build_annotation_tools(_QueryServiceShim(), ledger)

    receipt = _call(
        tools,
        "create_event",
        {"description": None, "finalize_events": True},
    )

    assert receipt["accepted"] is True
    assert receipt["item_count"] == 0
    assert receipt["finalized"] is True
    assert ledger.bound_payloads["events"] == []
    assert ledger.bound_payloads["character_observations"] == []
    assert ledger.domain_receipts >= {"events", "character_observations"}


def test_create_event_isforeshadowing_creates_thread_binding() -> None:
    """2026-08-22isforeshadowing=true 自动生成伏笔绑定（setup 指向树根）"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)

    receipt = _call(tools, "create_event", _create_args(isforeshadowing=True))

    foreshadowings = ledger.bound_payloads["foreshadowings"]
    assert len(foreshadowings) == 1
    assert foreshadowings[0].setup_node_id == receipt["root_node_id"]
    assert receipt["foreshadowing_setup_node_id"] == receipt["root_node_id"]


def test_create_event_exposes_pydantic_schema_and_creates_ordered_children() -> None:
    """2026-08-30 用于验证工具公开真实 Pydantic 合同并原子创建有序子节点"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)

    event_tool = _find_tool(tools, "create_event")
    assert event_tool.args_schema is CreateEventInput
    created = _call(
        tools,
        "create_event",
        {
            **_create_args(),
            "children": [
                {
                    "type": "main",
                    "description": "顾霜收势",
                    "participants": [
                        {
                            "entity": "顾霜",
                            "role": "主体",
                            "narrative_role": "主体",
                            "action": "收势",
                            "emotion": "neutral",
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


def test_create_event_rejects_invalid_children_without_mutating_ledger() -> None:
    """2026-08-30 用于验证子节点合同失败时不会留下半棵事件树"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)

    with pytest.raises(ValidationError, match="children"):
        _call(
            tools,
            "create_event",
            {**_create_args(), "children": [{"type": "invalid", "description": "续写"}]},
        )
    assert ledger.event_trees == {}
    assert ledger.bound_payloads.get("events") is None
    assert ledger.authorized_event_ids == set()


def test_create_event_rejects_duplicate_character_action_atomically() -> None:
    """2026-08-30 用于保证重复人物动作不会部分写入第二棵事件树"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)
    first = _call(tools, "create_event", _create_args(finalize_events=False))
    original_event_ids = set(ledger.authorized_event_ids)

    with pytest.raises(ValueError, match="人物动态状态重复"):
        _call(tools, "create_event", _create_args(finalize_events=True))

    assert list(ledger.event_trees) == [first["tree_id"]]
    assert len(ledger.bound_payloads["events"]) == 1
    assert len(ledger.bound_payloads["character_observations"]) == 1
    assert ledger.authorized_event_ids == original_event_ids


def test_create_event_accepts_authorized_cause_tree() -> None:
    """2026-08-22search_event 授权后的历史树可作跨章因果前驱"""
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "前章旧事")])
    ledger = _ledger()
    tools = _tools_with_entities_service(service, ledger)
    _find_tool(tools, "search_event").invoke({"keyword": "旧事"})

    receipt = _call(tools, "create_event", _create_args(cause_tree_id="tree-h"))

    assert receipt["cross_chapter"] is True
    bound = ledger.bound_payloads["events"][0]
    assert bound.causal_event_refs == ["node-h-root"]
    assert bound.cause_role == "root"


def test_create_event_rejects_unauthorized_cause_tree() -> None:
    """2026-08-22未经 create_event 回执或 search_event 授权的 cause_tree_id 拒绝"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)

    with pytest.raises(ValueError, match="cause_tree_id"):
        _call(tools, "create_event", _create_args(cause_tree_id="unknown-tree"))


class _QueryServiceShim:
    """2026-08-19 用于为事件写入提供最小查询服务（无需检索历史）"""

    def find_initial_case_candidates(self, current_text, *, semantic_limit=50, rotation_limit=50):
        del current_text, semantic_limit, rotation_limit
        return [], []

    def search_pool(self, query, *, hidden_case_ids, limit=50):
        del query, hidden_case_ids, limit
        return []

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


def test_create_event_does_not_require_local_paragraph_indices() -> None:
    """2026-08-22 回归：create_event 不再按段落锚点派生证据

    节点不携带锚点/字符区间/哈希/证据；章级证据由持久化层盖章。
    全局 paragraph_id 与局部下标错位时，create_event 仍应成功。
    """
    ledger = _offset_paragraph_ledger()
    tools = _tools_with_entities_shim(ledger)

    receipt = _call(tools, "create_event", _create_args())

    assert receipt["accepted"] is True
    bound = ledger.bound_payloads["events"][0]
    dumped = bound.model_dump()
    assert "anchor_paragraph_ids" not in dumped
    assert "evidence" not in dumped
    assert "char_start" not in dumped
    assert dumped["description"] == "顾霜拔剑"
