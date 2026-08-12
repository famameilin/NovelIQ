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

from src.agents.stream import AgentStream
from src.models.cloud.schema import CloudAnalysis
from src.storage.repositories.diagnosis_repository import DiagnosisRepository

from .contract import CloudAnalysisPatch
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


def _validate_topic_label_count(
    analysis: CloudAnalysis,
    *,
    expected_count: int,
) -> None:
    """
    2026-08-02 用于校验诊断主题标签数量与实际提供给 Agent 的主题数据一致
    """
    if expected_count <= 0:
        return
    actual_count = len(analysis.topic_labels)
    if actual_count != expected_count:
        raise ValueError(
            "topic_labels count must match available topic data: "
            f"expected {expected_count}, got {actual_count}"
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
    expected_topic_label_count: int,
    evidence_ledger: DiagnosisEvidenceLedger,
) -> None:
    """
    2026-08-04 用于同时校验诊断结果主题合同与工具取证来源
    """
    _validate_topic_label_count(analysis, expected_count=expected_topic_label_count)
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


async def run_diagnosis_agent(
    *,
    session: Session,
    run_id: str,
    novel_id: str,
    novel_title: str | None = None,
    llm: Any | None = None,
    stream: AgentStream | None = None,
    audit_recorder: Any | None = None,
) -> CloudAnalysis:
    """
    运行诊断 agent（工具化自主取证）

    从数据库按需查询证据（聚合指标/转折素材/人物/主题/图谱信号），
    自主决定查看哪些证据，最终输出 CloudAnalysis
    """
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.audit.recorder import AgentAuditRecorder
    from src.agents.graph import build_agent_graph
    from src.config import settings
    from src.storage.db import get_session_factory

    start_time = time.time()

    if llm is None:
        from src.agents.llm import build_chat_model

        llm = build_chat_model("diagnosis")

    if stream is not None:
        await stream.thinking("诊断 Agent 开始取证...")
    diagnosis_repo = DiagnosisRepository(session)
    topic_rows = diagnosis_repo.fetch_topic_words(
        run_id,
        top_n=10,
    )
    expected_topic_label_count = len(topic_rows)
    foreshadow_expectation = diagnosis_repo.calculate_foreshadow_expectation(run_id)

    evidence_ledger = DiagnosisEvidenceLedger()
    tools = build_diagnosis_tools(session, run_id, evidence_ledger=evidence_ledger)
    max_attempts = max(1, settings.models.diagnosis.max_iterations)
    recorder = audit_recorder or AgentAuditRecorder(get_session_factory())
    model_name = _model_name(llm)
    model_provider = _model_provider(llm)
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="diagnosis",
        chapter_id=None,
        attempt_number=1,
        model_name=model_name,
        model_provider=model_provider,
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="diagnosis",
        call_type="diagnosis",
        model_name=model_name or "unknown",
        model_provider=model_provider,
    )
    graph = build_agent_graph(
        llm,
        tools,
        max_attempts=max_attempts,
        response_model=CloudAnalysis,
        first_hint="请对当前小说完成整体诊断（按需取证，最后调用 finish 提交 CloudAnalysis）。",
        response_validator=lambda analysis: _validate_diagnosis_submission(
            analysis,
            expected_topic_label_count=expected_topic_label_count,
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

    system_prompt = build_diagnosis_system_prompt(novel_title)
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
        result_state = cast(dict[str, Any], await graph.ainvoke(initial_state))
    except Exception as exc:  # noqa: BLE001
        logger.error("diagnosis agent graph failed: run_id={} error={}", run_id, exc)
        recorder.finish_invocation(invocation_id, status="error", final_error=str(exc))
        raise DiagnosisAgentRunError(f"诊断 agent 运行失败: {exc}") from exc

    if result_state.get("error"):
        error = str(result_state["error"])
        logger.error("diagnosis agent finalize error: run_id={} error={}", run_id, error)
        recorder.finish_invocation(invocation_id, status="error", final_error=error)
        raise DiagnosisAgentRunError(error)

    raw_output = result_state.get("output")
    if raw_output is None:
        error = "诊断 agent 未产出结果"
        recorder.finish_invocation(invocation_id, status="error", final_error=error)
        raise DiagnosisAgentRunError(error)

    try:
        analysis = _finalize_diagnosis_result(
            CloudAnalysis.model_validate(raw_output),
            novel_id=novel_id,
            foreshadow_expectation=foreshadow_expectation,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("diagnosis finalize failed: run_id={} error={}", run_id, exc)
        recorder.finish_invocation(invocation_id, status="error", final_error=str(exc))
        raise DiagnosisAgentRunError(f"诊断结果终态校验失败: {exc}") from exc
    elapsed = time.time() - start_time
    recorder.finish_invocation(invocation_id, status="success")
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
