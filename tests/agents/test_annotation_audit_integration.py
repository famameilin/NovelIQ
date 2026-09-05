"""章节标注全流程与 AgentAuditRecorder 的端到端审计集成测试"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.graph import build_annotation_graph
from src.agents.annotation.prompts import build_chunk_message
from src.agents.annotation.schema import ChunkParagraphInfo
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools
from src.agents.audit.observer import AgentTurnObserver
from src.agents.audit.recorder import AgentAuditRecorder
from src.agents.stream import ModelCallTiming
from src.storage.models import TokenUsage
from src.storage.models.agent_audit import AgentInvocation, AgentToolCall, AgentTurn
from tests.agents.test_annotation_agent import (
    _dialogues_call,
    _empty_domain_calls,
    _entities_call,
    _events_call,
    _metrics_call,
    _QueryService,
    _SequenceLLM,
    _tool_message,
    _write_call,
)
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def _chunk_paragraph_info(text: str) -> ChunkParagraphInfo:
    """2026-08-18 用于构造单段落 ChunkParagraphInfo（事件锚点派生所需）"""
    return ChunkParagraphInfo(
        paragraph_ids=[0],
        char_spans=[(0, len(text))],
        texts=[text],
    )


pytestmark = pytest.mark.asyncio


def _count(db_session, model, run_id: str) -> int:
    """2026-08-10 用于按 run 统计审计行数"""
    return int(db_session.execute(select(func.count()).select_from(model).where(model.run_id == run_id)).scalar_one())


@pytest.mark.asyncio
async def test_observer_records_each_physical_provider_request_separately(db_session) -> None:
    """2026-08-30 用于验证失败重试与成功请求分别保存安全参数指纹计时和 token"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜进入山门"])
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    recorder = AgentAuditRecorder(factory)
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=1,
        attempt_number=1,
        model_name="test-model",
        model_provider="cloud",
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="annotation",
        call_type="agent",
        model_name="test-model",
        model_provider="cloud",
    )
    request_messages = [SystemMessage(content="sys"), HumanMessage(content="标注")]
    base_request = {
        "request_index": 1,
        "attempt": 1,
        "transport": "stream",
        "parameters": {
            "model": "test-model",
            "base_url": "https://provider.example/v1",
            "extra_body": {"think": True},
            "timeout_s": 180,
            "tool_names": ["write_metrics"],
            "tool_contract_fingerprint": "b" * 64,
        },
        "config_fingerprint": "a" * 64,
    }
    observer.begin_provider_turn(
        context_summary={"phase": "chunk_open"},
        request_messages=request_messages,
        provider_request=base_request,
        started_ns=1,
    )
    observer.fail_provider_turn(
        error="stream interrupted",
        timing=ModelCallTiming(ttft_ms=20, model_ms=30),
        response_message=AIMessage(
            content="部分输出",
            usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        ),
    )
    observer.begin_provider_turn(
        context_summary={"phase": "chunk_open"},
        request_messages=request_messages,
        provider_request={**base_request, "attempt": 2},
        started_ns=2,
    )
    observer.complete_provider_turn(
        response_message=AIMessage(
            content="",
            tool_calls=[{"name": "write_metrics", "args": {}, "id": "call-1"}],
            additional_kwargs={"reasoning_content": "先核对原文"},
            usage_metadata={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
        ),
        timing=ModelCallTiming(ttft_ms=10, model_ms=40),
    )

    db_session.rollback()
    turns = list(
        db_session.execute(
            select(AgentTurn).where(AgentTurn.invocation_id == invocation_id).order_by(AgentTurn.turn_index)
        ).scalars()
    )
    assert [turn.status for turn in turns] == ["error", "success"]
    assert [turn.context_summary["provider_request"]["request_index"] for turn in turns] == [1, 2]
    assert turns[0].context_summary["provider_request"]["attempt"] == 1
    assert turns[1].context_summary["provider_request"]["attempt"] == 2
    assert turns[0].context_summary["provider_request"]["config_fingerprint"] == "a" * 64
    assert turns[0].context_summary["provider_request"]["parameters"]["extra_body"] == {"think": True}
    assert "api_key" not in str(turns[0].context_summary["provider_request"])
    assert turns[0].ttft_ms == 20
    assert turns[1].ttft_ms == 10
    assert turns[0].raw_response["content"] == "部分输出"
    assert turns[0].raw_response["reasoning_observed"] is False
    assert turns[1].raw_response["reasoning_observed"] is True
    token_rows = list(db_session.execute(select(TokenUsage).where(TokenUsage.run_id == run_id)).scalars())
    assert sorted(row.total_tokens for row in token_rows) == [12, 20]


@pytest.mark.asyncio
async def test_no_tool_reply_closes_turns_then_fails(db_session) -> None:
    """2026-08-30 用于验证无工具回复每次物理请求各自错误收口且不新增混合失败行"""
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
        current_chunk_text="\u201c住手\u201d回荡",
        allow_future_context=False,
        paragraph_info=_chunk_paragraph_info("\u201c住手\u201d回荡"),
    )
    llm = _SequenceLLM([AIMessage(content="我不调用工具")] * 5)
    graph = build_annotation_graph(
        llm,
        build_annotation_tools(_QueryService(), ledger),
        ledger=ledger,
        max_iterations=30,
        observer=observer,
    )
    with pytest.raises(RuntimeError, match="未正常结束"):
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
    recorder.finish_invocation(invocation_id, status="error", final_error="模型调用未正常结束")

    db_session.rollback()
    turns = list(db_session.execute(select(AgentTurn).where(AgentTurn.invocation_id == invocation_id)).scalars())
    # 调用层重试预算默认 3 次：每次物理请求各自闭合，不再额外生成混合失败行
    assert len(turns) == 3
    assert all(turn.status == "error" for turn in turns)
    assert all(turn.turn_ms is not None and turn.turn_ms >= 0 for turn in turns)


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
        current_chunk_text="\u201c住手\u201d回荡",
        allow_future_context=False,
        paragraph_info=_chunk_paragraph_info("\u201c住手\u201d回荡"),
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
    turns = list(db_session.execute(select(AgentTurn).where(AgentTurn.invocation_id == invocation_id)).scalars())
    assert len(turns) == 1
    assert turns[0].status == "error"
    assert turns[0].error is not None
    assert turns[0].turn_ms is not None and turns[0].turn_ms >= 0


