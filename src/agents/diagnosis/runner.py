"""
诊断 Agent 运行入口（LangGraph 工具化自主取证）
"""

from __future__ import annotations

import json
import time
from typing import Any, cast

from loguru import logger
from sqlalchemy.orm import Session

from src.agents.usage import record_agent_token_usage
from src.models.cloud.schema import CloudAnalysis
from src.storage.repositories.diagnosis_repository import DiagnosisRepository

from .evidence import DiagnosisEvidenceLedger
from .prompts import build_diagnosis_system_prompt
from .tools import build_diagnosis_tools


class DiagnosisAgentRunError(RuntimeError):
    """诊断 agent 运行失败"""


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


def _serialize_diagnosis_messages(messages: list[Any]) -> list[dict[str, str]]:
    """
    2026-08-04 用于将诊断 Agent 消息与工具调用转为稳定审计文本
    """
    serialized: list[dict[str, str]] = []
    for message in messages:
        payload: dict[str, Any] = {"content": getattr(message, "content", "")}
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            payload["tool_calls"] = tool_calls
        tool_name = getattr(message, "name", None)
        if tool_name:
            payload["tool_name"] = tool_name
        serialized.append(
            {
                "role": str(getattr(message, "type", "unknown")),
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            }
        )
    return serialized


def _record_diagnosis_interactions(
    *,
    session: Session,
    run_id: str,
    novel_id: str,
    llm: Any,
    messages: list[Any],
    raw_output: dict[str, Any],
    evidence_ledger: DiagnosisEvidenceLedger,
    elapsed: float,
    status: str = "success",
    error_message: str | None = None,
) -> None:
    """
    2026-08-04 用于逐次记录诊断 Agent 模型响应、证据来源与 Provider Token 用量
    """
    try:
        from src.models.interactions import record_model_interaction

        serialized_messages = _serialize_diagnosis_messages(messages)
        serialized_messages.append(
            {
                "role": "evidence_audit",
                "content": json.dumps(evidence_ledger.to_dict(), ensure_ascii=False),
            }
        )
        model_responses = [message for message in messages if getattr(message, "type", None) == "ai"]
        record_count = max(1, len(model_responses))
        raw_base_url = getattr(llm, "base_url", "") or getattr(llm, "openai_api_base", "") or ""
        base_url = str(raw_base_url)
        provider = "cloud" if base_url and "localhost" not in base_url and "127.0.0.1" not in base_url else "local"
        for attempt_number in range(1, record_count + 1):
            response_text = json.dumps(raw_output, ensure_ascii=False)
            if model_responses and attempt_number < record_count:
                response_text = json.dumps(
                    _serialize_diagnosis_messages([model_responses[attempt_number - 1]]),
                    ensure_ascii=False,
                )
            record_model_interaction(
                run_id=run_id,
                chunk_id=None,
                interaction_type="diagnose",
                phase="diagnosis",
                attempt_number=attempt_number,
                messages=serialized_messages,
                response_text=response_text,
                thinking_content=None,
                duration_ms=int(elapsed * 1000),
                model_name=getattr(llm, "model_name", None),
                model_provider=provider,
                status="success" if model_responses else status,
                error_message=error_message,
                session=session,
            )
        record_agent_token_usage(
            session=session,
            run_id=run_id,
            novel_id=novel_id,
            task_type="diagnosis",
            call_type="diagnosis",
            chunk_id=None,
            llm=llm,
            messages=messages,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to record diagnosis agent interactions: {}", exc)


async def run_diagnosis_agent(
    *,
    session: Session,
    run_id: str,
    novel_id: str,
    novel_title: str | None = None,
    llm: Any | None = None,
) -> CloudAnalysis:
    """
    运行诊断 agent（工具化自主取证）

    从数据库按需查询证据（聚合指标/转折素材/人物/主题/图谱信号），
    自主决定查看哪些证据，最终输出 CloudAnalysis
    """
    from src.agents.graph import build_agent_graph
    from src.config import settings

    start_time = time.time()

    if llm is None:
        from src.agents.llm import build_chat_model

        llm = build_chat_model("diagnosis")

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
        _record_diagnosis_interactions(
            session=session,
            run_id=run_id,
            novel_id=novel_id,
            llm=llm,
            messages=initial_messages,
            raw_output={"error": str(exc)},
            evidence_ledger=evidence_ledger,
            elapsed=time.time() - start_time,
            status="error",
            error_message=str(exc),
        )
        raise DiagnosisAgentRunError(f"诊断 agent 运行失败: {exc}") from exc

    result_messages = result_state.get("messages")
    messages = result_messages if isinstance(result_messages, list) else initial_messages

    if result_state.get("error"):
        error = str(result_state["error"])
        logger.error("diagnosis agent finalize error: run_id={} error={}", run_id, error)
        _record_diagnosis_interactions(
            session=session,
            run_id=run_id,
            novel_id=novel_id,
            llm=llm,
            messages=messages,
            raw_output={"error": error},
            evidence_ledger=evidence_ledger,
            elapsed=time.time() - start_time,
            status="error",
            error_message=error,
        )
        raise DiagnosisAgentRunError(error)

    raw_output = result_state.get("output")
    if raw_output is None:
        error = "诊断 agent 未产出结果"
        _record_diagnosis_interactions(
            session=session,
            run_id=run_id,
            novel_id=novel_id,
            llm=llm,
            messages=messages,
            raw_output={"error": error},
            evidence_ledger=evidence_ledger,
            elapsed=time.time() - start_time,
            status="error",
            error_message=error,
        )
        raise DiagnosisAgentRunError(error)

    analysis = _finalize_diagnosis_result(
        CloudAnalysis.model_validate(raw_output),
        novel_id=novel_id,
        foreshadow_expectation=foreshadow_expectation,
    )
    elapsed = time.time() - start_time
    _record_diagnosis_interactions(
        session=session,
        run_id=run_id,
        novel_id=novel_id,
        llm=llm,
        messages=messages,
        raw_output=raw_output,
        evidence_ledger=evidence_ledger,
        elapsed=elapsed,
    )
    logger.info(
        "diagnosis agent complete: run_id={} genre_labels={} style_labels={} elapsed={:.2f}s",
        run_id,
        analysis.genre_labels,
        analysis.style_labels,
        elapsed,
    )
    return analysis
