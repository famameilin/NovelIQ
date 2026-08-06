"""章节级标注 Agent 合同测试"""

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
    validate_chapter_annotation,
)
from src.agents.annotation.schema import (
    AgentRunResult,
    CasePayload,
    ChapterAnnotation,
    Evidence,
    FactPayload,
    SuccessAudit,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


def _annotation_payload(*, summary: str = "顾霜进入山门") -> dict:
    """2026-08-05 用于构造章节 Agent 的最小完整 finish 参数"""
    return {
        "chapter_summary": summary,
        "segments": [
            {
                "chunk_id": 1,
                "summary": "顾霜进入山门",
                "emotional_valence": "neutral",
                "event_type": "铺垫",
                "pivot_moment": False,
                "cliffhanger": False,
            }
        ],
        "characters": [],
        "locations": [],
        "dialogues": [],
        "events": [],
        "relations": [],
        "states": [],
    }


class _QueryService:
    """2026-08-05 用于提供无数据库依赖的章节 Agent 查询桩"""

    def find_initial_case_candidates(self, current_text, *, semantic_limit=50, rotation_limit=50):
        """2026-08-05 用于返回空初始案例集合"""
        del current_text, semantic_limit, rotation_limit
        return [], []

    def search_continuity(self, query, *, hidden_case_ids, limit=50):
        """2026-08-05 用于返回空连续性检索结果"""
        from src.agents.annotation.schema import SearchResult

        del query, hidden_case_ids, limit
        return SearchResult()

    def fetch_active_cases(self, ids):
        """2026-08-05 用于返回空案例回读结果"""
        del ids
        return []

    def search_after(self, query, *, limit=50):
        """2026-08-05 用于返回空后文检索结果"""
        del query, limit
        return []

    def read_after_chunk(self, *, chapter_id, chunk_id):
        """2026-08-05 用于返回测试后文原文"""
        del chapter_id, chunk_id
        return "后文"


class _SequenceLLM:
    """2026-08-05 用于按顺序返回 Agent 消息的测试模型"""

    def __init__(self, responses: list[AIMessage]) -> None:
        """2026-08-05 用于保存待返回的模型消息序列"""
        self.responses = list(responses)
        self.calls = 0

    def bind_tools(self, tools):
        """2026-08-05 用于模拟 LangChain 工具绑定"""
        del tools
        return self

    async def ainvoke(self, messages):
        """2026-08-05 用于返回下一条测试模型消息"""
        del messages
        self.calls += 1
        return self.responses.pop(0)


def _finish_message(payload: dict, *, call_id: str = "finish-1") -> AIMessage:
    """2026-08-05 用于构造唯一 finish 工具调用消息"""
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
    """2026-08-05 用于构造唯一 revise_finish 工具调用消息"""
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


async def _invoke_graph(llm: _SequenceLLM) -> dict:
    """2026-08-05 用于执行一轮最小章节专用 LangGraph"""
    ledger = AnnotationToolLedger(
        current_chapter_id=1,
        current_chunk_ids=(1,),
    )
    tools = build_annotation_tools(_QueryService(), ledger)
    graph = build_annotation_graph(
        llm,
        tools,
        ledger=ledger,
        max_iterations=8,
        initial_validator=lambda annotation, allowed: None,
        post_after_validator=lambda annotation, allowed: None,
    )
    return await graph.ainvoke(
        {
            "messages": [SystemMessage(content="test"), HumanMessage(content="current")],
            "phase": "running_current",
            "iterations": 0,
            "candidate": None,
            "initial_finish": None,
            "final_annotation": None,
            "revision_payload": {},
            "error": None,
        }
    )


def _agent_result() -> AgentRunResult:
    """2026-08-05 用于构造 Runner 重试测试的完整成功结果"""
    annotation = ChapterAnnotation.model_validate(_annotation_payload())
    return AgentRunResult(
        run_id="run-1",
        chapter_id=1,
        final_annotation=annotation,
        initial_finish=annotation,
        revision_payload={},
        initial_case_candidate_ids=[],
        rotation_case_ids=[],
        pulled_case_ids=[],
        staged_outputs=[],
        success_audit=SuccessAudit(
            attempt_number=1,
            messages=[],
            tool_calls=[],
            model_provider="local",
            duration_ms=1,
        ),
    )


def test_evidence_rejects_extra_fields() -> None:
    """2026-08-05 用于验证 Evidence 永远只有 reason 与 chapterid"""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Evidence.model_validate({"reason": "依据", "chapterid": 1, "chunk_id": 2})


def test_case_description_counts_unicode_characters() -> None:
    """2026-08-05 用于验证案例描述长度按 Unicode 字符限制为一百"""
    accepted = CasePayload(keys=["身份"], description="甲" * 100)
    assert len(accepted.description) == 100
    with pytest.raises(ValidationError):
        CasePayload(keys=["身份"], description="甲" * 101)


def test_fact_payload_rejects_record_version_fields() -> None:
    """2026-08-06 用于验证 fact 只描述图节点关系与属性"""
    payload = {
        "fact_type": "membership",
        "subject": {"name": "顾霜", "entity_type": "character"},
        "predicate": "belongs_to",
        "object": {"name": "山门", "entity_type": "location"},
        "value": None,
        "participants": [],
        "scope": "novel",
        "story_time": None,
        "assertion": "affirmed",
        "confidence": "high",
    }
    FactPayload.model_validate(payload)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FactPayload.model_validate({**payload, "record_version": 1})
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FactPayload.model_validate({**payload, "change_kind": "supersede"})


def test_fact_payload_requires_character_nodes_for_identity_relation() -> None:
    """2026-08-06 用于验证称谓身份只能形成独立人物节点关系并选择代表节点"""
    payload = {
        "fact_type": "relation",
        "subject": {"name": "霜姐", "entity_type": "character"},
        "predicate": "同一人物",
        "object": {"name": "顾霜", "entity_type": "character"},
        "value": None,
        "participants": [],
        "scope": "novel",
        "story_time": None,
        "assertion": "affirmed",
        "confidence": "high",
        "directionality": "bidirectional",
        "relation_semantics": "same_character",
        "representative_node": {"endpoint": "object"},
    }

    fact = FactPayload.model_validate(payload)

    assert fact.representative_node is not None
    assert fact.representative_node.endpoint == "object"
    with pytest.raises(ValidationError, match="同一人物关系必须选择"):
        FactPayload.model_validate({**payload, "representative_node": None})
    with pytest.raises(ValidationError, match="必须恰好选择"):
        FactPayload.model_validate(
            {
                **payload,
                "representative_node": {
                    "endpoint": "object",
                    "node_id": "entity:42",
                },
            }
        )
    with pytest.raises(ValidationError, match="String should match pattern"):
        FactPayload.model_validate(
            {
                **payload,
                "representative_node": {"node_id": "entity:0"},
            }
        )
    negated = FactPayload.model_validate(
        {
            **payload,
            "assertion": "negated",
            "representative_node": None,
        }
    )
    assert negated.assertion == "negated"
    with pytest.raises(ValidationError, match="否定同一人物关系不允许"):
        FactPayload.model_validate(
            {
                **payload,
                "assertion": "negated",
            }
        )


def test_chapter_annotation_node_selector_requires_current_graph_search_visibility() -> None:
    """2026-08-06 用于验证正式标注只能引用本轮图 search 返回的实体节点 ID"""
    payload = _annotation_payload()
    payload["relations"] = [
        {
            "chunk_id": 1,
            "evidence": {"reason": "霜姐即顾霜", "chapterid": 1},
            "confidence": "high",
            "from_entity": {"name": "霜姐", "entity_type": "character"},
            "to_entity": {"name": "顾霜", "entity_type": "character"},
            "relation_type": "同一人物",
            "change_kind": "assert",
            "directionality": "bidirectional",
            "relation_semantics": "same_character",
            "representative_node": {"node_id": "entity:42"},
        }
    ]
    annotation = ChapterAnnotation.model_validate(payload)

    with pytest.raises(AnnotationAuthorizationError, match="未由本轮图 search 返回"):
        validate_chapter_annotation(
            annotation,
            chapter_id=1,
            current_chunks=[(1, "霜姐即顾霜")],
            allowed_evidence_chapter_ids={1},
            visible_graph_entity_node_ids=set(),
        )

    validate_chapter_annotation(
        annotation,
        chapter_id=1,
        current_chunks=[(1, "霜姐即顾霜")],
        allowed_evidence_chapter_ids={1},
        visible_graph_entity_node_ids={"entity:42"},
    )


@pytest.mark.asyncio
async def test_graph_keeps_initial_finish_when_after_response_has_no_tools() -> None:
    """2026-08-05 用于验证 after 无工具响应时采用初始完整结果"""
    llm = _SequenceLLM([_finish_message(_annotation_payload()), AIMessage(content="保持")])
    result = await _invoke_graph(llm)
    assert result["phase"] == "completed"
    assert result["final_annotation"] == _annotation_payload()
    assert result["revision_payload"] == {}


@pytest.mark.asyncio
async def test_graph_merges_only_submitted_revise_fields_after_finish() -> None:
    """2026-08-05 用于验证 revise_finish 只覆盖实际提交字段并完整保留其余候选"""
    llm = _SequenceLLM(
        [
            _finish_message(_annotation_payload()),
            _revise_message({"chapter_summary": "后文确认顾霜进入山门"}),
        ]
    )
    result = await _invoke_graph(llm)
    assert result["phase"] == "completed"
    assert result["final_annotation"]["chapter_summary"] == "后文确认顾霜进入山门"
    assert result["final_annotation"]["segments"] == _annotation_payload()["segments"]
    assert result["revision_payload"] == {"chapter_summary": "后文确认顾霜进入山门"}


@pytest.mark.asyncio
async def test_graph_rejects_finish_during_after_phase() -> None:
    """2026-08-05 用于验证 after 阶段直接拒绝业务 finish 调用"""
    llm = _SequenceLLM(
        [
            _finish_message(_annotation_payload()),
            _finish_message(_annotation_payload(summary="非法再次提交"), call_id="finish-2"),
        ]
    )
    result = await _invoke_graph(llm)
    assert result["final_annotation"] is None
    assert "阶段 after_open 拒绝工具调用" in str(result["error"])


@pytest.mark.asyncio
async def test_runner_stops_after_third_retryable_failure() -> None:
    """2026-08-05 用于验证第三次失败后终止且每次使用全新只读 Session"""
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
    """2026-08-05 用于验证授权错误直接失败且不会进入第二次尝试"""
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
    """2026-08-05 用于验证可重试错误后仍使用同一模型返回第三次成功结果"""
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
    assert all(call.kwargs["llm"] is llm for call in run_attempt.await_args_list)
    assert [call.kwargs["attempt_number"] for call in run_attempt.await_args_list] == [1, 2, 3]
