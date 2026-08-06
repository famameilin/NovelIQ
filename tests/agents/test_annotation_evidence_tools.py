"""章节 Agent 连续性与后文授权工具测试"""

from __future__ import annotations

import json

import pytest

from src.agents.annotation.errors import AnnotationAuthorizationError, AnnotationProtocolError
from src.agents.annotation.schema import (
    AfterChunkSearchResult,
    CaseSearchResult,
    Evidence,
    GraphSearchResult,
    SearchResult,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


class _QueryService:
    """2026-08-05 用于记录连续性与后文工具调用的测试查询服务"""

    def __init__(self) -> None:
        """2026-08-06 用于初始化后文查询与读取记录"""
        self.after_queries: list[str] = []
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
        del limit
        if query == "图节点":
            return SearchResult(
                results=[
                    GraphSearchResult(
                        target_node_id="fact:test",
                        source_kind="chapter_annotation",
                        evidence=Evidence(reason="图节点命中", chapterid=1),
                        matched_nodes=[
                            {
                                "node_id": "entity:42",
                                "node_kind": "entity",
                                "label": "顾霜",
                                "properties": {"entity_type": "character"},
                            }
                        ],
                        path=["entity:42", "fact:test"],
                    )
                ]
            )
        if "case-1" in hidden_case_ids:
            return SearchResult()
        case = self.find_initial_case_candidates("")[0][0]
        return SearchResult(results=[case])

    def fetch_active_cases(self, ids):
        """2026-08-05 用于按输入案例 ID 返回活动案例"""
        case = self.find_initial_case_candidates("")[0][0]
        return [case] if ids == ["case-1"] else []

    def search_after(self, query, *, limit=50):
        """2026-08-06 用于记录并检索当前位置之后的后文"""
        del limit
        self.after_queries.append(query)
        return [
            AfterChunkSearchResult(chapter_id=2, chunk_id=20, excerpt="第二章命中"),
            AfterChunkSearchResult(chapter_id=4, chunk_id=40, excerpt="第四章命中"),
        ]

    def read_after_chunk(self, *, chapter_id, chunk_id):
        """2026-08-06 用于记录已由 search 授权的后文读取"""
        self.reads.append((chapter_id, chunk_id))
        return f"chapter={chapter_id} chunk={chunk_id}"


def _find_tool(tools: list, name: str):
    """2026-08-05 用于按工具名取得 LangChain 测试工具"""
    return next(candidate for candidate in tools if candidate.name == name)


def _ledger() -> AnnotationToolLedger:
    """2026-08-06 用于构造由 search 动态授权后文的工具账本"""
    return AnnotationToolLedger(
        current_chapter_id=1,
        current_chunk_ids=(10, 11),
    )


def test_search_switches_to_later_chunk_query_after_finish() -> None:
    """2026-08-06 用于验证 finish 后 search 返回后文章节与 chunk ID"""
    service = _QueryService()
    ledger = _ledger()
    tools = build_annotation_tools(service, ledger)
    ledger.freeze_business_results()

    payload = json.loads(_find_tool(tools, "search").invoke({"query": "顾霜"}))

    assert service.after_queries == ["顾霜"]
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


def test_fact_push_node_selector_requires_current_graph_search_visibility() -> None:
    """2026-08-06 用于验证常用节点 ID 必须由本轮图 search 明确返回"""
    service = _QueryService()
    ledger = _ledger()
    tools = build_annotation_tools(service, ledger)
    push = _find_tool(tools, "push")
    output = {
        "output_kind": "fact",
        "source_case_ids": [],
        "evidence": {"reason": "霜姐即顾霜", "chapterid": 1},
        "payload": {
            "fact_type": "relation",
            "subject": {"name": "霜姐", "entity_type": "character"},
            "predicate": "同一人物",
            "object": {"name": "顾霜", "entity_type": "character"},
            "value": None,
            "participants": [],
            "scope": "global",
            "story_time": None,
            "assertion": "affirmed",
            "confidence": "high",
            "directionality": "bidirectional",
            "relation_semantics": "same_character",
            "representative_node": {"node_id": "entity:42"},
        },
    }

    with pytest.raises(AnnotationAuthorizationError, match="未由本轮图 search 返回"):
        push.invoke({"outputs": [output]})

    _find_tool(tools, "search").invoke({"query": "图节点"})
    payload = json.loads(push.invoke({"outputs": [output]}))

    assert payload["staged_count"] == 1
    assert ledger.visible_graph_entity_node_ids == {"entity:42"}