@pytest.mark.asyncio
async def test_annotation_turns_and_tool_calls_are_audited(db_session) -> None:
    """2026-08-30 用于验证每个物理模型请求与工具调用都有独立耗时且落库"""
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
            _tool_message([_entities_call(), invalid_metrics]),
            _tool_message([_metrics_call(call_id="call-metrics-fixed"), _events_call()]),
            _tool_message([*_empty_domain_calls(), _dialogues_call()]),
        ]
    )
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=1,
        current_chunk_id=0,
        current_chunk_text="\u201c住手\u201d回荡",
        allow_future_context=False,
        paragraph_info=_chunk_paragraph_info("\u201c住手\u201d回荡"),
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
            "error": None,
        }
    )
    recorder.finish_invocation(invocation_id, status="success")

    assert result_state["phase"] == "completed"
    db_session.rollback()
    assert _count(db_session, AgentInvocation, run_id) == 1
    invocation = db_session.execute(select(AgentInvocation).where(AgentInvocation.run_id == run_id)).scalar_one()
    assert invocation.status == "success"
    assert invocation.finished_at is not None

    turn_rows = list(
        db_session.execute(
            select(AgentTurn)
            .where(AgentTurn.invocation_id == invocation_id)
            .order_by(AgentTurn.turn_index, AgentTurn.id)
        ).scalars()
    )
    assert len(turn_rows) == 3
    assert [row.turn_index for row in turn_rows] == [1, 2, 3]
    assert [row.context_summary["active_write_tool"] for row in turn_rows] == [
        "write_entities",
        "write_entities",
        "write_entities",
    ]
    assert [row.context_summary["active_write_tools"] for row in turn_rows] == [
        ["write_entities", "write_metrics"],
        ["write_entities", "write_metrics", "create_event", "write_relations", "write_dialogues"],
        ["write_entities", "write_metrics", "create_event", "write_relations", "write_dialogues"],
    ]
    formal_writes = {"write_entities", "write_dialogues", "create_event", "write_relations", "write_metrics"}
    for turn in turn_rows:
        assert turn.model_ms is not None and turn.model_ms >= 0
        assert turn.turn_ms is not None and turn.turn_ms >= 0
        assert turn.raw_response["role"] == "ai"
        assert turn.context_summary["phase"] in {"chunk_open", "completed"}
        assert formal_writes.intersection(turn.context_summary["allowed_tool_names"]) == set(
            turn.context_summary["active_write_tools"]
        )

    tool_rows = list(
        db_session.execute(
            select(AgentToolCall)
            .join(AgentTurn, AgentTurn.id == AgentToolCall.turn_id)
            .where(AgentTurn.invocation_id == invocation_id)
            .order_by(AgentToolCall.call_index, AgentToolCall.id)
        ).scalars()
    )
    assert len(tool_rows) == 6
    failed_rows = [row for row in tool_rows if row.status == "error"]
    assert len(failed_rows) == 1
    assert failed_rows[0].tool_name == "write_metrics"
    assert failed_rows[0].receipt["accepted"] is False
    assert failed_rows[0].error is not None
    for tool in tool_rows:
        assert tool.tool_duration_ms is not None and tool.tool_duration_ms >= 0
        assert tool.request_args is not None
    accepted_rows = [row for row in tool_rows if row.status == "success"]
    assert len(accepted_rows) == 5
    write_rows = [row for row in accepted_rows if row.tool_name.startswith("write_")]
    assert all(row.receipt["accepted"] is True for row in write_rows)

    token_rows = list(db_session.execute(select(TokenUsage).where(TokenUsage.run_id == run_id)).scalars())
    assert len(token_rows) == 3
    assert all(row.agent_turn_id is not None for row in token_rows)
    assert {row.agent_turn_id for row in token_rows} == {row.id for row in turn_rows}
