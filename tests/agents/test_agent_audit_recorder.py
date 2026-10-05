"""AgentAuditRecorder 独立短事务审计测试"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.agents.audit.observer import AgentTurnObserver
from src.agents.audit.recorder import AgentAuditRecorder
from src.agents.stream import ModelCallTiming
from src.storage.models.agent_audit import AgentInvocation, AgentToolCall, AgentTurn
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def _session_factory(db_session):
    """2026-08-10 用于构造与测试引擎同绑定的独立 Session 工厂"""
    return sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)


def _count(db_session, model, run_id: str) -> int:
    """2026-08-10 用于按 run 统计审计行数"""
    return int(db_session.execute(select(func.count()).select_from(model).where(model.run_id == run_id)).scalar_one())


def test_recorder_utcnow_matches_timezone_free_database_contract() -> None:
    """2026-08-30 用于锁定无时区审计列统一写入 naive UTC"""
    from datetime import UTC, datetime

    recorder = AgentAuditRecorder(lambda: None)
    actual = recorder._utcnow()
    expected = datetime.now(UTC).replace(tzinfo=None)

    assert actual.tzinfo is None
    assert abs((expected - actual).total_seconds()) < 1


def test_recorder_writes_invocation_in_independent_transaction(db_session) -> None:
    """2026-08-10 用于验证 invocation 以独立短事务即时提交"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    recorder = AgentAuditRecorder(_session_factory(db_session))

    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=3,
        attempt_number=1,
        model_name="test-model",
        model_provider="local",
    )
    recorder.finish_invocation(invocation_id, status="success")

    db_session.rollback()
    row = db_session.execute(select(AgentInvocation).where(AgentInvocation.id == invocation_id)).scalar_one()
    assert row.task_type == "annotation"
    assert row.chapter_id == 3
    assert row.attempt_number == 1
    assert row.status == "success"
    assert row.final_error is None
    assert row.finished_at is not None
    assert row.started_at <= row.finished_at


def test_failed_invocation_keeps_final_error(db_session) -> None:
    """2026-08-10 用于验证失败尝试的审计记录保留最终错误"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    recorder = AgentAuditRecorder(_session_factory(db_session))

    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="diagnosis",
        chapter_id=None,
        attempt_number=1,
        model_name="test-model",
        model_provider="cloud",
    )
    recorder.finish_invocation(invocation_id, status="error", final_error="model failed")

    db_session.rollback()
    row = db_session.get(AgentInvocation, invocation_id)
    assert row.status == "error"
    assert row.final_error == "model failed"


def test_update_turn_timings_refreshes_finished_at(db_session, monkeypatch) -> None:
    """2026-08-13 P2-10 回合结束时刻随工具批处理结束更新，而非恒为插入时刻"""
    from datetime import datetime

    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    recorder = AgentAuditRecorder(_session_factory(db_session))
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=1,
        attempt_number=1,
        model_name="test-model",
        model_provider="local",
    )
    inserted_at = datetime(2026, 8, 13, 1, 0, 0)
    updated_at = datetime(2026, 8, 13, 1, 0, 2)
    times = iter([inserted_at, inserted_at, updated_at])
    monkeypatch.setattr(recorder, "_utcnow", lambda: next(times))

    turn_id = recorder.start_turn(
        invocation_id=invocation_id,
        turn_index=1,
        context_summary={},
        request_messages=[],
    )
    recorder.finish_turn(
        turn_id,
        raw_response={"role": "ai", "content": "输出"},
        status="success",
        error=None,
        timing={"model_ms": 100},
        timing_notes=[],
        token_usage=None,
        run_id=run_id,
        novel_id=novel_id,
        task_type="annotation",
        call_type="agent",
        model="test-model",
    )
    recorder.update_turn_timings(turn_id, tool_wall_ms=250, turn_ms=1200)

    db_session.rollback()
    turn = db_session.get(AgentTurn, turn_id)
    assert turn.started_at is not None
    assert turn.finished_at is not None
    assert (turn.finished_at - turn.started_at).total_seconds() == (updated_at - inserted_at).total_seconds()
    assert turn.finished_at > turn.started_at


def test_record_tool_call_persists_full_args_result_and_duration(db_session) -> None:
    """2026-08-10 用于验证工具调用行保存完整参数、结果、回执与独立耗时"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    recorder = AgentAuditRecorder(_session_factory(db_session))
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=1,
        attempt_number=1,
        model_name="test-model",
        model_provider="local",
    )
    turn_id = recorder.start_turn(
        invocation_id=invocation_id,
        turn_index=1,
        context_summary={},
        request_messages=[],
    )
    recorder.record_tool_call(
        turn_id=turn_id,
        call_index=0,
        tool_name="write_metrics",
        request_args={"summary": "章节开端"},
        response={"accepted": True, "domain": "metrics", "revision": 1},
        receipt={"accepted": True, "domain": "metrics", "revision": 1},
        status="success",
        error=None,
        tool_duration_ms=42,
    )

    db_session.rollback()
    row = db_session.execute(select(AgentToolCall).where(AgentToolCall.turn_id == turn_id)).scalar_one()
    assert row.tool_name == "write_metrics"
    assert row.call_index == 0
    assert row.request_args == {"summary": "章节开端"}
    assert row.response["accepted"] is True
    assert row.receipt == row.response
    assert row.status == "success"
    assert row.tool_duration_ms == 42


