"""
章节内 subagent 会话图：程序、结构化事件提交与显式收尾状态机
"""

# 创建时间：2026-10-02　创建者：Trae
# 任务：graph.py 大文件拆分——subagent 图（_route_after_subagent_agent /
# build_subagent_graph）迁入本模块
# 说明：纯结构搬移，不改任何运行逻辑与签名；agent 节点与批执行核心分别复用
# graph._build_agent_node 与 tool_batch._build_tool_batch_node，graph.py 保留
# build_subagent_graph 的 re-export，既有导入方零改动。

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph

from .graph import AnnotationGraphState, _build_agent_node, _tool_calls
from .tool_batch import _build_tool_batch_node
from .tools import AnnotationToolLedger

if TYPE_CHECKING:
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.stream import AgentStream

    from .subagent_ir import SubagentAnnotation


def _route_after_subagent_agent(state: AnnotationGraphState) -> str:
    """2026-09-17 三代理并发用于 subagent 会话路由：错误收口、工具批次、无工具回复即产出完毕

    撞轮次上限时 halted 置位，同样按会话收束结束。
    2026-10-02 恢复：随章内三子代理路径一并加回。
    """
    if state.get("error") or state.get("halted"):
        return "end"
    if not _tool_calls(state):
        return "end"
    return "tool_batch"


def _route_after_subagent_batch(state: AnnotationGraphState) -> str:
    """当前批次无失败、显式收尾且职责缺口清零时，直接结束子代理会话"""
    finished = False
    for message in reversed(state["messages"]):
        if not isinstance(message, ToolMessage):
            break
        try:
            body = json.loads(str(message.content))
        except (TypeError, ValueError):
            return "agent"
        if not isinstance(body, dict):
            return "agent"
        if body.get("error") or body.get("failed") or body.get("accepted") is False:
            return "agent"
        if body.get("status") in {"partial", "rejected", "runtime_error", "error"}:
            return "agent"
        gap = body.get("finish")
        if message.name == "finish" and body.get("status") == "written":
            ref = body.get("ref") or {}
            gap = {
                "finished": ref.get("finished"), "missing_candidates": ref.get("unjudged_candidates"),
                "missing_metric": ref.get("missing_metric", True),
            }
        if isinstance(gap, dict):
            finished = finished or (
                gap.get("finished") is True and not gap.get("missing_candidates")
                and gap.get("missing_metric") is False
            )
    return "end" if finished else "agent"


def build_subagent_graph(
    llm: Any,
    program_tool: Any,
    finish_tool: Any,
    *,
    ledger: AnnotationToolLedger,
    subagent: SubagentAnnotation,
    max_iterations: int,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
    retries: int | None = None,
    event_submission_tool: Any | None = None,
) -> Any:
    """构建独立 work 会话，成功 finish 后直接结束

    无工具回复或轮次上限仅停止会话，Agent 必须确认成功 finish 才能交付队列保存。
    """
    bind_tools = [program_tool, *([event_submission_tool] if event_submission_tool is not None else []), finish_tool]
    program_tool_name = str(program_tool.name)
    graph = StateGraph(AnnotationGraphState)
    graph.add_node(
        "agent",
        _build_agent_node(
            llm,
            bind_tools,
            ledger=ledger,
            max_iterations=max_iterations,
            stream=stream,
            observer=observer,
            retries=retries,
        ),
    )
    execute_batch = _build_tool_batch_node(
        bind_tools,
        ledger=ledger,
        observer=observer,
        stream=stream,
        program_tool_name=program_tool_name,

    )

    async def tool_batch(state: AnnotationGraphState) -> dict[str, Any]:
        result = await execute_batch(state)
        return result

    def route_batch(state: AnnotationGraphState) -> str:
        # 新 work 的成功 finish 已关闭写面，后续同批迟到写入不撤销关闭事实
        if ledger.chapter_finished:
            return "end"
        return _route_after_subagent_batch(state)

    graph.add_node("tool_batch", tool_batch)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_subagent_agent,
        {
            "tool_batch": "tool_batch",
            "end": END,
        },
    )
    graph.add_conditional_edges("tool_batch", route_batch, {"agent": "agent", "end": END})
    return graph.compile()
