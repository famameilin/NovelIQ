"""AgentAuditRecorder 独立短事务审计测试（2026-10-16 全库 3NF：executions + 两张宽表）"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.agents.stream_audit import ModelCallTiming
from src.agents.turn_observer import AgentTurnObserver
from src.audit.documents import decode_document
from src.audit.queries import fetch_agent_turns, fetch_run_tool_calls, fetch_token_usage_stats
from src.audit.recorder import AgentAuditRecorder
from src.storage.models import AgentToolCall, Execution, ModelCall
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def _session_factory(db_session):
    """2026-08-10 用于构造与测试引擎同绑定的独立 Session 工厂"""
    return sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)


def _timings(db_session, call_id: int) -> dict[str, int]:
    """2026-10-16 用于按宽表具名计时列读回实际测得的分项计时"""
    call = db_session.get(ModelCall, call_id)
    timings: dict[str, int] = {}
    for timing_kind, column in (
        ("ttft", "ttft_ms"),
        ("first_visible", "first_visible_ms"),
        ("reasoning", "reasoning_ms"),
        ("model", "model_ms"),
        ("tool_wall", "tool_wall_ms"),
    ):
        value = getattr(call, column)
        if value is not None:
            timings[timing_kind] = int(value)
    return timings


def _turn_context(run_id: str, **overrides: Any) -> dict[str, Any]:
    """构造调用侧流动的执行上下文（与 build_invocation_context 同一组字段）

    执行身份与归属列按目标合同是全局键/受限值域，测试内按每次调用铸造唯一值，
    避免同一测试 schema 内跨用例互相命中；标注调用按章内角色（annotation 等）。
    """
    context: dict[str, Any] = {
        "run_id": run_id,
        "task_type": "annotation",
        "call_type": "agent",
        "model": "test-model",
        "execution_id": f"exec-{uuid4().hex[:12]}",
        "attempt_number": 1,
        "chapter_id": 1,
        "role": "annotation",
    }
    context.update(overrides)
    return context


def _diagnosis_turn_context(run_id: str, **overrides: Any) -> dict[str, Any]:
    """构造诊断案例角色的调用上下文（case 角色带案例锚、不带章）"""
    context = _turn_context(
        run_id,
        task_type="diagnosis",
        call_type="diagnosis",
        role="case",
        chapter_id=None,
        case_anchor=f"case-{uuid4().hex[:12]}",
    )
    context.update(overrides)
    return context


def test_recorder_utcnow_matches_timezone_free_database_contract() -> None:
    """2026-08-30 用于锁定无时区审计列统一写入 naive UTC"""
    from datetime import UTC, datetime

    recorder = AgentAuditRecorder(lambda: None)
    actual = recorder._utcnow()
    expected = datetime.now(UTC).replace(tzinfo=None)

    assert actual.tzinfo is None
    assert abs((expected - actual).total_seconds()) < 1


def test_start_turn_registers_execution_call_documents_and_notes(db_session) -> None:
    """2026-10-16 用于验证回合拆成真实执行与调用宽行落库（请求/上下文/计时备注同列）"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))

    call_id = recorder.start_turn(
        **context,
        turn_index=1,
        context_summary={"phase": "chapter_open"},
        request_messages=[],
    )

    db_session.rollback()
    execution = db_session.get(Execution, context["execution_id"])
    assert execution is not None and execution.status == "running" and execution.finished_at is None
    assert execution.attempt_number == 1
    assert (execution.run_id, execution.role, execution.chapter_id) == (run_id, "annotation", 1)
    # 新合同：真实执行直接携带归属，退场的 work 列恒为空
    assert execution.work_id is None
    call = db_session.get(ModelCall, call_id)
    assert call.model == "test-model" and call.status == "running" and call.finished_at is None
    assert call.started_at is not None
    assert call.execution_id == context["execution_id"]
    assert call.turn_index == 1
    turn = fetch_agent_turns(db_session, run_id)[0]
    assert turn.request_messages == []
    assert turn.context_summary == {"phase": "chapter_open"}
    assert turn.timing_notes == ("provider_request_started",)


