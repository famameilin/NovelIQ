"""诊断报告写入与结束信号分离，真实回合预算及同会话补齐

2026-10-15 用户裁定「没复用agent，去改」：诊断会话图改用
annotation/agent_graph.build_agent_graph 同一图结构，绑定面只有程序面
execute_code 与 finish；本文件断言的都仍是行为面（报告内容、同会话补齐与预算终止）。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.annotation.agent_graph import build_agent_graph
from src.agents.annotation.agent_ir import AgentAnnotation
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.diagnosis.program_runtime import DiagnosisProgramRuntime, bind_finish_ledger
from src.agents.diagnosis.runner import _finalize_diagnosis_result, _validate_topic_label_ids
from src.agents.diagnosis.tools import build_diagnosis_tools
from src.diagnosis.schema import AgentAnalysis
from tests.support.model_stream_adapter import StreamedFakeModelMixin


def _analysis_payload() -> dict:
    return {
        "novel_id": "n1",
        "foreshadow_expectation": 0.35,
        "arc_scores": {"开局": 6.0, "发展": 7.5, "高潮": 8.0, "结局": 7.0, "顾霜": 8.0, "贺重明": 6.5},
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


def build_graph(responses, *, maximum=5, observer=None, stream=None, retries=None, completion_check=None):
    """按生产会话图装配（程序面 execute_code + finish），finish 与无工具响应共用检查"""
    report = {}
    session = MagicMock()
    tools = build_diagnosis_tools(session, "run", report_draft=report, execution_id="diagnosis")
    model = Replies(responses)
    ledger = AnnotationToolLedger(run_scope="run", current_chapter_id=0, current_chapter_text="",
                                  allow_future_context=False)
    runtime = DiagnosisProgramRuntime(tools, observer=observer)

    def check():
        try:
            if "analysis" not in report:
                raise ValueError("缺少报告")
            _validate_topic_label_ids(AgentAnalysis.model_validate(report["analysis"]), expected_ids={0, 1})
        except ValueError as exc:
            return [str(exc)]
        return []

    graph = build_agent_graph(
        model,
        runtime.build_tool(),
        bind_finish_ledger(runtime.tools["finish"], ledger),
        ledger=ledger,
        agent=AgentAnnotation(role="event"),
        max_iterations=maximum,
        observer=observer,
        stream=stream,
        retries=retries,
        completion_check=completion_check or check,
    )
    return graph, model, report


async def run_graph(graph):
    return await graph.ainvoke(
        {
            "messages": [HumanMessage(content="诊断")],
            "phase": "chapter_open",
            "iterations": 0,
            "error": None,
        },
        config={"recursion_limit": 40},
    )


async def test_report_then_both_end_signals_produce_same_result():
    graph, model, report = build_graph([
        AIMessage(content="", tool_calls=[call("execute_code", {"code": _analysis_code()})]),
        AIMessage(content="完成"),
    ])
    result = await run_graph(graph)
    assert result.get("halted") is None and result["completion_ok"] is True
    assert report["analysis"]["diagnosis"] == "结构完整，节奏张弛有度"
    assert result["iterations"] == len(model.requests) == 2
    assert model.bound == ["execute_code", "finish"]


async def test_writing_finish_inside_same_program_checks_final_batch_state():
    """finish 与业务写入同程序：整批执行完再检查，最终状态决定完整性"""
    code = f"{_analysis_code()}\nwrite_diagnosis(patch={{'diagnosis': '读取夹具补充概要'}})\nfinish()"
    graph, model, report = build_graph([AIMessage(content="", tool_calls=[call("execute_code", {"code": code})])])
    result = await run_graph(graph)
    assert report["analysis"] and result["completion_ok"] is True and len(model.requests) == 1


async def test_missing_report_continues_same_history_then_saves():
    graph, model, report = build_graph(
        [
            AIMessage(content="完成"),
            AIMessage(content="", tool_calls=[call("execute_code", {"code": _analysis_code()})]),
            AIMessage(content="完成"),
        ]
    )
    result = await run_graph(graph)
    assert result["completion_ok"] is True and len(model.requests) == 3
    assert any("缺少报告" in str(msg.content) for msg in model.requests[1])


async def test_report_validation_rejection_preserves_last_valid_draft():
    graph, model, report = build_graph(
        [
            AIMessage(content="", tool_calls=[call("execute_code", {"code": _analysis_code()})]),
            AIMessage(
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


async def test_topic_gap_can_be_repaired_after_no_tool_response():
    payload = {**_analysis_payload(), "topic_labels": {"0": "成长"}}
    graph, model, report = build_graph(
        [
            AIMessage(content="", tool_calls=[call("execute_code", {"code": _report_code(payload)})]),
            AIMessage(
                content="",
                tool_calls=[call("execute_code", {"code": "write_diagnosis(patch={'topic_labels': "
                                                        "{'0': '成长', '1': '复仇'}})"})],
            ),
            AIMessage(content="完成"),
        ]
    )
    result = await run_graph(graph)
    assert len(model.requests) == 3 and result["completion_ok"] is True
    assert report["analysis"]["topic_labels"]["1"] == "复仇"


@pytest.mark.parametrize(
    "response",
    [
        AIMessage(content="完成"),
        AIMessage(content="", tool_calls=[call("execute_code", {"code": "finish()"})]),
        AIMessage(content="", tool_calls=[call("execute_code", {"code": _analysis_code()})]),
    ],
)
async def test_final_round_without_complete_end_is_budget_exhausted(response):
    graph, model, report = build_graph([response], maximum=1)
    result = await run_graph(graph)
    assert result.get("halted") is True and len(model.requests) == 1


def test_validate_topic_label_ids_rejects_mismatch() -> None:
    """
    2026-08-02 用于拒绝主题标签数量与实际主题数据不一致的诊断结果
    """
    analysis = AgentAnalysis.model_validate(_analysis_payload())

    with pytest.raises(ValueError, match="IDs must match"):
        _validate_topic_label_ids(analysis, expected_ids={0, 1, 8})

    with pytest.raises(ValueError, match="valid dictionary"):
        AgentAnalysis.model_validate({"topic_labels": ["成长", "复仇"]})


def test_finalize_diagnosis_result_overrides_model_owned_runtime_fields() -> None:
    """
    2026-08-02 用于验证诊断终态由真实 novel_id 与伏笔 ledger 确定
    """
    payload = _analysis_payload()
    payload["novel_id"] = "wrong"
    payload["foreshadow_expectation"] = 0.99

    finalized = _finalize_diagnosis_result(
        AgentAnalysis.model_validate(payload),
        novel_id="novel-real",
        foreshadow_expectation=0.41,
    )

    assert finalized.novel_id == "novel-real"
    assert finalized.foreshadow_expectation == 0.41
