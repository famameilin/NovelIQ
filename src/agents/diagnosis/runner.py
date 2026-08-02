"""
诊断 Agent 运行入口（LangGraph 工具化自主取证）
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from src.models.cloud.schema import CloudAnalysis

from .prompts import build_diagnosis_system_prompt
from .tools import build_diagnosis_tools


class DiagnosisAgentRunError(RuntimeError):
    """诊断 agent 运行失败"""


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

    tools = build_diagnosis_tools(session, run_id)
    max_attempts = max(1, settings.analysis.agents.diagnosis.max_iterations)
    graph = build_agent_graph(
        llm,
        tools,
        max_attempts=max_attempts,
        response_model=CloudAnalysis,
        first_hint="请对当前小说完成整体诊断（按需取证，最后调用 finish 提交 CloudAnalysis）。",
    )

    from langchain_core.messages import HumanMessage, SystemMessage

    system_prompt = build_diagnosis_system_prompt(novel_title)
    initial_state = {
        "messages": [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"请对小说 {novel_title or novel_id} 完成整体诊断。"),
        ],
        "attempts": 0,
        "output": None,
        "error": None,
    }

    try:
        result_state = await graph.ainvoke(initial_state)
    except Exception as exc:  # noqa: BLE001
        logger.error("diagnosis agent graph failed: run_id={} error={}", run_id, exc)
        raise DiagnosisAgentRunError(f"诊断 agent 运行失败: {exc}") from exc

    if result_state.get("error"):
        error = str(result_state["error"])
        logger.error("diagnosis agent finalize error: run_id={} error={}", run_id, error)
        raise DiagnosisAgentRunError(error)

    raw_output = result_state.get("output")
    if raw_output is None:
        raise DiagnosisAgentRunError("诊断 agent 未产出结果")

    analysis = CloudAnalysis.model_validate(raw_output)
    elapsed = time.time() - start_time
    logger.info(
        "diagnosis agent complete: run_id={} genre_labels={} style_labels={} elapsed={:.2f}s",
        run_id,
        analysis.genre_labels,
        analysis.style_labels,
        elapsed,
    )
    return analysis