def test_start_turn_without_execution_ownership_is_rejected(db_session) -> None:
    """2026-10-16 用于验证执行归属（run/角色）缺失即合同违约：不伪造归属，也不落调用宽行"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    # 只抹掉归属：执行身份仍在，但登记真实 invocation 要求 run 与角色齐备
    context["run_id"], context["role"] = None, None
    recorder = AgentAuditRecorder(_session_factory(db_session))

    with pytest.raises(RuntimeError, match="执行归属未提供"):
        recorder.start_turn(
            **context,
            turn_index=1,
            context_summary={},
            request_messages=[],
        )

    db_session.rollback()
    assert db_session.get(Execution, context["execution_id"]) is None
    assert fetch_agent_turns(db_session, run_id) == []


def test_start_turn_replay_by_message_key_returns_same_call(db_session) -> None:
    """2026-10-16 用于验证审计消息重放不重复建调用行（消息键是真实身份）"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    message_key = f"msg:{uuid4().hex}"

    first = recorder.start_turn(
        **context,
        turn_index=1,
        context_summary={},
        request_messages=[],
        message_key=message_key,
    )
    replayed = recorder.start_turn(
        **context,
        turn_index=1,
        context_summary={},
        request_messages=[],
        message_key=message_key,
    )

    db_session.rollback()
    assert replayed == first
    assert len(fetch_agent_turns(db_session, run_id)) == 1


def test_failed_attempt_without_requests_only_closes_execution(db_session) -> None:
    """2026-10-16 用于验证派发失败只写执行终态，不伪造第 0 个模型回合"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _diagnosis_turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))

    recorder.finish_invocation(**context, status="error", final_error="model dispatch failed")

    db_session.rollback()
    execution = db_session.get(Execution, context["execution_id"])
    assert execution.status == "error"
    assert execution.error == "model dispatch failed"
    assert execution.finished_at is not None
    # 案例角色按新合同带案例锚且不带章
    assert (execution.run_id, execution.role, execution.case_anchor) == (run_id, "case", context["case_anchor"])
    assert execution.chapter_id is None and execution.work_id is None
    assert fetch_agent_turns(db_session, run_id) == []


def test_successful_attempt_closes_execution_without_extra_model_call(db_session) -> None:
    """2026-10-16 用于验证成功尝试登记成功终态且不额外伪造调用行"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))

    recorder.finish_invocation(**context, status="success")

    db_session.rollback()
    execution = db_session.get(Execution, context["execution_id"])
    assert execution.status == "success" and execution.error is None
    assert execution.finished_at is not None
    assert fetch_agent_turns(db_session, run_id) == []


