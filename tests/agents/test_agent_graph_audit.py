"""
通用 Agent 图审计闭合集成测试

验证 finish 提交回合闭合 turn_ms、finish 工具进入工具审计、
tool_limit 与模型异常路径同样闭合回合审计。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.agents.audit.observer import AgentTurnObserver
from src.agents.audit.recorder import AgentAuditRecorder
from src.agents.graph import build_agent_graph
from src.models.cloud.schema import CloudAnalysis
from src.storage.models.agent_audit import AgentToolCall, AgentTurn
from tests.agents.test_diagnosis_agent import _analysis_payload
from tests.support.chapter_annotation_helpers import create_run_with_chunks

pytestmark = pytest.mark.asyncio


class _SequencedLLM:
    """按顺序返回预定义 AIMessage 的测试模型（非流式降级路径）"""

    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def bind_tools(self, tools):
        del tools
        return self

    async def ainvoke(self, messages):
        del messages
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


class _FailingLLM:
    """模型调用直接抛异常的测试模型"""

    def bind_tools(self, tools):
        del tools
        return self

    async def ainvoke(self, messages):
        del messages
        raise RuntimeError("provider timeout")


def _new_audit_context(db_session) -> tuple[AgentAuditRecorder, AgentTurnObserver, int, str]:
    """构造与测试库绑定的审计 recorder/observer 并开启 invocation"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    recorder = AgentAuditRecorder(factory)
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="diagnosis",
        chapter_id=None,
        attempt_number=1,
        model_name="test-model",
        model_provider="local",
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="diagnosis",
        call_type="diagnosis",
        model_name="test-model",
        model_provider="local",
    )
    return recorder, observer, invocation_id, run_id


def _initial_state() -> dict:
    return {
        "messages": [SystemMessage(content="sys"), HumanMessage(content="诊断")],
        "attempts": 0,
        "tool_iterations": 0,
        "output": None,
        "error": None,
        "candidate": None,
    }


def _finish_call(payload: dict, call_id: str = "f1") -> dict:
    return {
        "name": "finish",
        "args": payload,
        "id": call_id,
        "type": "tool_call",
    }


