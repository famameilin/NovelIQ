"""
章节内 subagent 会话图：三职责子代理各自的 execute_code + finish 状态机
"""

# 创建时间：2026-10-02　创建者：Trae
# 任务：graph.py 大文件拆分——subagent 图（_route_after_subagent_agent /
# build_subagent_graph）迁入本模块
# 说明：纯结构搬移，不改任何运行逻辑与签名；agent 节点与批执行核心分别复用
# graph._build_agent_node 与 tool_batch._build_tool_batch_node，graph.py 保留
# build_subagent_graph 的 re-export，既有导入方零改动。

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph

from .graph import AnnotationGraphState, _build_agent_node, _tool_calls
from .tool_batch import _build_tool_batch_node
from .tools import AnnotationToolLedger

if TYPE_CHECKING:
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.stream import AgentStream


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


def build_subagent_graph(
    llm: Any,
    program_tool: Any,
    finish_tool: Any,
    *,
    ledger: AnnotationToolLedger,
    max_iterations: int,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
    retries: int | None = None,
) -> Any:
    """2026-09-17 三代理并发用于构建一个 subagent 的会话状态机（可见面 = execute_code + finish）

    与读者面同构：没有写入工具、没有领域冻结、没有缺域提醒，无工具回复即"本 subagent
    产出已写完"；两处差别是撞轮次上限按会话自然收束（stop_at_iteration_limit）与
    绑定面收成 [execute_code, finish]（模型直发原生工具名一律协议错误，不落到任何写入）。
    2026-09-18 subagent 的 finish 只声明本 subagent 完毕，不是章级收尾——本图的批次传
    chapter_finish_name=None，因此同名 finish 不触发整章冻结与批次末尾结算。
    2026-10-02 恢复：随章内三子代理路径一并加回。
    """
    bind_tools = [program_tool, finish_tool]
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
            completion_hint=None,
            require_tool_call=False,
            # 2026-09-25 消融（ch20/lanes 三臂，tmp_ablation/）：lane 账本令 reasoning +36%、
            # prompt 3.5x、三 lane 全撞满回合上限，交付相当——账本只在写者面注入
            inject_progress=False,
            bind_tools=bind_tools,
            subagent_face=True,
            stop_at_iteration_limit=True,
        ),
    )
    graph.add_node(
        "tool_batch",
        _build_tool_batch_node(
            bind_tools,
            ledger=ledger,
            observer=observer,
            stream=stream,
            program_tool_name=program_tool_name,
            chapter_finish_name=None,
        ),
    )
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_subagent_agent,
        {
            "tool_batch": "tool_batch",
            "end": END,
        },
    )
    graph.add_edge("tool_batch", "agent")
    return graph.compile()