def test_finish_invocation_replay_is_idempotent_and_conflicting_result_is_rejected(db_session) -> None:
    """2026-10-16 用于验证执行终态重放幂等，不同结果重复收口直接报错"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    recorder.finish_invocation(**context, status="error", final_error="失败")

    recorder.finish_invocation(**context, status="error", final_error="失败")
    with pytest.raises(RuntimeError, match="已结束"):
        recorder.finish_invocation(**context, status="success")

    db_session.rollback()
    assert db_session.get(Execution, context["execution_id"]).status == "error"


def test_redispatch_attempts_finalize_under_their_own_execution_identities(db_session) -> None:
    """2026-10-17 用于验证同一案例重派各轮按自己的执行身份收口，互不阻挡

    run 52cbb1ac 实证：身份按派发对象定终身时，续跑的第一轮收口会撞上轮终态
    （不同结果重复收口）而整轮失败。执行身份按派发轮次铸造后，新一轮以自己的结果
    收口不受上轮终态影响；同一身份内不同结果重复收口仍拒。
    """
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    first_round = _diagnosis_turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    recorder.finish_invocation(**first_round, status="error", final_error="上一轮失败")

    second_round = dict(first_round, execution_id=f"exec-{uuid4().hex[:12]}", attempt_number=2)
    recorder.finish_invocation(**second_round, status="success")

    db_session.rollback()
    first_row = db_session.get(Execution, first_round["execution_id"])
    second_row = db_session.get(Execution, second_round["execution_id"])
    assert (first_row.status, first_row.error) == ("error", "上一轮失败")
    assert (second_row.status, second_row.error) == ("success", None)
    with pytest.raises(RuntimeError, match="已结束"):
        recorder.finish_invocation(**second_round, status="error", final_error="不同结果")


def test_update_turn_timings_writes_tool_wall_and_refreshes_finished_at(db_session, monkeypatch) -> None:
    """2026-08-13 P2-10 回合结束时刻随工具批处理结束更新；turn_ms 读投影为分项合计"""
    from datetime import datetime

    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    inserted_at = datetime(2026, 8, 13, 1, 0, 0)
    updated_at = datetime(2026, 8, 13, 1, 0, 2)
    times = iter([inserted_at, inserted_at, inserted_at, updated_at])
    monkeypatch.setattr(recorder, "_utcnow", lambda: next(times))

    call_id = recorder.start_turn(
        **context,
        turn_index=1,
        context_summary={},
        request_messages=[],
    )
    recorder.finish_turn(
        call_id,
        raw_response={"role": "ai", "content": "输出"},
        status="success",
        error=None,
        timing={"model_ms": 100},
        timing_notes=[],
        token_usage=None,
    )
    recorder.update_turn_timings(call_id, tool_wall_ms=250, turn_ms=1200)

    db_session.rollback()
    call = db_session.get(ModelCall, call_id)
    assert (call.finished_at - call.started_at).total_seconds() == (updated_at - inserted_at).total_seconds()
    assert call.finished_at > call.started_at
    assert _timings(db_session, call_id) == {"model": 100, "tool_wall": 250}
    turn = fetch_agent_turns(db_session, run_id)[0]
    # turn_ms 是 model_ms + tool_wall_ms 的合计投影，不再作为独立可写列保存
    assert turn.turn_ms == 350
    assert turn.tool_wall_ms == 250


def test_finish_turn_splits_usage_reported_total_and_cost(db_session) -> None:
    """2026-10-16 用于验证用量分项、供应商实报总量与费用分别落表"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    call_id = recorder.start_turn(
        **context,
        turn_index=1,
        context_summary={},
        request_messages=[],
    )

    recorder.finish_turn(
        call_id,
        raw_response={"role": "ai", "content": "输出"},
        status="success",
        error=None,
        timing={"model_ms": 100},
        timing_notes=[],
        token_usage={
            "prompt_tokens": 1200,
            "completion_tokens": 340,
            "total_tokens": 1540,
            "cache_read_tokens": 800,
            "reasoning_tokens": 200,
            "cost": 0.25,
            "accounting_source": "reported",
        },
    )

    db_session.rollback()
    usage = fetch_agent_turns(db_session, run_id)[0]
    assert usage.prompt_tokens == 1200 and usage.completion_tokens == 340
    assert usage.cache_read_tokens == 800 and usage.reasoning_tokens == 200
    assert usage.accounting_source == "reported"
    assert usage.total_tokens == 1540
    assert usage.cost == 0.25


def test_finish_turn_estimated_usage_does_not_fake_reported_total(db_session) -> None:
    """2026-10-16 用于验证本地估算只按分项投影 total_tokens，不落成供应商实报"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    call_id = recorder.start_turn(
        **context,
        turn_index=1,
        context_summary={},
        request_messages=[],
    )

    recorder.finish_turn(
        call_id,
        raw_response={"role": "ai", "content": "输出"},
        status="success",
        error=None,
        timing={"model_ms": 100},
        timing_notes=[],
        token_usage={
            "prompt_tokens": 30,
            "completion_tokens": 12,
            "total_tokens": 42,
            "accounting_source": "estimated",
        },
    )

    db_session.rollback()
    turn = fetch_agent_turns(db_session, run_id)[0]
    assert turn.accounting_source == "estimated"
    assert turn.total_tokens == 42
    # 程序估算不落成供应商实报：宽行 reported_total_tokens 保持为空
    assert db_session.get(ModelCall, call_id).reported_total_tokens is None


def test_finish_turn_writes_raw_response_and_timing_notes_in_order(db_session) -> None:
    """2026-10-16 用于验证响应文档与多条计时备注按顺序保存"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _diagnosis_turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    call_id = recorder.start_turn(
        **context,
        turn_index=1,
        context_summary={"phase": "diagnosis"},
        request_messages=[{"role": "system", "content": "sys"}, {"role": "human", "content": "问"}],
    )
    recorder.finish_turn(
        call_id,
        raw_response={"role": "ai", "content": "输出"},
        status="success",
        error=None,
        timing={"model_ms": 900, "ttft_ms": 120},
        timing_notes=["provider_non_streaming", "provider_non_streaming"],
        token_usage=None,
    )

    db_session.rollback()
    turn = fetch_agent_turns(db_session, run_id)[0]
    assert turn.request_messages == [
        {"role": "system", "content": "sys"},
        {"role": "human", "content": "问"},
    ]
    assert turn.raw_response == {"role": "ai", "content": "输出"}
    assert turn.context_summary == {"phase": "diagnosis"}
    assert turn.timing_notes == ("provider_non_streaming", "provider_non_streaming")
    assert turn.timings == {"model": 900, "ttft": 120}


