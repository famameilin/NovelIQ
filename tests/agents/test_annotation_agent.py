"""章节级标注 Agent 新合同测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from src.agents.annotation.errors import AnnotationAuthorizationError
from src.agents.annotation.graph import build_annotation_graph
from src.agents.annotation.runner import (
    AnnotationAgentRunError,
    run_annotation_agent,
    validate_chapter_finish,
)
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    ChapterFinish,
    GraphEvidence,
    SuccessAudit,
    TextEvidence,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


def _coverage(chunk_id: int) -> dict:
    """2026-08-07 用于构造声明全部领域已检查的 coverage"""
    return {
        "chunk_id": chunk_id,
        "entities": True,
        "character_observations": True,
        "location_observations": True,
        "dialogues": True,
        "events": True,
        "relations": True,
        "states": True,
        "foreshadowings": True,
    }


def _finish_payload(*, summary: str = "顾霜进入山门") -> dict:
    """2026-08-07 用于构造最小完整 ChapterFinish 参数"""
    return {
        "chapter_summary": summary,
        "entities": {
            "characters": [],
            "locations": [],
            "objects": [],
            "organizations": [],
        },
        "chunks": [
            {
                "chunk_id": 1,
                "summary": "顾霜进入山门",
                "metrics": {
                    "emotional_valence": "neutral",
                    "event_type": "铺垫",
                    "pivot_moment": False,
                    "cliffhanger": False,
                },
                "character_observations": [],
                "location_observations": [],
                "dialogues": [],
                "events": [],
                "relations": [],
                "states": [],
                "foreshadowings": [],
            }
        ],
        "coverage": [_coverage(1)],
    }


class _QueryService:
    """2026-08-07 用于提供无数据库依赖的新合同查询桩"""

    def find_initial_case_candidates(self, current_text, *, semantic_limit=50, rotation_limit=50):
        """2026-08-07 用于返回空初始案例集合"""
        del current_text, semantic_limit, rotation_limit
        return [], []

    def search_pool(self, query, *, hidden_case_ids, limit=50):
        """2026-08-07 用于返回空案例与伏笔检索结果"""
        from src.agents.annotation.schema import SearchResult

        del query, hidden_case_ids, limit
        return SearchResult()

    def search_graph(self, query, *, limit=50):
        """2026-08-07 用于返回无上一章节图版本"""
        del query, limit
        return None

    async def search_text(self, query, *, range_name, limit=50):
        """2026-08-07 用于返回空原文候选"""
        del query, range_name, limit
        return []

    def read_text(self, chunk_id):
        """2026-08-07 用于返回测试原文"""
        del chunk_id
        return "后文"

    def fetch_active_case_details(self, case_id):
        """2026-08-07 用于表示测试中没有 active 案例"""
        del case_id
        return None


class _SequenceLLM:
    """2026-08-07 用于按顺序返回 Agent 消息的测试模型"""

    def __init__(self, responses: list[AIMessage]) -> None:
        """2026-08-07 用于保存待返回的模型消息序列"""
        self.responses = list(responses)
        self.calls = 0

    def bind_tools(self, tools):
        """2026-08-07 用于模拟 LangChain 工具绑定"""
        del tools
        return self

    async def ainvoke(self, messages):
        """2026-08-07 用于返回下一条测试模型消息"""
        del messages
        self.calls += 1
        return self.responses.pop(0)


def _finish_message(payload: dict, *, call_id: str = "finish-1") -> AIMessage:
    """2026-08-07 用于构造唯一 finish 工具调用消息"""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "finish",
                "args": {"annotation": payload},
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def _revise_message(correction: dict, *, call_id: str = "revise-1") -> AIMessage:
    """2026-08-07 用于构造唯一 revise_finish 工具调用消息"""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "revise_finish",
                "args": {"correction": correction},
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


async def _invoke_graph(
    llm: _SequenceLLM,
    *,
    allow_future_context: bool,
) -> dict:
    """2026-08-07 用于执行最小新合同章节 LangGraph"""
    ledger = AnnotationToolLedger(
        current_chapter_id=1,
        current_chunks={1: "顾霜进入山门"},
        allow_future_context=allow_future_context,
    )
    tools = build_annotation_tools(_QueryService(), ledger, run_scope="run-1")
    graph = build_annotation_graph(
        llm,
        tools,
        ledger=ledger,
        max_iterations=8,
        current_validator=lambda finish: None,
        future_validator=lambda finish: None,
    )
    return await graph.ainvoke(
        {
            "messages": [SystemMessage(content="test"), HumanMessage(content="current")],
            "phase": "current_open",
            "iterations": 0,
            "candidate": None,
            "initial_finish": None,
            "final_finish": None,
            "revision_payloads": [],
            "error": None,
        }
    )


def _agent_result() -> AgentRunResult:
    """2026-08-07 用于构造 Runner 重试测试的完整成功结果"""
    finish = ChapterFinish.model_validate(_finish_payload())
    return AgentRunResult(
        run_id="run-1",
        chapter_id=1,
        finish=finish,
        pulled_results=[],
        pushed_cases=[],
        audit=AgentRunAudit(
            allow_future_context=False,
            initial_finish=finish,
            revision_payloads=[],
            initial_case_candidate_ids=[],
            rotation_case_ids=[],
            authorized_text_chunk_ids=[1],
            visible_graph_fact_refs=[],
            visible_graph_entity_ids=[],
            visible_graph_relation_ids=[],
            success=SuccessAudit(
                attempt_number=1,
                messages=[],
                tool_calls=[],
                model_provider="local",
                duration_ms=1,
            ),
        ),
    )


def test_evidence_rejects_extra_fields() -> None:
    """2026-08-07 用于验证双源 Evidence 拒绝旧合同字段"""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TextEvidence.model_validate({"reason": "依据", "chunk_id": 2, "chapterid": 1})
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GraphEvidence.model_validate(
            {
                "reason": "前序事实",
                "fact_id": "fact-1",
                "fact_revision": 1,
                "excerpt": "旧搜索结果",
            }
        )


def test_finish_requires_fact_arrays_and_coverage() -> None:
    """2026-08-07 用于验证只有摘要指标的 finish 不能成为完整事实标注"""
    payload = _finish_payload()
    del payload["coverage"]
    del payload["chunks"][0]["relations"]

    with pytest.raises(ValidationError):
        ChapterFinish.model_validate(payload)


def test_validate_finish_requires_exact_chunk_and_coverage_order() -> None:
    """2026-08-07 用于验证 chunks coverage 精确覆盖全部 current"""
    finish = ChapterFinish.model_validate(_finish_payload())
    validate_chapter_finish(
        finish,
        chapter_id=1,
        current_chunks=[(1, "顾霜进入山门")],
        authorized_text_chunk_ids={1},
        visible_graph_fact_refs=set(),
        visible_graph_entities={},
        visible_graph_relation_ids=set(),
        visible_setup_ids=set(),
    )
    invalid = finish.model_copy(
        update={"coverage": [finish.coverage[0].model_copy(update={"chunk_id": 2})]}
    )
    with pytest.raises(ValueError, match="coverage 必须"):
        validate_chapter_finish(
            invalid,
            chapter_id=1,
            current_chunks=[(1, "顾霜进入山门")],
            authorized_text_chunk_ids={1},
            visible_graph_fact_refs=set(),
            visible_graph_entities={},
            visible_graph_relation_ids=set(),
            visible_setup_ids=set(),
        )


def test_location_relation_target_must_be_location() -> None:
    """2026-08-07 用于验证 located_at 目标只能引用地点节点"""
    payload = _finish_payload()
    payload["entities"]["characters"] = [
        {
            "ref": "character_1",
            "name": "顾霜",
            "existing_entity_id": None,
            "mentions": [{"chunk_id": 1, "start": 0, "end": 2, "text": "顾霜"}],
            "confidence": "high",
            "evidence": [{"reason": "人物出现", "chunk_id": 1}],
        },
        {
            "ref": "character_2",
            "name": "山门",
            "existing_entity_id": None,
            "mentions": [{"chunk_id": 1, "start": 4, "end": 6, "text": "山门"}],
            "confidence": "high",
            "evidence": [{"reason": "误标为人物", "chunk_id": 1}],
        },
    ]
    payload["chunks"][0]["relations"] = [
        {
            "ref": "relation_1",
            "confidence": "high",
            "evidence": [{"reason": "顾霜进入山门", "chunk_id": 1}],
            "from_ref": "character_1",
            "to_ref": "character_2",
            "relation_type": "located_at",
            "change_kind": "assert",
        }
    ]
    finish = ChapterFinish.model_validate(payload)

    with pytest.raises(ValueError, match="必须引用 location"):
        validate_chapter_finish(
            finish,
            chapter_id=1,
            current_chunks=[(1, "顾霜进入山门")],
            authorized_text_chunk_ids={1},
            visible_graph_fact_refs=set(),
            visible_graph_entities={},
            visible_graph_relation_ids=set(),
            visible_setup_ids=set(),
        )


@pytest.mark.asyncio
async def test_future_disabled_finishes_immediately() -> None:
    """2026-08-07 用于验证关闭后文开关时首份有效 finish 直接结束"""
    llm = _SequenceLLM([_finish_message(_finish_payload())])
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result["final_finish"] == _finish_payload()
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_future_enabled_can_revise_by_ref_and_continue_until_no_tools() -> None:
    """2026-08-07 用于验证 future 修正后继续开放并由无工具响应结束"""
    payload = _finish_payload()
    payload["chunks"][0]["states"] = [
        {
            "ref": "state_1",
            "confidence": "high",
            "evidence": [{"reason": "状态", "chunk_id": 1}],
            "entity_existing_entity_id": 42,
            "predicate": "status",
            "value": "unknown",
        }
    ]
    llm = _SequenceLLM(
        [
            _finish_message(payload),
            _revise_message(
                {
                    "chunks": [
                        {
                            "chunk_id": 1,
                            "upsert_states": [
                                {
                                    "ref": "state_1",
                                    "confidence": "high",
                                    "evidence": [{"reason": "后文确认", "chunk_id": 2}],
                                    "entity_existing_entity_id": 42,
                                    "predicate": "status",
                                    "value": "confirmed",
                                }
                            ],
                        }
                    ]
                }
            ),
            AIMessage(content="完成"),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=True)

    assert result["phase"] == "completed"
    assert result["final_finish"]["chunks"][0]["states"][0]["value"] == "confirmed"
    assert len(result["revision_payloads"]) == 1
    assert llm.calls == 3


@pytest.mark.asyncio
async def test_runner_stops_after_third_retryable_failure() -> None:
    """2026-08-07 用于验证第三次失败后终止且每次使用全新只读 Session"""
    sessions = [MagicMock(), MagicMock(), MagicMock()]
    with (
        patch(
            "src.agents.annotation.runner._run_single_attempt",
            new=AsyncMock(side_effect=RuntimeError("model failed")),
        ) as run_attempt,
        patch("src.agents.annotation.runner.asyncio.sleep", new=AsyncMock()) as sleep,
    ):
        with pytest.raises(AnnotationAgentRunError, match="连续 3 次失败"):
            await run_annotation_agent(
                run_id="run-1",
                chapter_id=1,
                current_chunks=[(1, "顾霜进入山门")],
                query_service_factory=lambda session: _QueryService(),
                session_factory=lambda: sessions.pop(0),
                llm=MagicMock(),
            )
    assert run_attempt.await_count == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_runner_does_not_retry_authorization_errors() -> None:
    """2026-08-07 用于验证授权错误直接失败且不会进入第二次尝试"""
    session = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(side_effect=AnnotationAuthorizationError("unauthorized")),
    ) as run_attempt:
        with pytest.raises(AnnotationAuthorizationError, match="unauthorized"):
            await run_annotation_agent(
                run_id="run-1",
                chapter_id=1,
                current_chunks=[(1, "顾霜进入山门")],
                query_service_factory=lambda current: _QueryService(),
                session_factory=lambda: session,
                llm=MagicMock(),
            )
    assert run_attempt.await_count == 1
    session.rollback.assert_called_once()
    session.close.assert_called_once()


@pytest.mark.asyncio
async def test_runner_retries_then_returns_successful_third_attempt() -> None:
    """2026-08-07 用于验证可重试错误后返回第三次成功结果"""
    result = _agent_result()
    sessions = [MagicMock(), MagicMock(), MagicMock()]
    llm = MagicMock()
    with (
        patch(
            "src.agents.annotation.runner._run_single_attempt",
            new=AsyncMock(side_effect=[RuntimeError("one"), RuntimeError("two"), result]),
        ) as run_attempt,
        patch("src.agents.annotation.runner.asyncio.sleep", new=AsyncMock()),
    ):
        actual = await run_annotation_agent(
            run_id="run-1",
            chapter_id=1,
            current_chunks=[(1, "顾霜进入山门")],
            query_service_factory=lambda session: _QueryService(),
            session_factory=lambda: sessions.pop(0),
            llm=llm,
        )
    assert actual == result
    assert run_attempt.await_count == 3
