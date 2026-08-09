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
    _record_diagnosis_interactions,
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


def test_record_diagnosis_interactions_records_each_model_response() -> None:
    """
    2026-08-04 用于保证诊断多轮取证与 finish 都形成独立模型交互审计
    """
    from src.agents.diagnosis.evidence import DiagnosisEvidenceLedger

    ledger = DiagnosisEvidenceLedger(tool_calls=["get_aggregate_signals"])
    llm = MagicMock(model_name="diagnosis-test")
    llm.base_url = "http://localhost:1234/v1"
    messages = [AIMessage(content="取证"), AIMessage(content="完成")]

    with patch("src.models.interactions.record_model_interaction") as record_interaction:
        _record_diagnosis_interactions(
            session=MagicMock(),
            run_id="run-1",
            novel_id="n1",
            llm=llm,
            messages=messages,
            raw_output=_analysis_payload(),
            evidence_ledger=ledger,
            elapsed=0.1,
        )

    assert record_interaction.call_count == 2
    assert [call.kwargs["attempt_number"] for call in record_interaction.call_args_list] == [1, 2]


def test_diagnosis_prompt_matches_current_schema_semantics() -> None:
    """
    2026-08-04 用于保证提示词把 arc_scores 与 style_labels 约束为当前 Schema 合同
    """
    from src.agents.diagnosis.prompts import build_diagnosis_system_prompt

    prompt = build_diagnosis_system_prompt("测试小说")

    assert "key 必须是角色规范名" in prompt
    assert "硬核/史诗/哲思" in prompt