async def test_graph_finish_round_closes_turn_and_audits_finish_tool(db_session) -> None:
    """2026-08-11 用于验证 finish 提交回合闭合 turn_ms 且 finish 进入工具审计"""
    recorder, observer, invocation_id, _ = _new_audit_context(db_session)
    evidence_tool = MagicMock()
    evidence_tool.name = "get_aggregate_signals"
    evidence_tool.ainvoke = AsyncMock(return_value='{"ok": true}')
    llm = _SequencedLLM(
        [
            AIMessage(
                content="取证",
                tool_calls=[
                    {
                        "name": "get_aggregate_signals",
                        "args": {},
                        "id": "e1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="提交", tool_calls=[_finish_call(_analysis_payload())]),
        ]
    )
    graph = build_agent_graph(
        llm,
        [evidence_tool],
        max_attempts=5,
        response_model=CloudAnalysis,
        first_hint="完成诊断",
        observer=observer,
    )

    result = await graph.ainvoke(_initial_state())

    recorder.finish_invocation(invocation_id, status="success")
    assert result.get("error") is None
    db_session.rollback()
    turns = list(
        db_session.execute(
            select(AgentTurn).where(AgentTurn.invocation_id == invocation_id).order_by(AgentTurn.turn_index)
        ).scalars()
    )
    assert len(turns) == 2
    assert all(turn.turn_ms is not None and turn.turn_ms >= 0 for turn in turns)
    tool_rows = list(
        db_session.execute(
            select(AgentToolCall).where(AgentToolCall.turn_id.in_([turn.id for turn in turns]))
        ).scalars()
    )
    assert {row.tool_name for row in tool_rows} == {"get_aggregate_signals", "finish"}
    finish_row = next(row for row in tool_rows if row.tool_name == "finish")
    assert finish_row.status == "success"
    assert finish_row.turn_id == turns[1].id
    assert finish_row.request_args["genre_labels"] == ["玄幻"]


async def test_graph_finish_validation_failure_records_error_tool_call(db_session) -> None:
    """2026-08-11 用于验证校验失败的 finish 调用以 error 状态进入工具审计且回合闭合"""
    recorder, observer, invocation_id, _ = _new_audit_context(db_session)
    bad_payload = dict(_analysis_payload())
    bad_payload["power_stance_score"] = 99
    llm = _SequencedLLM(
        [
            AIMessage(content="", tool_calls=[_finish_call(bad_payload, call_id="bad")]),
            AIMessage(content="", tool_calls=[_finish_call(_analysis_payload(), call_id="good")]),
        ]
    )
    graph = build_agent_graph(
        llm,
        [],
        max_attempts=5,
        response_model=CloudAnalysis,
        first_hint="完成诊断",
        observer=observer,
    )

    result = await graph.ainvoke(_initial_state())

    recorder.finish_invocation(invocation_id, status="success")
    assert result.get("error") is None
    assert llm.calls == 2
    db_session.rollback()
    turns = list(
        db_session.execute(
            select(AgentTurn).where(AgentTurn.invocation_id == invocation_id).order_by(AgentTurn.turn_index)
        ).scalars()
    )
    assert len(turns) == 2
    assert all(turn.turn_ms is not None for turn in turns)
    finish_rows = list(
        db_session.execute(
            select(AgentToolCall)
            .join(AgentTurn, AgentTurn.id == AgentToolCall.turn_id)
            .where(
                AgentTurn.invocation_id == invocation_id,
                AgentToolCall.tool_name == "finish",
            )
            .order_by(AgentToolCall.id)
        ).scalars()
    )
    assert [row.status for row in finish_rows] == ["error", "success"]
    assert finish_rows[0].error is not None
    assert "校验失败" in finish_rows[0].error


async def test_graph_mixed_finish_round_records_error_submission_audit(db_session) -> None:
    """2026-08-11 用于验证 finish 与其他工具同轮的不合规提交也进入工具审计"""
    recorder, observer, invocation_id, _ = _new_audit_context(db_session)
    evidence_tool = MagicMock()
    evidence_tool.name = "get_aggregate_signals"
    evidence_tool.ainvoke = AsyncMock(return_value='{"ok": true}')
    llm = _SequencedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    _finish_call(_analysis_payload(), call_id="f-mixed"),
                    {
                        "name": "get_aggregate_signals",
                        "args": {},
                        "id": "e1",
                        "type": "tool_call",
                    },
                ],
            ),
            AIMessage(content="", tool_calls=[_finish_call(_analysis_payload(), call_id="f-ok")]),
        ]
    )
    graph = build_agent_graph(
        llm,
        [evidence_tool],
        max_attempts=5,
        response_model=CloudAnalysis,
        first_hint="完成诊断",
        observer=observer,
    )

    result = await graph.ainvoke(_initial_state())

    recorder.finish_invocation(invocation_id, status="success")
    assert result.get("error") is None
    assert llm.calls == 2
    db_session.rollback()
    turns = list(
        db_session.execute(
            select(AgentTurn).where(AgentTurn.invocation_id == invocation_id).order_by(AgentTurn.turn_index)
        ).scalars()
    )
    assert len(turns) == 2
    assert all(turn.turn_ms is not None for turn in turns)
    evidence_tool.ainvoke.assert_not_awaited()
    finish_rows = list(
        db_session.execute(
            select(AgentToolCall)
            .join(AgentTurn, AgentTurn.id == AgentToolCall.turn_id)
            .where(
                AgentTurn.invocation_id == invocation_id,
                AgentToolCall.tool_name == "finish",
            )
            .order_by(AgentToolCall.id)
        ).scalars()
    )
    assert [row.status for row in finish_rows] == ["error", "success"]
    assert "唯一调用" in finish_rows[0].error
    assert finish_rows[0].request_args["genre_labels"] == ["玄幻"]


