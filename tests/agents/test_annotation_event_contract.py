"""事件层测试：create_event/update_event/search_event 树语义

覆盖：
- tools：create_event 返回 tree_id/root_node_id 并登记授权；isforeshadowing 自动生成伏笔绑定
- update_event：main 顺延主因链、secondary 挂当前链尾；非本章树拒绝
- create_event(cause_tree_id)：经 search_event 授权的历史树可作跨章因果前驱（根携带引用）
- 未授权 cause_tree_id 拒绝
"""

from __future__ import annotations

import pytest

from src.agents.annotation.tools import build_annotation_tools
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
    payload = {"description": "顾霜拔剑"}
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


def test_create_event_isforeshadowing_creates_thread_binding() -> None:
    """2026-08-22isforeshadowing=true 自动生成伏笔绑定（setup 指向树根）"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)

    receipt = _call(tools, "create_event", _create_args(isforeshadowing=True))

    foreshadowings = ledger.bound_payloads["foreshadowings"]
    assert len(foreshadowings) == 1
    assert foreshadowings[0].setup_node_id == receipt["root_node_id"]
    assert receipt["foreshadowing_setup_node_id"] == receipt["root_node_id"]


def test_update_event_appends_main_and_secondary() -> None:
    """2026-08-22main 顺延主因链尾，secondary 作为当前链尾分支"""
    ledger = _ledger()
    tools = _tools_with_entities_shim(ledger)
    created = _call(tools, "create_event", _create_args())
    tree_id = created["tree_id"]

    updated = _call(
        tools,
        "update_event",
        {
            "tree_id": tree_id,
            "items": [
                {"type": "main", "description": "顾霜收势"},
                {"type": "secondary", "description": "旁观者惊呼"},
            ],
        },
    )

    main_node, secondary_node = (item["node_id"] for item in updated["appended"])
    # main 推进链尾；secondary 的父节点是追加时的链尾（main 节点）
    assert updated["trunk_tail"] == main_node
    bound = ledger.bound_payloads["events"]
    by_node = {item.node_id: item for item in bound}
    assert by_node[main_node].parent_node_id == created["root_node_id"]
    assert by_node[main_node].cause_role == "main"
    assert by_node[secondary_node].parent_node_id == main_node
    assert by_node[secondary_node].cause_role == "secondary"


def test_update_event_rejects_foreign_tree() -> None:
    """2026-08-22单章闭环——非本章创建的树不允许 update"""
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "前章旧事")])
    ledger = _ledger()
    tools = _tools_with_entities_service(service, ledger)

    with pytest.raises(ValueError, match="已闭环"):
        _call(tools, "update_event", {"tree_id": "tree-h", "items": [{"type": "main", "description": "续写"}]})


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

    def read_text(self, paragraph_id):
        del paragraph_id
        return ""

    def thread_exists(self, setup_id):
        del setup_id
        return False

    def fetch_active_case_details(self, case_id):
        del case_id
        return None
