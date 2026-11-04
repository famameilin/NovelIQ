"""诊断报告写入与结束信号分离，真实回合预算及同会话补齐

诊断会话图改用
annotation/agent_graph.build_agent_loop 同一图结构，绑定面只有程序面
execute_code 与 finish；本文件断言的都仍是行为面（报告内容、同会话补齐与预算终止）。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.agents.diagnosis.program_runtime import DiagnosisProgramRuntime
from src.agents.diagnosis.session_loop import build_diagnosis_loop
from src.agents.diagnosis.tools import build_diagnosis_tools
from src.agents.messages import AssistantMessage, UserMessage
from tests.support.model_stream_adapter import StreamedFakeModelMixin
from tests.support.storage_fixtures import fixture_id, storage_for


def _analysis_payload() -> dict:
    return {
        "novel_id": fixture_id(__name__, "n1"),
        "foreshadow_expectation": 0.35,
        "arc_scores": {"顾霜": 8.0, "贺重明": 6.5},
        "genre_labels": ["玄幻"],
        "style_labels": ["爽文"],
        "topic_labels": {"0": "成长", "1": "复仇"},
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


def _report_code(payload: dict) -> str:
    return f"write_diagnosis(analysis={payload!r})"


def _analysis_code() -> str:
    return _report_code(_analysis_payload())


class Replies(StreamedFakeModelMixin):
    def __init__(self, responses):
        self.responses, self.requests = responses, []
        self.bound: list[str] = []

    def bind_tools(self, tools):
        self.bound = [tool.name for tool in tools]
        return self

    async def ainvoke(self, messages):
        self.requests.append(list(messages))
        return self.responses[len(self.requests) - 1]


def call(name, args=None, id="call"):
    return {"name": name, "args": args or {}, "id": id, "type": "tool_call"}


def build_graph(
    responses,
    *,
    maximum=5,
    observer=None,
    stream=None,
    retries=None,
    completion_check=None,
    context_window_tokens=None,
):
    """按生产会话图装配（程序面 execute_code + finish），finish 与无工具响应共用检查"""
    report = {"topic_ids": {0, 1}}
    session = MagicMock()
    tools = build_diagnosis_tools(
        storage_for(session),
        fixture_id(__name__, "run"),
        role="report",
        report_draft=report,
        agent_id=fixture_id(__name__, "diagnosis"),
        character_roster=["顾霜", "贺重明"],
    )
    model = Replies(responses)
    runtime = DiagnosisProgramRuntime(tools, observer=observer)

    def check():
        try:
            if "analysis" not in report:
                raise ValueError("缺少报告")
        except ValueError as exc:
            return [str(exc)]
        return []

    graph = build_diagnosis_loop(
        model,
        runtime,
        max_iterations=maximum,
        context_window_tokens=context_window_tokens,
        observer=observer,
        stream=stream,
        retries=retries,
        completion_check=completion_check or check,
    )
    return graph, model, report


async def run_graph(graph):
    return await graph.run(
        {
            "messages": [UserMessage(content="诊断")],
            "phase": "chapter_open",
            "iterations": 0,
            "error": None,
        },
    )


async def test_report_then_both_end_signals_produce_same_result():
    graph, model, report = build_graph(
        [
            AssistantMessage(content="", tool_calls=[call("execute_code", {"code": _analysis_code()})]),
            AssistantMessage(content="完成"),
        ]
    )
    result = await run_graph(graph)
    assert result.get("halted") is None and result["completion_ok"] is True
    assert report["analysis"]["diagnosis"] == "结构完整，节奏张弛有度"
    assert result["iterations"] == len(model.requests) == 2
    assert model.bound == ["execute_code", "finish"]


async def test_writing_finish_inside_same_program_checks_final_batch_state():
    """finish 与业务写入同程序：整批执行完再检查，最终状态决定完整性"""
    code = f"{_analysis_code()}\nwrite_diagnosis(patch={{'diagnosis': '读取夹具补充概要'}})\nfinish()"
    graph, model, report = build_graph(
        [AssistantMessage(content="", tool_calls=[call("execute_code", {"code": code})])]
    )
    result = await run_graph(graph)
    assert report["analysis"] and result["completion_ok"] is True and len(model.requests) == 1


async def test_missing_report_continues_same_history_then_saves():
    graph, model, report = build_graph(
        [
            AssistantMessage(content="完成"),
            AssistantMessage(content="", tool_calls=[call("execute_code", {"code": _analysis_code()})]),
            AssistantMessage(content="完成"),
        ]
    )
    result = await run_graph(graph)
    assert result["completion_ok"] is True and len(model.requests) == 3
    assert any("缺少报告" in str(msg.content) for msg in model.requests[1])


async def test_report_validation_rejection_preserves_last_valid_draft():
    graph, model, report = build_graph(
        [
            AssistantMessage(content="", tool_calls=[call("execute_code", {"code": _analysis_code()})]),
            AssistantMessage(
                content="",
                tool_calls=[
                    call("execute_code", {"code": "write_diagnosis(patch={'power_stance_score': 99})\nfinish()"})
                ],
            ),
        ]
    )
    result = await run_graph(graph)
    assert report["analysis"]["power_stance_score"] == 4 and result["completion_ok"] is True
    assert len(model.requests) == 2


async def test_topic_gap_is_rejected_at_write_and_repaired_by_resubmission():
    payload = {**_analysis_payload(), "topic_labels": {"0": "成长"}}
    repaired = {**_analysis_payload(), "topic_labels": {"0": "成长", "1": "复仇"}}
    graph, model, report = build_graph(
        [
            AssistantMessage(content="", tool_calls=[call("execute_code", {"code": _report_code(payload)})]),
            AssistantMessage(content="", tool_calls=[call("execute_code", {"code": _report_code(repaired)})]),
            AssistantMessage(content="完成"),
        ]
    )
    result = await run_graph(graph)
    assert len(model.requests) == 3 and result["completion_ok"] is True
    assert report["analysis"]["topic_labels"]["1"] == "复仇"


@pytest.mark.parametrize(
    "response",
    [
        AssistantMessage(content="完成"),
        AssistantMessage(content="", tool_calls=[call("execute_code", {"code": "finish()"})]),
        AssistantMessage(content="", tool_calls=[call("execute_code", {"code": _analysis_code()})]),
    ],
)
async def test_final_round_without_complete_end_is_budget_exhausted(response):
    graph, model, report = build_graph([response], maximum=1)
    result = await run_graph(graph)
    assert result.get("halted") is True and len(model.requests) == 1