def test_record_tool_call_persists_args_result_receipt_and_duration(db_session) -> None:
    """2026-10-16 用于验证工具调用按 call_id 关联调用并在宽行分开保存四类观察文档"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    call_id = recorder.start_turn(
        **context,
        turn_index=1,
        context_summary={},
        request_messages=[],
    )
    recorder.record_tool_call(
        turn_id=call_id,
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
    row = db_session.execute(select(AgentToolCall).where(AgentToolCall.call_id == call_id)).scalar_one()
    assert row.tool_name == "write_metrics"
    assert row.call_index == 0
    assert row.status == "success"
    assert row.tool_duration_ms == 42
    assert decode_document(bytes(row.executed_args_bytes)) == {"summary": "章节开端"}
    assert decode_document(bytes(row.response_observed_bytes))["accepted"] is True
    assert decode_document(bytes(row.receipt_observed_bytes))["revision"] == 1


def test_record_tool_call_persists_raw_args_as_observed_text(db_session) -> None:
    """2026-10-16 用于验证工具原始参数字符串按观察字节保真保存"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    call_id = recorder.start_turn(
        **context,
        turn_index=1,
        context_summary={},
        request_messages=[],
    )
    raw = '{"description": "神秘仪式", "keys": ["住手"]}'
    recorder.record_tool_call(
        turn_id=call_id,
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
    tool = fetch_run_tool_calls(db_session, run_id)[0]
    assert tool.raw_args == raw
    assert tool.executed_args["description"] == "神秘仪式"


def test_record_tool_call_replay_by_message_key_does_not_duplicate(db_session) -> None:
    """2026-10-16 用于验证工具审计重放按消息键幂等"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    call_id = recorder.start_turn(
        **context,
        turn_index=1,
        context_summary={},
        request_messages=[],
    )
    kwargs: dict[str, Any] = {
        "turn_id": call_id,
        "call_index": 0,
        "tool_name": "write_metrics",
        "request_args": {},
        "response": {"accepted": True},
        "receipt": {"accepted": True},
        "message_key": f"tool:{uuid4().hex}",
    }

    recorder.record_tool_call(**kwargs)
    recorder.record_tool_call(**kwargs)

    db_session.rollback()
    assert len(fetch_run_tool_calls(db_session, run_id)) == 1


def test_failed_tool_call_recorded_with_error(db_session) -> None:
    """2026-08-10 用于验证失败工具调用同样落库并保留错误与失败回执"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    call_id = recorder.start_turn(
        **context,
        turn_index=1,
        context_summary={},
        request_messages=[],
    )
    recorder.record_tool_call(
        turn_id=call_id,
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
    tool = fetch_run_tool_calls(db_session, run_id)[0]
    assert tool.status == "error"
    assert tool.error == "参数非法"
    assert tool.response_observed["accepted"] is False


def test_prior_audit_rows_survive_later_audit_failure(db_session) -> None:
    """2026-08-10 用于验证独立短事务：后续写入失败不回滚之前已提交的审计行"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    calls = {"count": 0}

    def failing_factory():
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("db unavailable")
        return _session_factory(db_session)()

    recorder = AgentAuditRecorder(failing_factory)
    call_id = recorder.start_turn(
        **context,
        turn_index=1,
        context_summary={},
        request_messages=[],
    )
    with pytest.raises(RuntimeError, match="db unavailable"):
        recorder.finish_turn(
            call_id,
            raw_response={"role": "ai", "content": "输出"},
            status="success",
            error=None,
            timing={"model_ms": 100},
            timing_notes=[],
            token_usage=None,
        )

    db_session.rollback()
    turn = fetch_agent_turns(db_session, run_id)[0]
    assert turn.call_id == call_id
    assert turn.status == "running"
    assert db_session.get(ModelCall, call_id).status == "running"


def test_observer_records_turn_and_tool_calls(db_session) -> None:
    """2026-08-10 用于验证观察器把回合与工具调用写入独立审计事务并闭合工具墙钟"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    observer = AgentTurnObserver(recorder, invocation_id=1, context=context)
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
    turn = fetch_agent_turns(db_session, run_id)[0]
    assert turn.status == "success"
    assert turn.turn_ms is not None and turn.turn_ms >= 0
    assert turn.tool_wall_ms == 5
    tool_rows = fetch_run_tool_calls(db_session, run_id)
    assert [row.tool_name for row in tool_rows] == ["write_metrics"]
    assert tool_rows[0].call_id == turn.call_id
    assert tool_rows[0].duration_ms == 5


def test_serialize_ai_message_preserves_reasoning_content() -> None:
    """2026-08-10 用于验证回合原始响应序列化保留模型思考内容"""
    from langchain_core.messages import AIMessage

    from src.agents.turn_observer import _serialize_ai_message

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

    from src.agents.turn_observer import _serialize_ai_message

    message = AIMessage(
        content="正文输出",
        response_metadata={"reasoning_content": "元数据思考"},
    )

    payload = _serialize_ai_message(message)

    assert payload["reasoning_content"] == "元数据思考"


def test_serialize_ai_message_preserves_finish_reason_from_kwargs() -> None:
    """2026-08-11 用于验证聚合器挂载的 finish_reason 随回合审计序列化保留"""
    from langchain_core.messages import AIMessage

    from src.agents.turn_observer import _serialize_ai_message

    message = AIMessage(content="", additional_kwargs={"finish_reason": "length"})

    payload = _serialize_ai_message(message)

    assert payload["finish_reason"] == "length"


def test_serialize_ai_message_reads_finish_reason_from_metadata() -> None:
    """2026-08-11 用于验证非流式响应的 finish_reason 从 response_metadata 读取"""
    from langchain_core.messages import AIMessage

    from src.agents.turn_observer import _serialize_ai_message

    message = AIMessage(content="", response_metadata={"finish_reason": "stop"})

    payload = _serialize_ai_message(message)

    assert payload["finish_reason"] == "stop"


def test_observer_persists_reasoning_content_into_raw_response_document(db_session) -> None:
    """2026-08-10 用于验证每轮模型思考内容随原始响应文档落库"""
    from langchain_core.messages import AIMessage

    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    observer = AgentTurnObserver(recorder, invocation_id=1, context=context)
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
    turn = fetch_agent_turns(db_session, run_id)[0]
    assert turn.raw_response["content"] == "正文"
    assert turn.raw_response["reasoning_content"] == "思考过程"


def test_observer_serializes_full_request_messages_into_turn(db_session) -> None:
    """2026-08-11 用于验证观察器把完整请求消息序列化并随计时备注落库"""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _diagnosis_turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    observer = AgentTurnObserver(recorder, invocation_id=1, context=context)

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
    turn = fetch_agent_turns(db_session, run_id)[0]
    assert turn.request_messages == [
        {"role": "system", "content": "sys"},
        {"role": "human", "content": "问"},
    ]
    assert turn.timing_notes == ("provider_non_streaming",)
    assert turn.raw_response["content"] == "答"


def test_serialize_request_messages_returns_empty_list_without_messages() -> None:
    """2026-08-11 用于验证无请求消息时序列化为空数组而非 NULL"""
    from src.agents.turn_observer import _serialize_request_messages

    assert _serialize_request_messages([]) == []


def test_observer_fail_provider_turn_keeps_real_request_messages(db_session) -> None:
    """2026-08-30 用于验证失败的物理请求保存真实请求消息且计时备注带失败标记"""
    from langchain_core.messages import HumanMessage, SystemMessage

    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _diagnosis_turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    observer = AgentTurnObserver(recorder, invocation_id=1, context=context)

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
    turn = fetch_agent_turns(db_session, run_id)[0]
    assert turn.status == "error"
    assert turn.error == "provider timeout"
    assert turn.turn_ms == 30
    assert turn.request_messages == [
        {"role": "system", "content": "sys"},
        {"role": "human", "content": "问"},
    ]
    assert turn.timing_notes == ("provider_request_failed",)


def test_observer_raises_when_tool_recorded_without_active_turn(db_session) -> None:
    """2026-08-10 用于验证无活动回合时工具审计直接报错（不静默忽略）"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    observer = AgentTurnObserver(recorder, invocation_id=999, context=context)
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


def test_close_orphaned_turns_interrupts_running_executions_and_calls(db_session) -> None:
    """2026-10-16 用于验证进程重启遗留的 running 执行与调用被统一收口为 interrupted"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    stale_context = _turn_context(run_id)
    finished_context = _turn_context(run_id, role="entity")
    failed_context = _turn_context(run_id, role="event", attempt_number=2)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    recorder.start_turn(**stale_context, turn_index=1, context_summary={}, request_messages=[])
    finished_id = recorder.start_turn(**finished_context, turn_index=1, context_summary={}, request_messages=[])
    recorder.finish_turn(
        finished_id,
        raw_response={},
        status="success",
        error=None,
        timing={"model_ms": 1},
        timing_notes=[],
        token_usage=None,
    )
    recorder.finish_invocation(**finished_context, status="success")
    # 没有模型请求的失败执行也要随重启收口
    recorder.finish_invocation(**failed_context, status="error")

    interrupted = AgentAuditRecorder(_session_factory(db_session)).close_orphaned_turns(run_id)

    db_session.rollback()
    # 收口 1 条 running 调用 + 1 条 running 执行
    assert interrupted == 2
    assert db_session.get(ModelCall, finished_id).status == "success"
    turns = fetch_agent_turns(db_session, run_id)
    assert {turn.status for turn in turns} == {"interrupted", "success"}
    assert [turn.error for turn in turns if turn.status == "interrupted"] == ["进程重启遗留：回合未正常收口"]
    executions = db_session.get(Execution, stale_context["execution_id"])
    assert executions.status == "interrupted" and executions.finished_at is not None
    assert db_session.get(Execution, failed_context["execution_id"]).status == "error"


def test_close_orphaned_turns_ignores_other_runs(db_session) -> None:
    """2026-10-16 用于验证收口只作用于目标 run 的执行与调用"""
    _novel_id, target_run = create_run_with_chunks(db_session, texts=["原文"])
    other_novel_id, other_run = create_run_with_chunks(db_session, texts=["原文"], title="其他运行")
    context = _turn_context(other_run)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    call_id = recorder.start_turn(**context, turn_index=1, context_summary={}, request_messages=[])

    interrupted = AgentAuditRecorder(_session_factory(db_session)).close_orphaned_turns(target_run)

    db_session.rollback()
    assert interrupted == 0
    assert db_session.get(ModelCall, call_id).status == "running"
    assert db_session.get(Execution, context["execution_id"]).status == "running"


def test_fetch_token_usage_stats_combines_agent_and_standalone_calls(db_session) -> None:
    """2026-10-16 用于验证统计从新表重组：Agent 回合 + 非 Agent 调用同一口径"""
    from src.storage.repositories import StatsRepository

    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    context = _turn_context(run_id)
    recorder = AgentAuditRecorder(_session_factory(db_session))
    call_id = recorder.start_turn(**context, turn_index=1, context_summary={}, request_messages=[])
    recorder.finish_turn(
        call_id,
        raw_response={},
        status="success",
        error=None,
        timing={"model_ms": 10},
        timing_notes=[],
        token_usage={
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 130,
            "accounting_source": "reported",
        },
    )
    StatsRepository(db_session).insert_model_turn(
        run_id=run_id,
        task_type="embedding",
        call_type="embedding",
        model="test-embedding",
        prompt_tokens=10,
        total_tokens=10,
        accounting_source="reported",
        message_key=f"{run_id}:usage:1",
    )
    db_session.commit()

    stats = fetch_token_usage_stats(db_session, run_id)

    assert stats["summary"]["call_count"] == 2
    assert stats["summary"]["total_prompt_tokens"] == 110
    assert stats["summary"]["total_completion_tokens"] == 20
    # 供应商实报总量优先：130 + 10，不按分项重算
    assert stats["summary"]["total_tokens"] == 140
    assert stats["summary"]["accounting_method"] == "reported"
    assert stats["by_task"]["annotation"]["call_count"] == 1
    assert stats["by_call_type"]["embedding.embedding"]["total_tokens"] == 10
    assert stats["by_model"]["test-model"]["total_tokens"] == 130
    assert stats["coverage_gaps"] == []
