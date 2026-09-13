"""search_event 工具与 authorized_event_ids 授权链路测试

覆盖：
- 检索返回历史事件树根视图并把 tree_id/root_node_id 登记进授权集合
- 非 chunk_open 阶段拒绝检索
- resolve_foreshadowing_case 对未授权 root/event 拒绝、对非伏笔根拒绝
- 先检索授权后 resolve 通过（根事件+挂树事件写入 ResolvedCase）
"""

from __future__ import annotations

import json

import pytest

from src.agents.annotation.errors import AnnotationAuthorizationError, AnnotationInputError
from src.agents.annotation.schema import (
    ActiveCaseDetails,
    CaseSearchResult,
    EventTreeHistoryResult,
    SearchResult,
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
        self.calls: list[tuple[str, int]] = []

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50):
        """2026-09-11 案例改检索制：案例经 search_pool 展示取得编号（旧合同为注入候选）"""
        del query, hidden_case_ids, case_type, limit
        return SearchResult(results=[self._case()])

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
            target_ref={"kind": "伏笔疑点", "chunk_id": 10},
        )

    def search_event_history(self, query, *, limit=50):
        """2026-08-30 用于记录严格历史检索并返回预设树根视图"""
        self.calls.append((query, limit))
        return list(self.trees)


def _history_tree(
    tree_id: str,
    root_node_id: str,
    description: str,
    *,
    foreshadow: bool = False,
) -> EventTreeHistoryResult:
    """2026-08-22 用于构造预设历史树根视图（foreshadow=True 即伏笔树根）"""
    return EventTreeHistoryResult(
        tree_id=tree_id,
        root_node_id=root_node_id,
        chapter_id=1,
        chapter_order=1,
        description=description,
        participants=[{"entity": "顾霜", "role": "主体"}],
        cross_chapter=False,
        is_foreshadow_setup=foreshadow,
        foreshadowing_status="open" if foreshadow else None,
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
    """2026-08-18 用于把活动案例登记进账本并返回临时编号

    2026-09-11 案例改检索制：编号只能由 search_pool 回执产生，测试准备亦走该通道。
    """
    tools = _tools(service, ledger)
    view = json.loads(_find_tool(tools, "search_pool").invoke({"query": "线索"}))
    return int(view["results"][0]["case_number"])


def test_search_event_registers_authorized_tree_ids() -> None:
    """2026-08-22检索结果把 tree_id 与 root_node_id 登记进授权集合"""
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "顾霜进入山门")])
    ledger = _ledger()
    tools = _tools(service, ledger)

    view = json.loads(_find_tool(tools, "search_event").invoke({"keyword": "顾霜"}))

    assert view["trees"][0]["tree_id"] == "tree-h"
    assert ledger.authorized_event_ids == {"tree-h", "node-h-root"}
    assert ledger.history_tree_views["tree-h"]["root_node_id"] == "node-h-root"
    assert service.calls == [("顾霜", 20)]
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
    """2026-09-13 用于验证未经授权的 root_event_id 不能被伏笔解决引用"""
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "顾霜进入山门")])
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    with pytest.raises(
        AnnotationAuthorizationError,
        match="root_event_id 未由事件域回执或 search_event 授权: event-x",
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "伏笔回收",
                "foreshadowing_action": "reinforce",
                "root_event_id": "event-x",
                "event_id": "node-h-root",
            }
        )


def test_resolve_foreshadowing_case_tree_id_mixup_gets_targeted_hint() -> None:
    """2026-09-04 第6章教训回归：把 tree_id 误当 root_event_id 时报错须点名这层混淆

    write_event 回执同时含 tree_id 与 node_id，模型把 tree_id 传入后被泛化报错
    拒绝，转而 search_event 查本章事件落空（树仅覆盖已完成章节）→ 空转至回合上限。
    """
    service = _EventHistoryService()
    ledger = _ledger()
    # 真实流程：write_event 只把节点 id 登记进 authorized_event_ids，
    # tree_id 仅进 authorized_tree_ids（不授权伏笔挂树引用）
    ledger.authorized_tree_ids.add("tree-mixup")
    ledger.authorized_event_ids.update({"node-bind-1"})
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    with pytest.raises(
        AnnotationAuthorizationError,
        match=r"root_event_id 未由事件域回执或 search_event 授权: tree-mixup"
        r".*事件树 id 而非事件节点 id.*children\[\]\.node_id 或 search_event 树根视图的 root_node_id",
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "伏笔回收",
                "foreshadowing_action": "reinforce",
                "root_event_id": "tree-mixup",
                "event_id": "node-bind-1",
            }
        )


