"""
诊断 Agent 运行入口（LangGraph 工具化自主取证）

审计: 每次诊断运行开启 agent_invocations 行，模型回合与工具调用通过
AgentTurnObserver 写入独立短事务；失败路径同样保留完整审计记录。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any, cast

from loguru import logger
from sqlalchemy.orm import Session

from src.agents.diagnosis.schema import CloudAnalysis
from src.agents.stream import AgentStream
from src.storage.diagnosis_payload import CloudAnalysisPatch
from src.storage.repositories.diagnosis_repository import DiagnosisRepository

from .evidence import DiagnosisEvidenceLedger
from .prompts import build_diagnosis_system_prompt
from .tools import build_diagnosis_tools


class DiagnosisAgentRunError(RuntimeError):
    """诊断 agent 运行失败"""


def _model_provider(llm: Any) -> str:
    """2026-08-10 用于从模型地址稳定区分本地与云端审计来源"""
    raw_base_url = getattr(llm, "base_url", "") or getattr(llm, "openai_api_base", "") or ""
    base_url = str(raw_base_url)
    if base_url and "localhost" not in base_url and "127.0.0.1" not in base_url:
        return "cloud"
    return "local"


def _model_name(llm: Any) -> str | None:
    """2026-08-10 用于从模型对象稳定读取审计用模型名"""
    return str(getattr(llm, "model_name", None) or getattr(llm, "model", "") or None) or None


def _validate_topic_label_ids(
    analysis: CloudAnalysis,
    *,
    expected_ids: set[int],
) -> None:
    """核对标签键与本轮模型实际 topic_id 完全一致"""
    actual_ids = {int(topic_id) for topic_id in analysis.topic_labels}
    if actual_ids != expected_ids:
        raise ValueError(
            "topic_labels IDs must match available topic data: "
            f"expected {sorted(expected_ids)}, got {sorted(actual_ids)}"
        )


def _finalize_diagnosis_result(
    analysis: CloudAnalysis,
    *,
    novel_id: str,
    foreshadow_expectation: float | None,
) -> CloudAnalysis:
    """
    2026-08-02 用于以运行元数据和伏笔 ledger 确定性收口诊断终态
    """
    payload = analysis.model_dump()
    payload["novel_id"] = novel_id
    payload["foreshadow_expectation"] = foreshadow_expectation
    return CloudAnalysis.model_validate(payload)


def _validate_diagnosis_submission(
    analysis: CloudAnalysis,
    *,
    expected_topic_ids: set[int],
    evidence_ledger: DiagnosisEvidenceLedger,
) -> None:
    """
    2026-08-04 用于同时校验诊断结果主题合同与工具取证来源
    """
    _validate_topic_label_ids(analysis, expected_ids=expected_topic_ids)
    evidence_ledger.require_evidence()


def _context_summary(
    evidence_ledger: DiagnosisEvidenceLedger,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """2026-08-10 用于生成诊断回合的确定性上下文摘要"""
    return lambda state: {
        "phase": "diagnosis",
        "attempts": int(state.get("attempts") or 0),
        "tool_iterations": int(state.get("tool_iterations") or 0),
        "evidence": evidence_ledger.to_dict(),
    }


async def _run_diagnosis_agent(
    *,
    session: Session,
    run_id: str,
    novel_id: str,
    execution_id: str,
    novel_title: str | None = None,
    llm: Any | None = None,
    stream: AgentStream | None = None,
    audit_recorder: Any | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> CloudAnalysis:
    """
    运行诊断 agent（工具化自主取证）

    从数据库按需查询证据（聚合指标/转折素材/人物/主题/图谱信号），
    自主决定查看哪些证据，最终输出 CloudAnalysis
    """
    from src.agents.audit.observer import AgentTurnObserver, build_invocation_context
    from src.agents.graph import build_agent_graph
    from src.config import settings

    start_time = time.time()

    if llm is None:
        from src.config.input_config import load_task_config
        from src.model_pool.llm import build_chat_model

        model_config = load_task_config("diagnosis")
        llm = build_chat_model("diagnosis", config=model_config)

    if stream is not None:
        await stream.thinking("诊断 Agent 开始取证...")
    diagnosis_repo = DiagnosisRepository(session)
    topic_rows = diagnosis_repo.fetch_topic_words(run_id)
    expected_topic_ids = {int(row["topic_id"]) for row in topic_rows}
    foreshadow_expectation = diagnosis_repo.calculate_foreshadow_expectation(run_id)

    evidence_ledger = DiagnosisEvidenceLedger()
    tools = build_diagnosis_tools(session, run_id, evidence_ledger=evidence_ledger)
    max_attempts = max(1, settings.models.diagnosis.max_iterations)
    recorder: Any = audit_recorder
    model_name = _model_name(llm)
    model_provider = _model_provider(llm)
    audit_context = build_invocation_context(
        run_id=run_id,
        task_type="diagnosis",
        execution_id=execution_id,
        attempt_number=1,
        model=model_name or "unknown",
        model_provider=model_provider,
    )
    invocation_id = recorder.start_invocation(**audit_context)
    observer = AgentTurnObserver(recorder, invocation_id=invocation_id, context=audit_context)
    graph = build_agent_graph(
        llm,
        tools,
        max_attempts=max_attempts,
        response_model=CloudAnalysis,
        first_hint="请对当前小说完成整体诊断（按需取证，最后调用 finish 提交 CloudAnalysis）。",
        response_validator=lambda analysis: _validate_diagnosis_submission(
            analysis,
            expected_topic_ids=expected_topic_ids,
            evidence_ledger=evidence_ledger,
        ),
        revision_tool_name="revise_finish",
        revision_response_model=CloudAnalysisPatch,
        stream=stream,
        observer=observer,
        context_summary=_context_summary(evidence_ledger),
        model_retries=max(1, settings.models.diagnosis.total_attempts),
    )

    from langchain_core.messages import HumanMessage, SystemMessage

    system_prompt = build_diagnosis_system_prompt(
        novel_title,
        topic_label_count=len(expected_topic_ids),
    )
    initial_messages: list[Any] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"请对小说 {novel_title or novel_id} 完成整体诊断。"),
    ]
    initial_state: dict[str, Any] = {
        "messages": initial_messages,
        "attempts": 0,
        "tool_iterations": 0,
        "output": None,
        "error": None,
        "candidate": None,
    }

    try:
        # 取消要立即停：诊断取证是逐回合 LLM 调用，等整轮跑完再响应会拖住取消，
        # 故与标注 agent 同语义直接中断这次的图调用（取消由上层 handle_cancel 收口）
        from src.workflows.cancellation import run_cancellable

        result_state = cast(
            dict[str, Any], await run_cancellable(graph.ainvoke(initial_state), is_cancelled)
        )
    except BaseException as exc:
        logger.error("diagnosis agent graph failed: run_id={} error={}", run_id, exc)
        recorder.finish_invocation(**audit_context, status="error", final_error=str(exc))
        if not isinstance(exc, Exception):
            raise
        raise DiagnosisAgentRunError(f"诊断 agent 运行失败: {exc}") from exc

    if result_state.get("error"):
        error = str(result_state["error"])
        logger.error("diagnosis agent finalize error: run_id={} error={}", run_id, error)
        recorder.finish_invocation(**audit_context, status="error", final_error=error)
        raise DiagnosisAgentRunError(error)

    raw_output = result_state.get("output")
    if raw_output is None:
        error = "诊断 agent 未产出结果"
        recorder.finish_invocation(**audit_context, status="error", final_error=error)
        raise DiagnosisAgentRunError(error)

    try:
        analysis = _finalize_diagnosis_result(
            CloudAnalysis.model_validate(raw_output),
            novel_id=novel_id,
            foreshadow_expectation=foreshadow_expectation,
        )
    except Exception as exc:
        logger.error("diagnosis finalize failed: run_id={} error={}", run_id, exc)
        recorder.finish_invocation(**audit_context, status="error", final_error=str(exc))
        raise DiagnosisAgentRunError(f"诊断结果终态校验失败: {exc}") from exc
    # 诊断产物由 agent 自存（与标注 agent 同责），工作流只负责派发与收口展示
    try:
        save_diagnosis_result(session, run_id, analysis)
    except Exception as exc:
        logger.error("diagnosis save failed: run_id={} error={}", run_id, exc)
        recorder.finish_invocation(**audit_context, status="error", final_error=str(exc))
        raise DiagnosisAgentRunError(f"诊断结果落库失败: {exc}") from exc
    elapsed = time.time() - start_time
    recorder.finish_invocation(**audit_context, status="success")
    logger.info(
        "diagnosis agent complete: run_id={} genre_labels={} style_labels={} elapsed={:.2f}s",
        run_id,
        analysis.genre_labels,
        analysis.style_labels,
        elapsed,
    )
    if stream is not None:
        await stream.output("整体诊断完成，结果已通过校验")
    return analysis


def save_diagnosis_result(session: Session, run_id: str, analysis: CloudAnalysis) -> None:
    """诊断 Agent 保存实际诊断结果，并直接委托事实图维护主角属性"""
    from src.fact_graph.graph import FactGraph
    from src.storage.repositories import StatsRepository

    StatsRepository(session).insert_cloud_analysis(run_id, analysis)
    FactGraph(run_scope=run_id).save_main_characters(session, list(analysis.main_characters))
    session.commit()


async def run_diagnosis_agent(
    *,
    session: Session,
    run_id: str,
    novel_id: str,
    novel_title: str | None = None,
    llm: Any | None = None,
    stream: AgentStream | None = None,
    audit_recorder: Any | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> CloudAnalysis:
    """默认执行只发送实际展示和审计消息，审计保存有独立生命周期"""
    from uuid import uuid4

    from src.agents.audit.module import AuditMessages, AuditModule
    from src.event_bus import EventBus, Message
    from src.sse.consumer import SSEModule
    from src.storage.db import get_session_factory

    bus = EventBus()
    execution_id = uuid4().hex
    audit = AuditModule(bus, run_id, get_session_factory()) if audit_recorder is None else None
    recorder = (
        audit_recorder if audit_recorder is not None else AuditMessages(bus, run_id, "", execution_id, "diagnosis")
    )
    sse = SSEModule(bus, run_id, stream._emitter if stream is not None else None)

    async def emit(event: Any) -> None:
        await bus.request(
            Message(
                topic="sse.show",
                source="diagnosis",
                target=sse.address,
                run_id=run_id,
                invocation_id=execution_id,
                payload=event,
            )
        )

    relay = AgentStream(emit, sub_stage="diagnosis", stream_id=execution_id) if stream is not None else None
    try:
        if relay is not None:
            from src.sse.events import StreamEvent

            await emit(
                StreamEvent(action="work_reset", stage="diagnose", sub_stage="diagnosis", stream_id=execution_id)
            )
        return await _run_diagnosis_agent(
            session=session,
            run_id=run_id,
            novel_id=novel_id,
            execution_id=execution_id,
            novel_title=novel_title,
            llm=llm,
            stream=relay,
            audit_recorder=recorder,
            is_cancelled=is_cancelled,
        )
    finally:
        sse.close()
        if audit is not None:
            await audit.close()
