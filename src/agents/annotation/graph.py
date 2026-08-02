"""
标注 Agent LangGraph 定义

使用通用工具循环图：agent（带工具 LLM）→ tools → agent …
最终通过 finish 工具提交合并标注输出（阶段 1-4 合并 + 身份消歧决策）

身份消歧在循环内通过 register_identity / lookup_identity 工具完成，
不再存在独立的增量/最终消歧任务
"""

from __future__ import annotations

from typing import Any

from src.config import settings

from .schema import MergedChunkAnnotation


def build_annotation_graph(llm, tools: list[Any]) -> Any:
    """构建标注 agent 图"""
    from src.agents.graph import build_agent_graph

    max_attempts = max(1, settings.analysis.agents.annotation.max_iterations)
    return build_agent_graph(
        llm,
        tools,
        max_attempts=max_attempts,
        response_model=MergedChunkAnnotation,
        first_hint="请分析当前文本块并完成标注（先查询身份记忆与历史证据，最后调用 finish 提交结果）。",
    )