def test_resolve_foreshadowing_case_passes_authorized_event_ids() -> None:
    """2026-09-13 先 search_event 授权后 resolve 可把本章事件挂进伏笔树"""
    service = _EventHistoryService(
        trees=[
            _history_tree("tree-setup", "node-setup", "顾霜立誓", foreshadow=True),
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
                "foreshadowing_action": "reinforce",
                "root_event_id": "node-setup",
                "event_id": "node-payoff",
            }
        )
    )

    assert resolved["accepted"] is True
    last = ledger.resolved_cases[-1]
    assert last.action == "foreshadowing"
    assert last.foreshadowing_action == "reinforce"
    assert last.foreshadowing_root_event_id == "node-setup"
    assert last.foreshadowing_event_id == "node-payoff"


def test_resolve_foreshadowing_case_rejects_non_foreshadow_root() -> None:
    """2026-09-13 伏笔即事件树：root_event_id 非伏笔树根（埋设事件）时拒绝并指向发现通道"""
    service = _EventHistoryService(
        trees=[
            _history_tree("tree-h", "node-h-root", "白芷承认精灵族身份", foreshadow=False),
            _history_tree("tree-p", "node-payoff", "精灵身份当众揭示"),
        ],
    )
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    _find_tool(tools, "search_event").invoke({"keyword": "白芷"})
    with pytest.raises(
        AnnotationInputError,
        match=r"root_event_id 不是伏笔树的根（埋设事件）: node-h-root",
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "疑点强化",
                "foreshadowing_action": "reinforce",
                "root_event_id": "node-h-root",
                "event_id": "node-payoff",
            }
        )
    assert ledger.resolved_cases == []


def test_resolve_foreshadowing_case_rejects_event_id_equal_to_root() -> None:
    """2026-09-13 伏笔树合同：埋设事件自身不挂边，event_id == root_event_id 拒绝"""
    service = _EventHistoryService(
        trees=[_history_tree("tree-h", "node-h-root", "白芷承认精灵族身份", foreshadow=True)],
    )
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)
    _find_tool(tools, "search_event").invoke({"keyword": "白芷"})

    with pytest.raises(
        AnnotationInputError,
        match=r"event_id 不得与 root_event_id 相同（埋设事件自身不挂边）",
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "疑点续接",
                "foreshadowing_action": "reinforce",
                "root_event_id": "node-h-root",
                "event_id": "node-h-root",
            }
        )
    assert ledger.resolved_cases == []


def test_resolve_foreshadowing_case_binds_history_root_with_foreshadow_view() -> None:
    """2026-09-13 伏笔树根经 search_event 树根视图授权后 resolve 通过"""
    service = _EventHistoryService(
        trees=[
            _history_tree("tree-h", "node-h-root", "白芷承认精灵族身份", foreshadow=True),
            _history_tree("tree-p", "node-payoff", "精灵身份当众揭示"),
        ],
    )
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)
    _find_tool(tools, "search_event").invoke({"keyword": "白芷"})

    resolved = json.loads(
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "疑点被证实",
                "foreshadowing_action": "payoff",
                "root_event_id": "node-h-root",
                "event_id": "node-payoff",
                "expected_payoff_family": "身份揭露",
            }
        )
    )
    assert resolved["accepted"] is True
    last = ledger.resolved_cases[-1]
    assert last.foreshadowing_action == "payoff"
    assert last.foreshadowing_root_event_id == "node-h-root"
    assert last.foreshadowing_event_id == "node-payoff"
    assert last.expected_payoff_family == "身份揭露"
