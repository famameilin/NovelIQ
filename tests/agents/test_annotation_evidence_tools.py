"""章节 Agent 连续性与后文授权工具测试"""

from __future__ import annotations

import json

import pytest

from src.agents.annotation.errors import AnnotationAuthorizationError, AnnotationProtocolError
from src.agents.annotation.schema import (
    AfterChunkSearchResult,
    CaseSearchResult,
    Evidence,
    SearchResult,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


class _QueryService:
    """2026-08-05 用于记录连续性与后文工具调用的测试查询服务"""

    def __init__(self) -> None:
        """2026-08-05 用于初始化查询范围与读取记录"""
        self.after_scope: tuple[int, ...] | None = None
        self.reads: list[tuple[int, int]] = []

    def find_initial_case_candidates(self, current_text, *, semantic_limit=50, rotation_limit=50):
        """2026-08-05 用于返回一个初始活动案例"""
        del current_text, semantic_limit, rotation_limit
        case = CaseSearchResult(
            id="case-1",
            keys=["顾霜"],
            description="顾霜身份仍待确认",
            evidence=Evidence(reason="第一章尚未明确", chapterid=1),
        )
        return [case], ["case-1"]

    def search_continuity(self, query, *, hidden_case_ids, limit=50):
        """2026-08-05 用于验证 pull 后案例从后续 search 隐藏"""
        del query, limit
        if "case-1" in hidden_case_ids:
            return SearchResult()
        case = self.find_initial_case_candidates("")[0][0]
        return SearchResult(results=[case])

    def fetch_active_cases(self, ids):
        """2026-08-05 用于按输入案例 ID 返回活动案例"""
        case = self.find_initial_case_candidates("")[0][0]
        return [case] if ids == ["case-1"] else []

    def search_after(self, query, *, after_chapter_ids, limit=50):
        """2026-08-05 用于记录并检索固定全部后文章节"""
        del query, limit
        self.after_scope = after_chapter_ids
        return [
            AfterChunkSearchResult(chapter_id=2, chunk_id=20, excerpt="第二章命中"),
            AfterChunkSearchResult(chapter_id=4, chunk_id=40, excerpt="第四章命中"),
        ]

    def read_after_chunk(self, *, chapter_id, chunk_id, after_chapter_ids):
        """2026-08-05 用于记录后文读取并返回完整原文"""
        assert chapter_id in after_chapter_ids
        self.reads.append((chapter_id, chunk_id))
        return f"chapter={chapter_id} chunk={chunk_id}"


def _find_tool(tools: list, name: str):
    """2026-08-05 用于按工具名取得 LangChain 测试工具"""
    return next(candidate for candidate in tools if candidate.name == name)


def _ledger() -> AnnotationToolLedger:
    """2026-08-05 用于构造包含全部后续章节范围的工具账本"""
    return AnnotationToolLedger(
        current_chapter_id=1,
        current_chunk_ids=(10, 11),
        after_chapter_ids=(2, 3, 4),
    )


def test_search_switches_to_all_after_chapters_after_finish() -> None:
    """2026-08-05 用于验证 finish 后 search 覆盖固定全部后续章节"""
    service = _QueryService()
    ledger = _ledger()
    tools = build_annotation_tools(service, ledger)
    ledger.freeze_business_results()

    payload = json.loads(_find_tool(tools, "search").invoke({"query": "顾霜"}))

    assert service.after_scope == (2, 3, 4)
    assert [(item["chapter_id"], item["chunk_id"]) for item in payload["results"]] == [(2, 20), (4, 40)]
    assert ledger.authorized_after_chunks == {(2, 20), (4, 40)}


def test_read_chunk_rejects_unmatched_or_non_after_targets() -> None:
    """2026-08-05 用于验证 read_chunk 不能猜测未命中或非后文 chunk"""
    service = _QueryService()
    ledger = _ledger()
    tools = build_annotation_tools(service, ledger)
    ledger.freeze_business_results()
    _find_tool(tools, "search").invoke({"query": "顾霜"})
    read_chunk = _find_tool(tools, "read_chunk")

    with pytest.raises(AnnotationAuthorizationError, match="未由本轮 after search 命中"):
        read_chunk.invoke({"chapter_id": 3, "chunk_id": 30})
    with pytest.raises(AnnotationAuthorizationError, match="未由本轮 after search 命中"):
        read_chunk.invoke({"chapter_id": 1, "chunk_id": 10})
    assert read_chunk.invoke({"chapter_id": 4, "chunk_id": 40}) == "chapter=4 chunk=40"
    assert service.reads == [(4, 40)]


def test_pull_and_push_are_frozen_after_finish() -> None:
    """2026-08-05 用于验证首次有效 finish 后业务工具立即冻结"""
    service = _QueryService()
    ledger = _ledger()
    tools = build_annotation_tools(service, ledger)
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    ledger.freeze_business_results()

    with pytest.raises(AnnotationProtocolError, match="不允许 pull"):
        _find_tool(tools, "pull").invoke({"ids": ["case-1"]})
    with pytest.raises(AnnotationProtocolError, match="不允许 push"):
        _find_tool(tools, "push").invoke(
            {
                "outputs": [
                    {
                        "output_kind": "case",
                        "source_case_ids": [],
                        "evidence": {"reason": "仍未确认", "chapterid": 1},
                        "payload": {"keys": ["顾霜"], "description": "顾霜身份仍待确认"},
                    }
                ]
            }
        )


def test_pulled_case_must_be_covered_before_finish() -> None:
    """2026-08-05 用于验证 pull 的案例必须被至少一个 staged output 覆盖"""
    service = _QueryService()
    ledger = _ledger()
    tools = build_annotation_tools(service, ledger)
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    _find_tool(tools, "pull").invoke({"ids": ["case-1"]})

    with pytest.raises(ValueError, match="未被任何 push 输出覆盖"):
        ledger.freeze_business_results()


def test_pull_hides_case_from_later_continuity_search() -> None:
    """2026-08-05 用于验证 pull 只修改运行内可见集合并隐藏已接收案例"""
    service = _QueryService()
    ledger = _ledger()
    tools = build_annotation_tools(service, ledger)
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    _find_tool(tools, "pull").invoke({"ids": ["case-1"]})

    payload = json.loads(_find_tool(tools, "search").invoke({"query": "顾霜"}))

    assert payload["results"] == []