def test_record_tool_call_persists_raw_args(db_session) -> None:
    """2026-08-11 用于验证工具调用行保存原始参数片段"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    recorder = AgentAuditRecorder(_session_factory(db_session))
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=1,
        attempt_number=1,
        model_name="test-model",
        model_provider="local",
    )
    turn_id = recorder.start_turn(
        invocation_id=invocation_id,
        turn_index=1,
        context_summary={},
        request_messages=[],
    )
    raw = '{"description": "神秘仪式", "keys": ["住手"]}'
    recorder.record_tool_call(
        turn_id=turn_id,
        call_index=0,
        tool_name="push_case",
        request_args={"description": "神秘仪式", "keys": ["住手"]},
        raw_args=raw,
        response={"accepted": True},
        receipt={"accepted": True},
        status="success",
        error=None,
        tool_duration_ms=10,
    )

    db_session.rollback()
    row = db_session.execute(select(AgentToolCall).where(AgentToolCall.turn_id == turn_id)).scalar_one()
    assert row.raw_args == raw
    assert row.request_args["description"] == "神秘仪式"


def test_failed_tool_call_recorded_with_error(db_session) -> None:
    """2026-08-10 用于验证失败工具调用同样落库并保留错误与失败回执"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    recorder = AgentAuditRecorder(_session_factory(db_session))
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=1,
        attempt_number=1,
        model_name="test-model",
        model_provider="local",
    )
    turn_id = recorder.start_turn(
        invocation_id=invocation_id,
        turn_index=1,
        context_summary={},
        request_messages=[],
    )
    recorder.record_tool_call(
        turn_id=turn_id,
        call_index=0,
        tool_name="write_states",
        request_args={"items": []},
        response={"accepted": False, "error": "参数非法"},
        receipt={"accepted": False, "error": "参数非法"},
        status="error",
        error="参数非法",
        tool_duration_ms=3,
    )

    db_session.rollback()
    row = db_session.execute(select(AgentToolCall).where(AgentToolCall.turn_id == turn_id)).scalar_one()
    assert row.status == "error"
    assert row.error == "参数非法"
    assert row.response["accepted"] is False


def test_prior_audit_rows_survive_later_audit_failure(db_session) -> None:
    """2026-08-10 用于验证独立短事务：后续写入失败不回滚之前已提交的审计行"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    calls = {"count": 0}

    def failing_factory():
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("db unavailable")
        return _session_factory(db_session)()

    recorder = AgentAuditRecorder(failing_factory)
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=1,
        attempt_number=1,
        model_name="test-model",
        model_provider="local",
    )
    with pytest.raises(RuntimeError, match="db unavailable"):
        recorder.finish_invocation(invocation_id, status="success")

    db_session.rollback()
    assert _count(db_session, AgentInvocation, run_id) == 1
    row = db_session.get(AgentInvocation, invocation_id)
    assert row.status == "running"


def test_observer_records_turn_and_tool_calls(db_session) -> None:
    """2026-08-10 用于验证观察器把回合与工具调用写入独立审计事务并闭合 turn 计时"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    recorder = AgentAuditRecorder(_session_factory(db_session))
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
    from langchain_core.messages import AIMessage

    response = AIMessage(
        content="",
        tool_calls=[{"name": "write_metrics", "args": {}, "id": "c1", "type": "tool_call"}],
    )
    observer.begin_provider_turn(
        context_summary={"phase": "chapter_open"},
        request_messages=[AIMessage(content="问")],
        provider_request={"transport": "stream"},
        started_ns=0,
    )
    observer.complete_provider_turn(response_message=response, timing=ModelCallTiming(ttft_ms=10, model_ms=100))
    observer.record_tool_call(
        call_index=0,
        tool_name="write_metrics",
        request_args={},
        response={"accepted": True, "domain": "metrics", "revision": 1},
        receipt={"accepted": True, "domain": "metrics", "revision": 1},
        status="success",
        error=None,
        tool_duration_ms=5,
        started_ns=1_000_000,
    )
    observer.close_turn()

    db_session.rollback()
    turn = db_session.execute(select(AgentTurn).where(AgentTurn.invocation_id == invocation_id)).scalar_one()
    assert turn.turn_ms is not None and turn.turn_ms >= 0
    assert turn.tool_wall_ms == 5
    assert _count(db_session, AgentInvocation, run_id) == 1
    tool_rows = list(db_session.execute(select(AgentToolCall).where(AgentToolCall.turn_id == turn.id)).scalars())
    assert len(tool_rows) == 1


