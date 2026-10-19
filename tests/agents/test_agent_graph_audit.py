"""结束检查、工具拒绝与模型故障均保留实际回合审计"""

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.orm import sessionmaker

from src.agents.turn_observer import AgentTurnObserver, build_invocation_context
from src.audit.queries import fetch_agent_turns, fetch_run_tool_calls
from src.audit.recorder import AgentAuditRecorder
from src.storage import new_id
from tests.agents.test_diagnosis_agent import _analysis_payload, build_graph, call, run_graph
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.storage_fixtures import storage_factory, storage_for


def _new_audit_context(db_session) -> tuple[AgentAuditRecorder, AgentTurnObserver, dict, str]:
    """构造与测试库绑定的审计 recorder/observer（案例角色直接携带归属，不再登记 work）"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    recorder = AgentAuditRecorder(storage_factory(factory))
    context = build_invocation_context(
        run_id=run_id,
        task_type="diagnosis",
        agent_id=new_id(),
        attempt_number=1,
        model="test-model",
        case_anchor=None,
        role="case",
    )
    invocation_id = recorder.start_invocation(**context)
    observer = AgentTurnObserver(recorder, invocation_id=invocation_id, context=context)
    return recorder, observer, context, run_id


def _program(code: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[call("execute_code", {"code": code})])


@pytest.mark.parametrize("mode", ["success", "rejected_report", "budget", "no_tool"])
async def test_graph_audit_records_real_tools_and_closes_turns(db_session, mode):
    """绑定面只有程序面 execute_code 与 finish，拒绝与预算终止都保留逐笔工具审计"""
    recorder, observer, context, run_id = _new_audit_context(db_session)
    good = f"write_diagnosis(analysis={_analysis_payload()})\nfinish()"
    responses = [_program(good)]
    maximum = 3
    if mode == "rejected_report":
        bad = f"write_diagnosis(analysis={ {**_analysis_payload(), 'power_stance_score': 99} })"
        responses = [_program(bad), _program(good)]
    elif mode == "budget":
        responses, maximum = [_program("search_cases()")], 1
    elif mode == "no_tool":
        responses = [AIMessage(content="缺报告"), _program(good)]
    graph, model, _ = build_graph(responses, maximum=maximum, observer=observer)
    result = await run_graph(graph)
    recorder.finish_invocation(
        **context, status="error" if (result.get("error") or result.get("halted")) else "success"
    )
    db_session.rollback()
    turns = fetch_agent_turns(storage_for(db_session), run_id)
    assert len(turns) == len(model.requests)
    assert all(turn.turn_ms is not None and turn.timings.get("model") is not None for turn in turns)
    rows = fetch_run_tool_calls(storage_for(db_session), run_id)
    if mode == "budget":
        assert result.get("halted") is True
        assert [row.tool_name for row in rows] == ["search_cases", "execute_code"]
    else:
        assert result.get("completion_ok") is True
        report_rows = [row for row in rows if row.tool_name == "write_diagnosis"]
        assert [bool(row.error) for row in report_rows] == (
            [True, False] if mode == "rejected_report" else [False]
        )


async def test_provider_failure_retains_audit(db_session):
    recorder, observer, context, run_id = _new_audit_context(db_session)
    graph, model, _ = build_graph(responses=[], maximum=2, observer=observer, completion_check=lambda: [])
    model.ainvoke = AsyncMock(side_effect=RuntimeError("provider failure"))
    with pytest.raises(RuntimeError, match="provider failure"):
        await run_graph(graph)
    recorder.finish_invocation(**context, status="error", final_error="provider failure")
    db_session.rollback()
    turn = fetch_agent_turns(storage_for(db_session), run_id)[0]
    assert turn.error is not None and turn.turn_ms is not None


async def test_transport_retry_is_audited_separately_from_model_round(db_session):
    recorder, observer, context, run_id = _new_audit_context(db_session)
    graph, model, _ = build_graph(responses=[], maximum=1, observer=observer, retries=2, completion_check=lambda: [])
    model.ainvoke = AsyncMock(side_effect=[TimeoutError("provider timeout"), AIMessage(content="完成")])
    result = await run_graph(graph)
    recorder.finish_invocation(**context, status="success")
    db_session.rollback()
    turns = fetch_agent_turns(storage_for(db_session), run_id)
    assert result["iterations"] == 1
    assert [bool(turn.error) for turn in turns] == [True, False]
    assert all(turn.turn_ms is not None for turn in turns)
