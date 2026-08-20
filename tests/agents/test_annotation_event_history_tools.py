"""search_event_history 工具与 authorized_event_ids 授权链路测试

覆盖：
- 检索返回历史事件视图并把返回 event_id 登记进授权集合
- 检索范围 max_chapter_order = 当前章序 - 1（只检索当前章之前）
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
    EventHistoryResult,
    TextEvidence,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools

_CHUNK_TEXT = "\u201c住手\u201d回荡"


class _EventHistoryService:
    """2026-08-18 用于记录检索调用并返回预设历史事件的测试查询服务"""

    def __init__(
        self,
        events: list[EventHistoryResult] | None = None,
        current_chapter_order: int = 2,
    ) -> None:
        self.events = events or []
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
        """2026-08-18 用于记录检索范围并返回预设事件"""
        self.calls.append((query, max_chapter_order, limit))
        return list(self.events)


def _history_event(event_id: str, description: str) -> EventHistoryResult:
    """2026-08-18 用于构造预设历史事件结果（文本哈希仅满足格式校验）"""
    return EventHistoryResult(
        event_id=event_id,
        chapter_id=1,
        chapter_order=1,
        description=description,
        participants=[{"entity": "顾霜", "role": "主体"}],
        anchor_paragraph_ids=[0],
        char_start=0,
        char_end=8,
        text_hash="0" * 64,
        evidence=[TextEvidence(paragraph_ids=[0], char_start=0, char_end=8, text_hash="0" * 64)],
        causal_event_refs=[],
        tree_id="tree-h",
    )


def _ledger() -> AnnotationToolLedger:
    """2026-08-18 用于构造带唯一 current 原文的工具账本"""
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=10,
        current_chunk_text=_CHUNK_TEXT,
        allow_future_context=False,
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


def test_search_event_history_registers_authorized_event_ids() -> None:
    """2026-08-18 用于验证检索结果登记授权事件且范围限当前章之前"""
    service = _EventHistoryService(events=[_history_event("event-a", "顾霜进入山门")])
    ledger = _ledger()
    tools = _tools(service, ledger)

    view = json.loads(_find_tool(tools, "search_event_history").invoke({"query": "顾霜"}))

    assert view["events"][0]["event_id"] == "event-a"
    assert ledger.authorized_event_ids == {"event-a"}
    # current_chapter_order=2 → 只检索第 1 章
    assert service.calls == [("顾霜", 1, 50)]
    assert ledger.search_log[-1]["tool"] == "search_event_history"
    assert ledger.search_log[-1]["hits"] == ["event-a"]


def test_search_event_history_rejects_outside_chunk_open_phase() -> None:
    """2026-08-18 用于验证非 chunk_open 阶段检索被拒绝"""
    service = _EventHistoryService(events=[_history_event("event-a", "顾霜进入山门")])
    ledger = _ledger()
    ledger.set_phase("writing")
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationAuthorizationError, match="阶段 .* 不允许 search_event_history"):
        _find_tool(tools, "search_event_history").invoke({"query": "顾霜"})


def test_resolve_foreshadowing_case_rejects_unauthorized_event_id() -> None:
    """2026-08-18 用于验证未经检索授权的 event_id 不能被伏笔解决引用"""
    service = _EventHistoryService(events=[_history_event("event-a", "顾霜进入山门")])
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    with pytest.raises(
        AnnotationAuthorizationError,
        match="setup_event_id 未由本轮 search_event_history 授权: event-x",
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "伏笔回收",
                "setup_event_id": "event-x",
            }
        )


def test_resolve_foreshadowing_case_passes_authorized_event_ids() -> None:
    """2026-08-18 用于验证先检索授权后 resolve 可绑定 setup/payoff 事件"""
    service = _EventHistoryService(
        events=[
            _history_event("event-setup", "顾霜立誓"),
            _history_event("event-payoff", "顾霜兑现承诺"),
        ]
    )
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    _find_tool(tools, "search_event_history").invoke({"query": "顾霜"})
    assert ledger.authorized_event_ids == {"event-setup", "event-payoff"}

    resolved = json.loads(
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "伏笔回收",
                "setup_event_id": "event-setup",
                "payoff_event_id": "event-payoff",
            }
        )
    )

    assert resolved["accepted"] is True
    assert ledger.resolved_cases[-1].action == "foreshadowing"
    assert ledger.resolved_cases[-1].setup_event_id == "event-setup"
    assert ledger.resolved_cases[-1].payoff_event_id == "event-payoff"