def test_serialize_ai_message_preserves_reasoning_content() -> None:
    """2026-08-10 用于验证回合原始响应序列化保留模型思考内容"""
    from langchain_core.messages import AIMessage

    from src.agents.audit.observer import _serialize_ai_message

    message = AIMessage(
        content="正文输出",
        additional_kwargs={"reasoning_content": "先分析后行动"},
    )

    payload = _serialize_ai_message(message)

    assert payload["content"] == "正文输出"
    assert payload["reasoning_content"] == "先分析后行动"


def test_serialize_ai_message_reads_reasoning_from_metadata() -> None:
    """2026-08-10 用于验证 Provider 把思考放在 response_metadata 时同样保留"""
    from langchain_core.messages import AIMessage

    from src.agents.audit.observer import _serialize_ai_message

    message = AIMessage(
        content="正文输出",
        response_metadata={"reasoning_content": "元数据思考"},
    )

    payload = _serialize_ai_message(message)

    assert payload["reasoning_content"] == "元数据思考"


def test_serialize_ai_message_preserves_finish_reason_from_kwargs() -> None:
    """2026-08-11 用于验证聚合器挂载的 finish_reason 随回合审计序列化保留"""
    from langchain_core.messages import AIMessage

    from src.agents.audit.observer import _serialize_ai_message

    message = AIMessage(content="", additional_kwargs={"finish_reason": "length"})

    payload = _serialize_ai_message(message)

    assert payload["finish_reason"] == "length"


def test_serialize_ai_message_reads_finish_reason_from_metadata() -> None:
    """2026-08-11 用于验证非流式响应的 finish_reason 从 response_metadata 读取"""
    from langchain_core.messages import AIMessage

    from src.agents.audit.observer import _serialize_ai_message

    message = AIMessage(content="", response_metadata={"finish_reason": "stop"})

    payload = _serialize_ai_message(message)

    assert payload["finish_reason"] == "stop"


def test_observer_persists_reasoning_content_into_turn_row(db_session) -> None:
    """2026-08-10 用于验证每轮模型思考内容随回合行落库"""
    from langchain_core.messages import AIMessage

    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    recorder = AgentAuditRecorder(_session_factory(db_session))
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
    response = AIMessage(
        content="正文",
        additional_kwargs={"reasoning_content": "思考过程"},
    )

    observer.begin_provider_turn(
        context_summary={"phase": "chapter_open"},
        request_messages=[AIMessage(content="问")],
        provider_request={"transport": "stream"},
        started_ns=0,
    )
    observer.complete_provider_turn(response_message=response, timing=ModelCallTiming(ttft_ms=5, model_ms=50))

    db_session.rollback()
    turn = db_session.execute(select(AgentTurn).where(AgentTurn.invocation_id == invocation_id)).scalar_one()
    assert turn.raw_response["content"] == "正文"
    assert turn.raw_response["reasoning_content"] == "思考过程"


