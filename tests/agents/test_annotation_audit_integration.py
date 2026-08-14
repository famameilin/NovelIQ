"""章节标注全流程与 AgentAuditRecorder 的端到端审计集成测试"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.graph import build_annotation_graph
from src.agents.annotation.prompts import build_chunk_message
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools
from src.agents.audit.observer import AgentTurnObserver
from src.agents.audit.recorder import AgentAuditRecorder
from src.storage.models import TokenUsage
from src.storage.models.agent_audit import AgentInvocation, AgentToolCall, AgentTurn
from tests.agents.test_annotation_agent import (
    _dialogues_call,
    _empty_domain_calls,
    _entities_call,
    _events_call,
    _metrics_call,
    _observations_call,
    _QueryService,
    _SequenceLLM,
    _tool_message,
    _write_call,
)
from tests.support.chapter_annotation_helpers import create_run_with_chunks

pytestmark = pytest.mark.asyncio


def _count(db_session, model, run_id: str) -> int:
    """2026-08-10 用于按 run 统计审计行数"""
    return int(
        db_session.execute(
            select(func.count()).select_from(model).where(model.run_id == run_id)
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_protocol_error_round_closes_turn_timing(db_session) -> None:
    """2026-08-11 用于验证无工具回复的协议错误回合同样闭合 turn_ms"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["“住手”回荡"])
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    recorder = AgentAuditRecorder(factory)
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=1,
        attempt_number=1,
        model_name="test-model",
        model_provider="local",
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="annotation",
        call_type="agent",
        model_name="test-model",
        model_provider="local",
    )
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=1,
        current_chunk_id=0,
        current_chunk_text="“住手”回荡",
        allow_future_context=False,
    )
    llm = _SequenceLLM([AIMessage(content="我不调用工具")] * 3)
    graph = build_annotation_graph(
        llm,
        build_annotation_tools(_QueryService(), ledger),
        ledger=ledger,
        max_iterations=30,
        observer=observer,
    )
    result_state = await graph.ainvoke(
        {
            "messages": [
                SystemMessage(content="test"),
                HumanMessage(content="标注这段"),
            ],
            "phase": "chunk_open",
            "iterations": 0,
            "protocol_errors": 0,
            "error": None,
        }
    )
    recorder.finish_invocation(invocation_id, status="error", final_error=str(result_state["error"]))

    assert "协议错误" in (result_state.get("error") or "")
    db_session.rollback()
    turns = list(
        db_session.execute(
            select(AgentTurn).where(AgentTurn.invocation_id == invocation_id)
        ).scalars()
    )
    # 2026-08-14 P1-4：协议错误预算内重试（2 次重试 = 3 个回合），每个回合都闭合计时
    assert len(turns) == 3
    for turn in turns:
        assert turn.turn_ms is not None and turn.turn_ms >= 0


