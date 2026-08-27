"""search_event 工具与 authorized_event_ids 授权链路测试

覆盖：
- 检索返回历史事件树根视图并把 tree_id/root_node_id 登记进授权集合
- 非 chunk_open 阶段拒绝检索
- resolve_foreshadowing_case 对未授权 event_id 拒绝
- 先检索授权后 resolve 通过（setup/payoff 事件绑定写入 ResolvedCase）
"""

from __future__ import annotations

import json

import pytest

from src.agents.annotation.errors import AnnotationAuthorizationError
from src.agents.annotation.schema import (
    ActiveCaseDetails,
    CaseSearchResult,
    EventTreeHistoryResult,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools

_CHUNK_TEXT = "\u201c住手\u201d回荡"


class _EventHistoryService:
    """2026-08-18 用于记录检索调用并返回预设历史事件树的测试查询服务"""

    def __init__(
        self,
        trees: list[EventTreeHistoryResult] | None = None,
        current_chapter_order: int = 2,
    ) -> None:
        self.trees = trees or []
        self.current_chapter_order = current_chapter_order
        self.calls: list[tuple[str, int, int]] = []

    def find_initial_case_candidates(self, current_text, *, semantic_limit=50, rotation_limit=50):
        del current_text, semantic_limit, rotation_limit
        return [self._case()], ["case-1"]

    def _case(self) -> CaseSearchResult:
        """2026-08-18 用于构造可严格解决的活动案例"""
        return CaseSearchResult(
            id="case-1",
            type="foreshadowing_payoff",
            chunk_id=10,
            keys=["线索"],
            description="伏笔回收判断",
        )

    def fetch_active_case_details(self, case_id):
        """2026-08-18 用于返回包含稳定目标的 active 案例"""
        if case_id != "case-1":
            return None
        return ActiveCaseDetails(
            **self._case().model_dump(mode="python"),
            target_key="thread-1",
            target_ref={"kind": "foreshadowing", "chunk_id": 10, "setup_id": "thread-1"},
        )

    def search_event_history(self, query, *, max_chapter_order, limit=50):
        """2026-08-22记录检索范围并返回预设树根视图"""
        self.calls.append((query, max_chapter_order, limit))
        return list(self.trees)


def _history_tree(tree_id: str, root_node_id: str, description: str) -> EventTreeHistoryResult:
    """2026-08-22 用于构造预设历史树根视图"""
    return EventTreeHistoryResult(
        tree_id=tree_id,
        root_node_id=root_node_id,
        chapter_id=1,
        chapter_order=1,
        description=description,
        participants=[{"entity": "顾霜", "role": "主体"}],
        cross_chapter=False,
    )


def _ledger() -> AnnotationToolLedger:
    """2026-08-18 用于构造带唯一 current 原文的工具账本"""
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=2,
        current_chunk_id=10,
        current_chunk_text=_CHUNK_TEXT,
        allow_future_context=False,
        current_chapter_order=2,
    )


def _tools(service, ledger):
    return build_annotation_tools(service, ledger)


def _find_tool(tools, name):
    return next(candidate for candidate in tools if candidate.name == name)


def _register_payoff_case(service, ledger) -> int:
    """2026-08-18 用于把活动案例登记进账本并返回临时编号"""
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    return ledger.case_number_by_id["case-1"]


def test_search_event_registers_authorized_tree_ids() -> None:
    """2026-08-22检索结果把 tree_id 与 root_node_id 登记进授权集合"""
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "顾霜进入山门")])
    ledger = _ledger()
    tools = _tools(service, ledger)

    view = json.loads(_find_tool(tools, "search_event").invoke({"keyword": "顾霜"}))

    assert view["trees"][0]["tree_id"] == "tree-h"
    assert ledger.authorized_event_ids == {"tree-h", "node-h-root"}
    assert ledger.history_tree_views["tree-h"]["root_node_id"] == "node-h-root"
    # current_chapter_order=2 → 只检索第 1 章
    assert service.calls == [("顾霜", 1, 20)]
    assert ledger.search_log[-1]["tool"] == "search_event"
    assert ledger.search_log[-1]["hits"] == ["tree-h"]


def test_search_event_rejects_outside_chunk_open_phase() -> None:
    """2026-08-18 用于验证非 chunk_open 阶段检索被拒绝"""
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "顾霜进入山门")])
    ledger = _ledger()
    ledger.set_phase("writing")
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationAuthorizationError, match="阶段 .* 不允许 search_event"):
        _find_tool(tools, "search_event").invoke({"keyword": "顾霜"})


def test_resolve_foreshadowing_case_rejects_unauthorized_event_id() -> None:
    """2026-08-18 用于验证未经授权的 event_id 不能被伏笔解决引用"""
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "顾霜进入山门")])
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    with pytest.raises(
        AnnotationAuthorizationError,
        match="setup_event_id 未由 create_event/update_event 回执或 search_event 授权: event-x",
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "伏笔回收",
                "setup_event_id": "event-x",
            }
        )


def test_resolve_foreshadowing_case_passes_authorized_event_ids() -> None:
    """2026-08-22先 search_event 授权后 resolve 可绑定 setup/payoff 节点"""
    service = _EventHistoryService(
        trees=[
            _history_tree("tree-setup", "node-setup", "顾霜立誓"),
            _history_tree("tree-payoff", "node-payoff", "顾霜兑现承诺"),
        ]
    )
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    _find_tool(tools, "search_event").invoke({"keyword": "顾霜"})
    assert ledger.authorized_event_ids >= {"tree-setup", "node-setup", "tree-payoff", "node-payoff"}

    resolved = json.loads(
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "伏笔回收",
                "setup_event_id": "node-setup",
                "payoff_event_id": "node-payoff",
            }
        )
    )

    assert resolved["accepted"] is True
    assert ledger.resolved_cases[-1].action == "foreshadowing"
    assert ledger.resolved_cases[-1].setup_event_id == "node-setup"
    assert ledger.resolved_cases[-1].payoff_event_id == "node-payoff"
