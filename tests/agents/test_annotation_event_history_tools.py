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
        case_has_thread: bool = True,
        setup_event_owner: str | None = None,
    ) -> None:
        self.trees = trees or []
        self.current_chapter_order = current_chapter_order
        self.case_has_thread = case_has_thread
        self.setup_event_owner = setup_event_owner
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
        target_ref: dict = {"kind": "伏笔疑点", "chunk_id": 10}
        if self.case_has_thread:
            target_ref["setup_id"] = "thread-1"
        return ActiveCaseDetails(
            **self._case().model_dump(mode="python"),
            target_key="thread-1",
            target_ref=target_ref,
        )

    def search_event_history(self, query, *, limit=50):
        """2026-08-30 用于记录严格历史检索并返回预设树根视图"""
        self.calls.append((query, limit))
        return list(self.trees)

    def thread_id_for_setup_event(self, setup_event_id):
        """2026-09-13 用于返回埋设事件占用线程的预设值"""
        del setup_event_id
        return self.setup_event_owner


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
    """2026-08-18 用于验证未经授权的 event_id 不能被伏笔解决引用"""
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "顾霜进入山门")])
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    with pytest.raises(
        AnnotationAuthorizationError,
        match="setup_event_id 未由事件域回执或 search_event 授权: event-x",
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "伏笔回收",
                "setup_event_id": "event-x",
            }
        )


def test_resolve_foreshadowing_case_tree_id_mixup_gets_targeted_hint() -> None:
    """2026-09-04 第6章教训回归：把 tree_id 误当 setup_event_id 时报错须点名这层混淆

    write_event 回执同时含 tree_id 与 node_id，模型把 tree_id 传入后被泛化报错
    拒绝，转而 search_event 查本章事件落空（树仅覆盖已完成章节）→ 空转至回合上限。
    """
    service = _EventHistoryService()
    ledger = _ledger()
    # 真实流程：write_event 只把节点 id 登记进 authorized_event_ids，
    # tree_id 仅进 authorized_tree_ids（不授权 setup/payoff 引用）
    ledger.authorized_tree_ids.add("tree-mixup")
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    with pytest.raises(
        AnnotationAuthorizationError,
        match=r"setup_event_id 未由事件域回执或 search_event 授权: tree-mixup"
        r".*事件树 id 而非事件节点 id.*children\[\]\.node_id 或 root_node_id",
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "伏笔回收",
                "setup_event_id": "tree-mixup",
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


def test_resolve_foreshadowing_case_requires_setup_event_for_threadless_case() -> None:
    """2026-09-04 用于验证未挂线程案例确认伏笔必须给埋设事件，缺锚点拒绝、带锚点接受"""
    service = _EventHistoryService(
        trees=[_history_tree("tree-h", "node-h-root", "白芷承认精灵族身份")],
        case_has_thread=False,
    )
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    with pytest.raises(
        AnnotationInputError,
        match="未关联伏笔线程.*setup_event_id.*close_case",
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "疑点强化",
                "setup_status": "reinforced",
            }
        )
    assert ledger.resolved_cases == []

    _find_tool(tools, "search_event").invoke({"keyword": "白芷"})
    resolved = json.loads(
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "疑点被证实",
                "setup_event_id": "node-h-root",
                "setup_status": "reinforced",
            }
        )
    )
    assert resolved["accepted"] is True
    assert ledger.resolved_cases[-1].action == "foreshadowing"
    assert ledger.resolved_cases[-1].setup_event_id == "node-h-root"
    # 未挂线程时 setup_summary 兜底为案例描述，确认信息不丢
    assert ledger.resolved_cases[-1].setup_summary == "伏笔回收判断"


def test_resolve_foreshadowing_case_rejects_setup_event_owned_by_other_thread() -> None:
    """2026-09-13 ch20 崩溃回归：重指他人埋设事件须工具层即拒，而非完成事务撞唯一约束炸 run"""
    service = _EventHistoryService(
        trees=[_history_tree("tree-setup", "node-setup", "贺重明烧叶求救")],
        setup_event_owner="thread-other",
    )
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)
    _find_tool(tools, "search_event").invoke({"keyword": "贺重明"})

    with pytest.raises(
        AnnotationInputError,
        match=r"已绑定伏笔线程 thread-other.*同一埋设事件只能属于一条线程",
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "疑点续接",
                "setup_event_id": "node-setup",
            }
        )
    assert ledger.resolved_cases == []


def test_resolve_foreshadowing_case_allows_own_thread_setup_event() -> None:
    """2026-09-13 埋设事件占用者就是案例目标线程时放行（幂等重申）"""
    service = _EventHistoryService(
        trees=[_history_tree("tree-setup", "node-setup", "白芷承认精灵族身份")],
        setup_event_owner="thread-1",
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
                "setup_event_id": "node-setup",
                "setup_status": "reinforced",
            }
        )
    )
    assert resolved["accepted"] is True
    assert ledger.resolved_cases[-1].setup_event_id == "node-setup"
