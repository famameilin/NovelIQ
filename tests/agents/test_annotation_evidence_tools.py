"""章节 Agent pull push 与后文授权工具测试"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.agents.annotation.errors import AnnotationAuthorizationError, AnnotationProtocolError
from src.agents.annotation.schema import (
    ActiveCaseDetails,
    CaseSearchResult,
    GraphSearchEntity,
    GraphSearchFact,
    GraphSearchResult,
    PushCase,
    SearchResult,
    TextEvidence,
    TextSearchResult,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


class _QueryService:
    """2026-08-07 用于记录 pull push 与原文工具调用的测试查询服务"""

    def __init__(self) -> None:
        """2026-08-07 用于初始化原文查询范围与读取记录"""
        self.text_queries: list[tuple[str, str]] = []
        self.reads: list[int] = []

    def _case(self) -> CaseSearchResult:
        """2026-08-07 用于构造一个可严格解决的活动案例"""
        return CaseSearchResult(
            id="case-1",
            type="dialogue_speaker",
            chunkid=10,
            keys=["住手", "说话人"],
            description="该句住手由谁说出",
            evidence=[TextEvidence(reason="当前原文尚未明确", chunk_id=10)],
        )

    def find_initial_case_candidates(self, current_text, *, semantic_limit=50, rotation_limit=50):
        """2026-08-07 用于返回一个初始活动案例"""
        del current_text, semantic_limit, rotation_limit
        return [self._case()], ["case-1"]

    def search_pool(self, query, *, hidden_case_ids, limit=50):
        """2026-08-07 用于验证 pull 后案例从后续池搜索隐藏"""
        del query, limit
        if "case-1" in hidden_case_ids:
            return SearchResult()
        return SearchResult(results=[self._case()])

    def search_graph(self, query, *, limit=50):
        """2026-08-07 用于返回上一章节图版本中的实体与事实授权"""
        del query, limit
        return GraphSearchResult(
            graph_version_id="graph-version-1",
            facts=[
                GraphSearchFact(
                    fact_id="fact-1",
                    fact_revision=1,
                    fact_type="character_observation",
                    predicate="action",
                    effective_chunk_id=1,
                    content={"kind": "character_observation"},
                    evidence=[TextEvidence(reason="前章原文确认", chunk_id=1)],
                )
            ],
            entities=[
                GraphSearchEntity(
                    existing_entity_id=42,
                    name="顾霜",
                    entity_type="character",
                    state_revision=1,
                    state={"status": "active"},
                )
            ],
        )

    async def search_text(self, query, *, range_name, limit=50):
        """2026-08-07 用于记录范围并返回原文候选"""
        del limit
        self.text_queries.append((query, range_name))
        return [
            TextSearchResult(
                chapter_id=2,
                chunk_id=20,
                excerpt="顾霜喝道",
                keyword_score=1.0,
            )
        ]

    def read_text(self, chunk_id):
        """2026-08-07 用于记录已由文本搜索候选授权的原文读取"""
        self.reads.append(chunk_id)
        return "顾霜喝道"

    def fetch_active_case_details(self, case_id):
        """2026-08-07 用于返回包含内部稳定目标的 active 案例"""
        if case_id != "case-1":
            return None
        return ActiveCaseDetails(
            **self._case().model_dump(mode="python"),
            target_key="target-1",
            target_ref={
                "kind": "dialogue",
                "item_ref": "dialogue_1",
                "chunk_id": 10,
                "start": 1,
                "end": 3,
                "text": "住手",
                "fact_id": "fact-dialogue",
                "fact_revision": 1,
            },
        )


def _find_tool(tools: list, name: str):
    """2026-08-07 用于按工具名取得 LangChain 测试工具"""
    return next(candidate for candidate in tools if candidate.name == name)


def _ledger(*, allow_future_context: bool) -> AnnotationToolLedger:
    """2026-08-07 用于构造带 current 原文和后文开关的工具账本"""
    return AnnotationToolLedger(
        current_chapter_id=1,
        current_chunks={10: "“住手”回荡", 11: "众人沉默"},
        allow_future_context=allow_future_context,
    )


def _tools(service: _QueryService, ledger: AnnotationToolLedger) -> list:
    """2026-08-07 用于构建带稳定 run scope 的测试工具"""
    return build_annotation_tools(service, ledger, run_scope="run-1")


def test_push_schema_rejects_old_output_wrapper() -> None:
    """2026-08-07 用于验证 push 只接受固定案例结构"""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PushCase.model_validate(
            {
                "description": "该句住手由谁说出",
                "keys": ["住手", "说话人"],
                "type": "dialogue_speaker",
                "chunkid": 10,
                "output_kind": "case",
            }
        )


@pytest.mark.asyncio
async def test_future_disabled_rejects_all_future_text_capabilities() -> None:
    """2026-08-07 用于验证关闭开关时 future 搜索读取都不可用"""
    service = _QueryService()
    ledger = _ledger(allow_future_context=False)
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationAuthorizationError, match="range 必须为 previous"):
        await _find_tool(tools, "search_text").ainvoke(
            {"query": "顾霜", "range": "future"}
        )
    ledger.set_phase("future_open")
    with pytest.raises(AnnotationAuthorizationError, match="allow_future_context=false"):
        await _find_tool(tools, "search_text").ainvoke(
            {"query": "顾霜", "range": "future"}
        )


@pytest.mark.asyncio
async def test_future_enabled_search_then_read_authorizes_pull_evidence() -> None:
    """2026-08-07 用于验证开启开关后 future 原文可确认案例并独立 pull"""
    service = _QueryService()
    ledger = _ledger(allow_future_context=True)
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    tools = _tools(service, ledger)
    ledger.set_phase("future_open")

    payload = json.loads(
        await _find_tool(tools, "search_text").ainvoke(
            {"query": "顾霜", "range": "future"}
        )
    )
    assert payload[0]["chunk_id"] == 20
    assert _find_tool(tools, "read_text").invoke({"chunk_id": 20}) == "顾霜喝道"
    pull_payload = json.loads(
        _find_tool(tools, "pull").invoke(
            {
                "case_id": "case-1",
                "type": "dialogue_speaker",
                "resolution": {
                    "speaker": {
                        "name": "顾霜",
                        "entity_type": "character",
                    },
                    "evidence_chunkid": 20,
                },
            }
        )
    )

    assert pull_payload == {"accepted": True, "case_id": "case-1"}
    assert ledger.pulled_results[0].target_ref["fact_id"] == "fact-dialogue"
    assert json.loads(_find_tool(tools, "search_pool").invoke({"query": "住手"}))["results"] == []


def test_pull_requires_case_type_and_authorized_evidence_chunk() -> None:
    """2026-08-07 用于验证 pull 按案例 type 严格校验 resolution"""
    service = _QueryService()
    ledger = _ledger(allow_future_context=False)
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationAuthorizationError, match="evidence_chunkid 未经"):
        _find_tool(tools, "pull").invoke(
            {
                "case_id": "case-1",
                "type": "dialogue_speaker",
                "resolution": {
                    "speaker": {
                        "name": "顾霜",
                        "entity_type": "character",
                    },
                    "evidence_chunkid": 20,
                },
            }
        )


def test_push_is_current_only_when_future_disabled_and_binds_stable_anchor() -> None:
    """2026-08-07 用于验证关闭开关时 push 只暂存唯一 current 对话目标"""
    service = _QueryService()
    ledger = _ledger(allow_future_context=False)
    tools = _tools(service, ledger)
    payload = json.loads(
        _find_tool(tools, "push").invoke(
            {
                "description": "该句住手由谁说出",
                "keys": ["住手", "说话人"],
                "type": "dialogue_speaker",
                "chunkid": 10,
            }
        )
    )

    assert payload["accepted"] is True
    assert ledger.staged_push_cases[0].target_anchor.text == "住手"
    ledger.set_phase("future_open")
    with pytest.raises(AnnotationProtocolError, match="不允许 push"):
        _find_tool(tools, "push").invoke(
            {
                "description": "重复",
                "keys": ["住手", "说话人"],
                "type": "dialogue_speaker",
                "chunkid": 10,
            }
        )


def test_future_enabled_rejects_push_before_future_phase() -> None:
    """2026-08-07 用于验证开启开关时 push 只保留全部 future 后仍未解决案例"""
    service = _QueryService()
    ledger = _ledger(allow_future_context=True)
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationProtocolError, match="不允许 push"):
        _find_tool(tools, "push").invoke(
            {
                "description": "该句住手由谁说出",
                "keys": ["住手", "说话人"],
                "type": "dialogue_speaker",
                "chunkid": 10,
            }
        )

    ledger.set_phase("future_open")
    payload = json.loads(
        _find_tool(tools, "push").invoke(
            {
                "description": "该句住手由谁说出",
                "keys": ["住手", "说话人"],
                "type": "dialogue_speaker",
                "chunkid": 10,
            }
        )
    )
    assert payload["accepted"] is True