def test_turn_row_persists_request_messages_and_timing_notes(db_session) -> None:
    """2026-08-30 用于验证回合行保存完整请求消息与计时口径备注"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    recorder = AgentAuditRecorder(_session_factory(db_session))
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="diagnosis",
        chapter_id=None,
        attempt_number=1,
        model_name="test-model",
        model_provider="cloud",
    )

    turn_id = recorder.start_turn(
        invocation_id=invocation_id,
        turn_index=1,
        context_summary={"phase": "diagnosis"},
        request_messages=[
            {"role": "system", "content": "sys"},
            {"role": "human", "content": "问"},
        ],
    )
    recorder.finish_turn(
        turn_id,
        raw_response={"role": "ai", "content": ""},
        status="success",
        error=None,
        timing={"model_ms": 900},
        timing_notes=["provider_non_streaming"],
        token_usage=None,
        run_id=run_id,
        novel_id=novel_id,
        task_type="diagnosis",
        call_type="diagnosis",
        model="test-model",
    )

    db_session.rollback()
    turn = db_session.get(AgentTurn, turn_id)
    assert turn.request_messages == [
        {"role": "system", "content": "sys"},
        {"role": "human", "content": "问"},
    ]
    assert turn.timing_notes == ["provider_non_streaming"]


def test_observer_serializes_full_request_messages_into_turn(db_session) -> None:
    """2026-08-11 用于验证观察器把完整请求消息序列化并随计时备注落库"""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    recorder = AgentAuditRecorder(_session_factory(db_session))
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="diagnosis",
        chapter_id=None,
        attempt_number=1,
        model_name="test-model",
        model_provider="cloud",
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="diagnosis",
        call_type="diagnosis",
        model_name="test-model",
        model_provider="cloud",
    )

    observer.begin_provider_turn(
        context_summary={"phase": "diagnosis"},
        request_messages=[SystemMessage(content="sys"), HumanMessage(content="问")],
        provider_request={"transport": "stream"},
        started_ns=0,
    )
    observer.complete_provider_turn(
        response_message=AIMessage(content="答"),
        timing=ModelCallTiming(
            model_ms=250,
            timing_notes=("provider_non_streaming",),
        ),
    )

    db_session.rollback()
    turn = db_session.execute(select(AgentTurn).where(AgentTurn.invocation_id == invocation_id)).scalar_one()
    assert turn.request_messages == [
        {"role": "system", "content": "sys"},
        {"role": "human", "content": "问"},
    ]
    assert turn.timing_notes == ["provider_non_streaming"]
    assert turn.raw_response["content"] == "答"


def test_serialize_request_messages_returns_empty_list_without_messages() -> None:
    """2026-08-11 用于验证无请求消息时序列化为空数组而非 NULL"""
    from src.agents.audit.observer import _serialize_request_messages

    assert _serialize_request_messages([]) == []


def test_observer_fail_provider_turn_keeps_real_request_messages(db_session) -> None:
    """2026-08-30 用于验证失败的物理请求保存真实请求消息且计时备注带失败标记"""
    from langchain_core.messages import HumanMessage, SystemMessage

    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    recorder = AgentAuditRecorder(_session_factory(db_session))
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="diagnosis",
        chapter_id=None,
        attempt_number=1,
        model_name="test-model",
        model_provider="cloud",
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="diagnosis",
        call_type="diagnosis",
        model_name="test-model",
        model_provider="cloud",
    )

    observer.begin_provider_turn(
        context_summary={"phase": "diagnosis"},
        request_messages=[SystemMessage(content="sys"), HumanMessage(content="问")],
        provider_request={"transport": "stream"},
        started_ns=0,
    )
    observer.fail_provider_turn(
        error="provider timeout",
        timing=ModelCallTiming(model_ms=30),
        response_message=None,
    )

    db_session.rollback()
    turn = db_session.execute(select(AgentTurn).where(AgentTurn.invocation_id == invocation_id)).scalar_one()
    assert turn.status == "error"
    assert turn.turn_ms == 30
    assert turn.request_messages == [
        {"role": "system", "content": "sys"},
        {"role": "human", "content": "问"},
    ]
    assert turn.timing_notes == ["provider_request_failed"]


def test_observer_raises_when_tool_recorded_without_active_turn(db_session) -> None:
    """2026-08-10 用于验证无活动回合时工具审计直接报错（不静默忽略）"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    recorder = AgentAuditRecorder(_session_factory(db_session))
    observer = AgentTurnObserver(
        recorder,
        invocation_id=999,
        run_id=run_id,
        novel_id=novel_id,
        task_type="annotation",
        call_type="agent",
        model_name="test-model",
        model_provider="local",
    )
    with pytest.raises(RuntimeError):
        observer.record_tool_call(
            call_index=0,
            tool_name="write_metrics",
            request_args={},
            response=None,
            receipt=None,
            status="success",
            error=None,
            tool_duration_ms=1,
            started_ns=0,
        )
