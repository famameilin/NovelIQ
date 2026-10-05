"""
章内 subagent 会话运行器：单个 subagent 的 CodeAct 会话与缺口续跑闸门
"""

# ruff: noqa: E402 —— 文件末尾的 re-export 导入为有意的延迟导入（大文件拆分聚合面）。

# 创建时间：2026-10-02　创建者：Trae
# 任务：subagent_program.py 大文件拆分——run_subagent_agent 迁入本模块
# 说明：纯结构搬移，不改任何运行逻辑与签名；缺口计算（subagent_gap/subagent_gap_is_clean）、
# 角色文案与 _SUBAGENT_GATE_ATTEMPTS 保留在 subagent_program.py（本模块末尾反向引用，
# 双向均定义先于引用，任意导入顺序安全）；subagent_program.py 保留 re-export。

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from loguru import logger

from .errors import AnnotationInvariantError, AnnotationRetryableError
from .prompts import SUBAGENT_ROLE_SCOPES, SUBAGENT_SYSTEM_PROMPT, build_subagent_gap_message, build_subagent_message
from .subagent_ir import SubagentAnnotation
from .subagent_runtime import SubagentProgramRuntime, SubagentRunOutcome
from .tools import AnnotationToolLedger


async def run_subagent_agent(
    *,
    run_id: str,
    chapter_id: int,
    role: str,
    ledger: AnnotationToolLedger,
    tool_map: dict[str, Any],
    write_lock: asyncio.Lock,
    subagent: SubagentAnnotation,
    llm: Any,
    session_factory: Any,
    graph_state: Any | None = None,
    stream: Any | None = None,
    audit_recorder: Any | None = None,
    novel_id: str = "default",
    attempt_number: int = 1,
) -> SubagentRunOutcome:
    """用于运行一个 subagent 的 CodeAct 会话（写入直接落共享章级账本）

    subagent 绝不触碰 FactGraph 的章节生命周期（begin/reset/drain 全归派发方），
    但它的每一笔构造都经生产单条事务边界即时落库（写入生效）。
    模型可见面 = [execute_code, finish]；会话收束 = 模型不再提交程序，
    撞轮次上限按同一收束处理。
    """
    from src.agents.annotation.graph import build_subagent_graph
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.audit.recorder import AgentAuditRecorder
    from src.config import settings

    recorder = audit_recorder or AgentAuditRecorder(session_factory)
    model_name = str(getattr(llm, "model_name", None) or getattr(llm, "model", "") or None) or None
    raw_base_url = str(getattr(llm, "base_url", "") or getattr(llm, "openai_api_base", "") or "")
    is_local = not raw_base_url or "localhost" in raw_base_url or "127.0.0.1" in raw_base_url
    model_provider = "local" if is_local else "cloud"
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation_subagent",
        chapter_id=chapter_id,
        attempt_number=attempt_number,
        model_name=model_name,
        model_provider=model_provider,
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="annotation_subagent",
        call_type="agent",
        model_name=model_name or "unknown",
        model_provider=model_provider,
    )
    try:
        paragraph_info = ledger.paragraph_info
        if paragraph_info is None:
            raise AnnotationInvariantError("subagent 会话需要段落坐标映射，paragraph_info 缺失")
        runtime = SubagentProgramRuntime(
            tool_map,
            ledger,
            subagent,
            write_lock=write_lock,
            observer=observer,
            stream=stream,
        )
        program_tool = runtime.build_tool()
        from .event_submission import build_event_submission_tool

        graph = build_subagent_graph(
            llm,
            program_tool,
            runtime.finish_tool,
            ledger=ledger,
            subagent=subagent,
            max_iterations=max(1, settings.models.annotation.max_iterations),
            stream=stream,
            observer=observer,
            retries=settings.models.annotation.total_attempts,
            event_submission_tool=build_event_submission_tool(runtime),
        )
        first_messages: list[BaseMessage] = [
            SystemMessage(content=SUBAGENT_SYSTEM_PROMPT),
            HumanMessage(
                content=build_subagent_message(
                    role=role,
                    paragraph_info=paragraph_info,
                    candidates=ledger.dialogue_candidates,
                    role_scope=SUBAGENT_ROLE_SCOPES[role],
                )
            ),
        ]
        result_state = await graph.ainvoke(
            {
                "messages": first_messages,
                "phase": "chapter_open",
                "iterations": 0,
                "error": None,
            }
        )
        # 2026-09-17 缺口闸门 + subagent 级有界续跑：subagent 内的遗漏在落库相位没有模型
        # 通道可修（写入即生效，缺口就是缺口），所以这里必须判"交完了没有"。缺口清单直接作为
        # 一条用户消息交回**同一个会话**（产出记录、变量与轮次预算都还在，不是新起会话）；
        # 续跑一次仍不完整就放行，缺口在章级收尾面上可见降级。
        candidate_total = len(ledger.dialogue_candidates)
        gap = subagent_gap(subagent, candidate_total=candidate_total)
        if not subagent_gap_is_clean(gap) and attempt_number < _SUBAGENT_GATE_ATTEMPTS:
            logger.info(
                "subagent gate retry run_id={} chapter_id={} role={} missing_candidates={} missing_metric={}",
                run_id,
                chapter_id,
                role,
                len(gap["missing_candidates"]),
                gap["missing_metric"],
            )
            result_state = await graph.ainvoke(
                {
                    "messages": [*result_state["messages"], HumanMessage(content=build_subagent_gap_message(gap))],
                    "phase": "chapter_open",
                    "iterations": 0,
                    "error": None,
                }
            )
            gap = subagent_gap(subagent, candidate_total=candidate_total)
        if not subagent_gap_is_clean(gap):
            logger.warning(
                "subagent incomplete run_id={} chapter_id={} role={} gap={}",
                run_id,
                chapter_id,
                role,
                gap,
            )
    except asyncio.CancelledError:
        # 兄弟 subagent 失败会把在飞的这一条取消（BaseException，不走下面的 Exception 分支）：
        # 取消同样要收口审计行，否则 agent_invocations 留下没有终态的悬挂行
        recorder.finish_invocation(invocation_id, status="error", final_error="cancelled")
        raise
    except Exception as exc:
        recorder.finish_invocation(invocation_id, status="error", final_error=str(exc))
        if isinstance(exc, AnnotationRetryableError):
            raise
        raise AnnotationRetryableError(f"subagent 会话失败（{SUBAGENT_ROLE_LABELS.get(role, role)}）: {exc}") from exc
    error = result_state.get("error")
    if error:
        recorder.finish_invocation(invocation_id, status="error", final_error=str(error))
        raise AnnotationRetryableError(f"subagent 会话失败（{SUBAGENT_ROLE_LABELS.get(role, role)}）: {error}")
    recorder.finish_invocation(invocation_id, status="success")
    return SubagentRunOutcome(
        subagent=subagent,
        final_messages=list(result_state["messages"]),
    )


# 缺口计算与角色/闸门常量保留在 subagent_program（本模块仅在调用时读它们）：
# 置于文件末尾引用，两个方向的首次导入都安全（双方定义先于引用）。
from .subagent_program import (  # noqa: E402
    _SUBAGENT_GATE_ATTEMPTS,
    SUBAGENT_ROLE_LABELS,
    subagent_gap,
    subagent_gap_is_clean,
)