async def test_graph_tool_limit_round_closes_turn(db_session) -> None:
    """2026-08-11 用于验证工具迭代超限回合同样闭合 turn_ms"""
    recorder, observer, invocation_id, _ = _new_audit_context(db_session)
    evidence_tool = MagicMock()
    evidence_tool.name = "get_aggregate_signals"
    evidence_tool.ainvoke = AsyncMock(return_value='{"ok": true}')
    llm = _SequencedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_aggregate_signals",
                        "args": {},
                        "id": "e1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_aggregate_signals",
                        "args": {},
                        "id": "e2",
                        "type": "tool_call",
                    },
                    {
                        "name": "get_aggregate_signals",
                        "args": {},
                        "id": "e3",
                        "type": "tool_call",
                    },
                ],
            ),
        ]
    )
    graph = build_agent_graph(
        llm,
        [evidence_tool],
        max_attempts=5,
        response_model=CloudAnalysis,
        first_hint="完成诊断",
        max_tool_iterations=2,
        observer=observer,
    )

    result = await graph.ainvoke(_initial_state())

    recorder.finish_invocation(invocation_id, status="error", final_error=str(result.get("error")))
    assert "上限" in (result.get("error") or "")
    db_session.rollback()
    turns = list(
        db_session.execute(
            select(AgentTurn).where(AgentTurn.invocation_id == invocation_id).order_by(AgentTurn.turn_index)
        ).scalars()
    )
    assert len(turns) == 2
    assert all(turn.turn_ms is not None and turn.turn_ms >= 0 for turn in turns)


async def test_graph_model_exception_records_error_turn(db_session) -> None:
    """2026-08-11 用于验证模型调用异常时保留 error 状态回合且计时闭合"""
    recorder, observer, invocation_id, _ = _new_audit_context(db_session)
    graph = build_agent_graph(
        _FailingLLM(),
        [],
        max_attempts=5,
        response_model=CloudAnalysis,
        first_hint="完成诊断",
        observer=observer,
    )

    with pytest.raises(RuntimeError, match="provider timeout"):
        await graph.ainvoke(_initial_state())

    recorder.finish_invocation(invocation_id, status="error", final_error="provider timeout")
    db_session.rollback()
    turns = list(
        db_session.execute(
            select(AgentTurn).where(AgentTurn.invocation_id == invocation_id)
        ).scalars()
    )
    assert len(turns) == 1
    turn = turns[0]
    assert turn.status == "error"
    assert turn.error == "provider timeout"
    assert turn.turn_ms is not None and turn.turn_ms >= 0
    assert turn.model_ms is not None
    assert turn.request_messages is not None
    assert {"system", "human"} == {m["role"] for m in turn.request_messages}
    assert turn.request_messages[-1]["content"] == "诊断"
    assert turn.timing_notes == ["provider_call_failed"]


async def test_graph_finish_emits_tool_call_succeeded_event() -> None:
    """2026-08-13 P2-7 finish 走 finalize 路径时补发 tool_call succeeded 终态事件，
    前端 finish 状态不再永久停留在"进行中"""
    from src.agents.stream import AgentStream

    events: list[tuple[str, str, str]] = []

    async def emitter(event) -> None:
        events.append((event.action, event.content, event.status or ""))

    llm = _SequencedLLM(
        [AIMessage(content="提交", tool_calls=[_finish_call(_analysis_payload())])]
    )
    graph = build_agent_graph(
        llm,
        [],
        max_attempts=5,
        response_model=CloudAnalysis,
        first_hint="完成诊断",
        stream=AgentStream(emitter),
    )

    result = await graph.ainvoke(_initial_state())

    assert result.get("error") is None
    # started 由非流式降级路径补发，succeeded 由 finalize 补发（修复前缺失）
    assert ("tool_call", "finish", "started") in events
    assert ("tool_call", "finish", "success") in events
    assert ("output", "最终结果已生成并通过校验", "") in events
