"""
诊断 Agent 单元测试

- 图循环：agent 调用 finish 提交 CloudAnalysis
- 校验失败重试
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.diagnosis.runner import (
    DiagnosisAgentRunError,
    _finalize_diagnosis_result,
    _validate_topic_label_count,
    run_diagnosis_agent,
)
from src.agents.graph import build_agent_graph
from src.models.cloud.schema import CloudAnalysis


def _analysis_payload() -> dict:
    return {
        "novel_id": "n1",
        "foreshadow_expectation": 0.35,
        "arc_scores": {"开局": 6.0, "发展": 7.5, "高潮": 8.0, "结局": 7.0, "顾霜": 8.0, "贺重明": 6.5},
        "genre_labels": ["玄幻"],
        "style_labels": ["爽文"],
        "topic_labels": ["成长", "复仇"],
        "diagnosis": "结构完整，节奏张弛有度",
        "value_logic_type": "强者为王",
        "power_stance_score": 4,
        "power_stance_reason": "主角始终保持主动",
        "common_people_dignity": 3,
        "dignity_reason": "配角有独立性",
        "cultural_depth_score": 3,
        "cultural_depth_reason": "世界观有层次",
        "narrative_arc_type": "三幕式",
        "focus_structure": "single",
        "focus_characters": ["顾霜"],
        "main_characters": ["顾霜", "贺重明"],
        "core_cast": ["顾霜", "贺重明"],
    }


class _FinishOnlyLLM:
    def __init__(self, payload: dict, *, first_bad: bool = False, wrapped: bool = True) -> None:
        self.payload = payload
        self.first_bad = first_bad
        self.wrapped = wrapped
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.first_bad and self.calls == 1:
            bad = dict(self.payload)
            bad["power_stance_score"] = 99
            args = {"analysis": bad} if self.wrapped else bad
            return AIMessage(
                content="",
                tool_calls=[{"name": "finish", "args": args, "id": "c1", "type": "tool_call"}],
            )
        args = {"analysis": self.payload} if self.wrapped else self.payload
        return AIMessage(
            content="",
            tool_calls=[{"name": "finish", "args": args, "id": "c1", "type": "tool_call"}],
        )


class _EvidenceThenFinishLLM(_FinishOnlyLLM):
    """先调用取证工具再提交诊断的测试模型"""

    async def ainvoke(self, messages):
        """
        2026-08-04 用于模拟诊断 Agent 的合法取证后 finish 调用序列
        """
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_aggregate_signals",
                        "args": {},
                        "id": "get-signals",
                        "type": "tool_call",
                    }
                ],
            )
        args = {"analysis": self.payload} if self.wrapped else self.payload
        return AIMessage(
            content="",
            tool_calls=[{"name": "finish", "args": args, "id": "finish", "type": "tool_call"}],
        )


class _CapturingRetryLLM(_FinishOnlyLLM):
    """先提交非法 finish 再重试，并捕获第二次收到的完整消息序列"""

    def __init__(self, payload: dict) -> None:
        super().__init__(payload, first_bad=True, wrapped=False)
        self.captured_messages: list | None = None

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            bad = dict(self.payload)
            bad["power_stance_score"] = 99
            return AIMessage(
                content="",
                tool_calls=[{"name": "finish", "args": bad, "id": "c1", "type": "tool_call"}],
            )
        self.captured_messages = list(messages)
        return AIMessage(
            content="",
            tool_calls=[{"name": "finish", "args": self.payload, "id": "c1", "type": "tool_call"}],
        )


@pytest.mark.asyncio
async def test_diagnosis_agent_produces_cloud_analysis() -> None:
    graph = build_agent_graph(
        _FinishOnlyLLM(_analysis_payload(), wrapped=False),
        [],
        max_attempts=5,
        response_model=CloudAnalysis,
        first_hint="完成诊断",
    )

    from langchain_core.messages import HumanMessage, SystemMessage

    result = await graph.ainvoke(
        {
            "messages": [SystemMessage(content="sys"), HumanMessage(content="诊断")],
            "attempts": 0,
            "output": None,
            "error": None,
        }
    )

    assert result.get("error") is None
    analysis = CloudAnalysis.model_validate(result["output"])
    assert analysis.genre_labels == ["玄幻"]
    assert analysis.style_labels == ["爽文"]
    assert analysis.foreshadow_expectation == 0.35


@pytest.mark.asyncio
async def test_diagnosis_agent_retries_on_invalid_output() -> None:
    llm = _FinishOnlyLLM(_analysis_payload(), first_bad=True, wrapped=False)
    graph = build_agent_graph(
        llm,
        [],
        max_attempts=5,
        response_model=CloudAnalysis,
        first_hint="完成诊断",
    )

    from langchain_core.messages import HumanMessage, SystemMessage

    result = await graph.ainvoke(
        {
            "messages": [SystemMessage(content="sys"), HumanMessage(content="诊断")],
            "attempts": 0,
            "output": None,
            "error": None,
        }
    )

    assert result.get("error") is None
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_retry_answers_every_pending_tool_call_with_tool_message() -> None:
    """
    2026-08-09 用于保证校验失败重试时最后 AIMessage 的每条 tool_call
    都有紧随的 ToolMessage 响应，避免真实 OpenAI 400 tool_calls 悬空
    """
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

    llm = _CapturingRetryLLM(_analysis_payload())
    graph = build_agent_graph(
        llm,
        [],
        max_attempts=5,
        response_model=CloudAnalysis,
        first_hint="完成诊断",
    )

    result = await graph.ainvoke(
        {
            "messages": [SystemMessage(content="sys"), HumanMessage(content="诊断")],
            "attempts": 0,
            "output": None,
            "error": None,
        }
    )

    assert result.get("error") is None
    assert llm.calls == 2
    assert llm.captured_messages is not None
    messages = llm.captured_messages
    for message, next_message in zip(messages, messages[1:], strict=False):
        if not isinstance(message, AIMessage) or not message.tool_calls:
            continue
        for call in message.tool_calls:
            assert isinstance(next_message, ToolMessage)
            assert next_message.tool_call_id == call["id"]
            assert next_message.name == call["name"]


@pytest.mark.asyncio
async def test_truncated_tool_call_skips_invoke_and_returns_error_tool_message() -> None:
    """
    2026-08-11 用于验证通用图对截断标记调用不执行业务工具，
    直接生成错误 ToolMessage 回喂模型，模型修正后正常完成。
    """
    from unittest.mock import AsyncMock, MagicMock

    from langchain_core.messages import HumanMessage, SystemMessage

    tool = MagicMock()
    tool.name = "get_aggregate_signals"
    tool.ainvoke = AsyncMock()

    class _TruncatedThenFinishLLM(_FinishOnlyLLM):
        def __init__(self, payload: dict) -> None:
            super().__init__(payload)
            self.captured_messages: list[list] = []

        async def ainvoke(self, messages):
            self.calls += 1
            self.captured_messages.append(list(messages))
            if self.calls == 1:
                # 聚合器在运行时以属性赋值挂载截断标记（绕过 create_tool_call 重建）
                message = AIMessage(content="")
                message.tool_calls = [
                    {
                        "name": "get_aggregate_signals",
                        "args": {},
                        "id": "get-signals",
                        "type": "tool_call",
                        "truncated": True,
                        "truncated_args": '{"metric": "sig',
                    }
                ]
                return message
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "finish",
                        "args": {"analysis": self.payload},
                        "id": "finish",
                        "type": "tool_call",
                    }
                ],
            )

    llm = _TruncatedThenFinishLLM(_analysis_payload())
    graph = build_agent_graph(
        llm,
        [tool],
        max_attempts=5,
        response_model=CloudAnalysis,
        first_hint="完成诊断",
    )

    result = await graph.ainvoke(
        {
            "messages": [SystemMessage(content="sys"), HumanMessage(content="诊断")],
            "attempts": 0,
            "output": None,
            "error": None,
        }
    )

    assert result.get("error") is None
    assert llm.calls == 2
    tool.ainvoke.assert_not_awaited()
    second_round = llm.captured_messages[1]
    error_messages = [
        str(message.content)
        for message in second_round
        if getattr(message, "type", "") == "tool" and "Error" in str(message.content)
    ]
    assert len(error_messages) == 1
    assert "截断" in error_messages[0]


@pytest.mark.asyncio
async def test_run_diagnosis_agent_requires_run_scoped_tools() -> None:
    """run_diagnosis_agent 装配诊断工具并输出 CloudAnalysis"""
    mock_session = MagicMock()
    payload = _analysis_payload()
    payload["novel_id"] = "model-invented-id"
    payload["foreshadow_expectation"] = 0.99
    llm = _EvidenceThenFinishLLM(payload)
    diagnosis_repo = MagicMock()
    diagnosis_repo.fetch_topic_words.return_value = [{"topic_id": 0}, {"topic_id": 1}]
    diagnosis_repo.calculate_foreshadow_expectation.return_value = 0.62

    with patch(
        "src.agents.diagnosis.runner.DiagnosisRepository",
        return_value=diagnosis_repo,
    ):
        analysis = await run_diagnosis_agent(
            session=mock_session,
            run_id="run-1",
            novel_id="n1",
            llm=llm,
            audit_recorder=MagicMock(),
        )

    assert isinstance(analysis, CloudAnalysis)
    assert analysis.genre_labels == ["玄幻"]
    assert analysis.novel_id == "n1"
    assert analysis.foreshadow_expectation == 0.62


@pytest.mark.asyncio
async def test_run_diagnosis_agent_rejects_finish_without_evidence_tool() -> None:
    """
    2026-08-04 用于保证诊断 Agent 不能绕过工具取证直接提交结果
    """
    mock_session = MagicMock()
    diagnosis_repo = MagicMock()
    diagnosis_repo.fetch_topic_words.return_value = [{"topic_id": 0}, {"topic_id": 1}]
    diagnosis_repo.calculate_foreshadow_expectation.return_value = 0.62

    with patch("src.agents.diagnosis.runner.DiagnosisRepository", return_value=diagnosis_repo):
        with pytest.raises(DiagnosisAgentRunError, match="必须至少调用一个证据工具"):
            await run_diagnosis_agent(
                session=mock_session,
                run_id="run-1",
                novel_id="n1",
                llm=_FinishOnlyLLM(_analysis_payload()),
                audit_recorder=MagicMock(),
            )


def test_validate_topic_label_count_rejects_mismatch() -> None:
    """
    2026-08-02 用于拒绝主题标签数量与实际主题数据不一致的诊断结果
    """
    analysis = CloudAnalysis.model_validate(_analysis_payload())

    with pytest.raises(ValueError, match="expected 3, got 2"):
        _validate_topic_label_count(analysis, expected_count=3)


def test_finalize_diagnosis_result_overrides_model_owned_runtime_fields() -> None:
    """
    2026-08-02 用于验证诊断终态由真实 novel_id 与伏笔 ledger 确定
    """
    payload = _analysis_payload()
    payload["novel_id"] = "wrong"
    payload["foreshadow_expectation"] = 0.99

    finalized = _finalize_diagnosis_result(
        CloudAnalysis.model_validate(payload),
        novel_id="novel-real",
        foreshadow_expectation=0.41,
    )

    assert finalized.novel_id == "novel-real"
    assert finalized.foreshadow_expectation == 0.41


def test_diagnosis_context_summary_carries_evidence_keys() -> None:
    """
    2026-08-10 用于保证诊断回合的确定性上下文摘要携带证据工具键
    """
    from src.agents.diagnosis.evidence import DiagnosisEvidenceLedger
    from src.agents.diagnosis.runner import _context_summary

    ledger = DiagnosisEvidenceLedger(tool_calls=["get_aggregate_signals"])
    summary = _context_summary(ledger)({"attempts": 2, "tool_iterations": 3, "output": None, "error": None})

    assert summary["phase"] == "diagnosis"
    assert summary["attempts"] == 2
    assert summary["tool_iterations"] == 3
    assert summary["evidence"] == {"tool_calls": ["get_aggregate_signals"]}


def test_diagnosis_prompt_matches_current_schema_semantics() -> None:
    """
    2026-08-04 用于保证提示词把 arc_scores 与 style_labels 约束为当前 Schema 合同
    """
    from src.agents.diagnosis.prompts import build_diagnosis_system_prompt

    prompt = build_diagnosis_system_prompt("测试小说")

    assert "key 必须是角色规范名" in prompt
    assert "硬核/史诗/哲思" in prompt