@pytest.mark.asyncio
async def test_annotation_model_exception_records_error_turn(db_session) -> None:
    """2026-08-11 用于验证标注模型调用异常时保留 error 回合并闭合计时"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["“住手”回荡"])
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    recorder = AgentAuditRecorder(factory)
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=1,
        attempt_number=1,
        model_name="test-model",
        model_provider="local",
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="annotation",
        call_type="agent",
        model_name="test-model",
        model_provider="local",
    )
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=1,
        current_chunk_id=0,
        current_chunk_text="“住手”回荡",
        allow_future_context=False,
    )
    llm = _SequenceLLM([])
    graph = build_annotation_graph(
        llm,
        build_annotation_tools(_QueryService(), ledger),
        ledger=ledger,
        max_iterations=30,
        observer=observer,
    )

    with pytest.raises(IndexError):
        await graph.ainvoke(
            {
                "messages": [
                    SystemMessage(content="test"),
                    HumanMessage(content="标注这段"),
                ],
                "phase": "chunk_open",
                "iterations": 0,
                "error": None,
            }
        )

    recorder.finish_invocation(invocation_id, status="error", final_error="IndexError")
    db_session.rollback()
    turns = list(
        db_session.execute(
            select(AgentTurn).where(AgentTurn.invocation_id == invocation_id)
        ).scalars()
    )
    assert len(turns) == 1
    assert turns[0].status == "error"
    assert turns[0].error is not None
    assert turns[0].turn_ms is not None and turns[0].turn_ms >= 0
    """2026-08-10 用于验证每个模型回合与工具调用都有独立耗时且落库"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["“住手”回荡"])
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    recorder = AgentAuditRecorder(factory)
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=1,
        attempt_number=1,
        model_name="test-model",
        model_provider="local",
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="annotation",
        call_type="agent",
        model_name="test-model",
        model_provider="local",
    )
    invalid_metrics = _write_call(
        "write_metrics",
        {
            "summary": " ",
            "emotional_valence": "neutral",
            "narrative_function": "铺垫",
        },
        call_id="call-metrics-bad",
    )
    llm = _SequenceLLM(
        [
                _tool_message(
                    [
                        _entities_call(),
                        _observations_call(),
                        _dialogues_call(),
                        _events_call(),
                        _write_call("write_relations", {"items": []}, call_id="call-relations"),
                        invalid_metrics,
                        *_empty_domain_calls()[-1:],
                    ]
                ),
            _tool_message([_metrics_call(call_id="call-metrics-fixed")]),
        ]
    )
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=1,
        current_chunk_id=0,
        current_chunk_text="“住手”回荡",
        allow_future_context=False,
    )
    tools = build_annotation_tools(_QueryService(), ledger)
    graph = build_annotation_graph(
        llm,
        tools,
        ledger=ledger,
        max_iterations=30,
        observer=observer,
    )
    result_state = await graph.ainvoke(
        {
            "messages": [
                SystemMessage(content="test"),
                HumanMessage(
                    content=build_chunk_message(
                        chunk_index=1,
                        chunk_total=1,
                        chunk_text="“住手”回荡",
                        candidates=ledger.dialogue_candidates,
                    )
                ),
            ],
            "phase": "chunk_open",
            "iterations": 0,
            "protocol_errors": 0,
            "error": None,
        }
    )
    recorder.finish_invocation(invocation_id, status="success")

    assert result_state["phase"] == "completed"
    db_session.rollback()
    assert _count(db_session, AgentInvocation, run_id) == 1
    invocation = db_session.execute(
        select(AgentInvocation).where(AgentInvocation.run_id == run_id)
    ).scalar_one()
    assert invocation.status == "success"
    assert invocation.finished_at is not None

    turn_rows = list(
        db_session.execute(
            select(AgentTurn).where(AgentTurn.invocation_id == invocation_id)
        ).scalars()
    )
    assert len(turn_rows) == 2
    assert [row.turn_index for row in turn_rows] == [1, 2]
    for turn in turn_rows:
        assert turn.model_ms is not None and turn.model_ms >= 0
        assert turn.turn_ms is not None and turn.turn_ms >= 0
        assert turn.raw_response["role"] == "ai"
        assert turn.context_summary["phase"] in {"chunk_open", "completed"}

    tool_rows = list(
        db_session.execute(
            select(AgentToolCall)
            .join(AgentTurn, AgentTurn.id == AgentToolCall.turn_id)
            .where(AgentTurn.invocation_id == invocation_id)
            .order_by(AgentToolCall.call_index, AgentToolCall.id)
        ).scalars()
    )
    assert len(tool_rows) == 8
    failed_rows = [row for row in tool_rows if row.status == "error"]
    assert len(failed_rows) == 1
    assert failed_rows[0].tool_name == "write_metrics"
    assert failed_rows[0].receipt["accepted"] is False
    assert failed_rows[0].error is not None
    for tool in tool_rows:
        assert tool.tool_duration_ms is not None and tool.tool_duration_ms >= 0
        assert tool.request_args is not None
    accepted_rows = [row for row in tool_rows if row.status == "success"]
    assert len(accepted_rows) == 7
    write_rows = [row for row in accepted_rows if row.tool_name.startswith("write_")]
    assert all(row.receipt["accepted"] is True for row in write_rows)
    assert all(row.receipt["state_digest"].startswith("sha256:") for row in write_rows)

    token_rows = list(
        db_session.execute(
            select(TokenUsage).where(TokenUsage.run_id == run_id)
        ).scalars()
    )
    assert len(token_rows) == 2
    assert all(row.agent_turn_id is not None for row in token_rows)
    assert {row.agent_turn_id for row in token_rows} == {row.id for row in turn_rows}
