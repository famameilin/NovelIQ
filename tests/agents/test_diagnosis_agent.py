"""
诊断 Agent 单元测试

- 图循环：agent 调用 finish 提交 CloudAnalysis
- 校验失败重试
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from src.agents.diagnosis.runner import run_diagnosis_agent
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
    def __init__(self, payload: dict, *, first_bad: bool = False) -> None:
        self.payload = payload
        self.first_bad = first_bad
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.first_bad and self.calls == 1:
            bad = dict(self.payload)
            bad["power_stance_score"] = 99
            return AIMessage(
                content="",
                tool_calls=[{"name": "finish", "args": bad, "id": "c1", "type": "tool_call"}],
            )
        return AIMessage(
            content="",
            tool_calls=[{"name": "finish", "args": self.payload, "id": "c1", "type": "tool_call"}],
        )


@pytest.mark.asyncio
async def test_diagnosis_agent_produces_cloud_analysis() -> None:
    graph = build_agent_graph(
        _FinishOnlyLLM(_analysis_payload()),
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
    llm = _FinishOnlyLLM(_analysis_payload(), first_bad=True)
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
async def test_run_diagnosis_agent_requires_run_scoped_tools() -> None:
    """run_diagnosis_agent 装配诊断工具并输出 CloudAnalysis"""
    mock_session = MagicMock()
    llm = _FinishOnlyLLM(_analysis_payload())

    analysis = await run_diagnosis_agent(
        session=mock_session,
        run_id="run-1",
        novel_id="n1",
        llm=llm,
    )

    assert isinstance(analysis, CloudAnalysis)
    assert analysis.genre_labels == ["玄幻"]
