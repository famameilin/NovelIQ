"""
标注 Agent LangGraph 定义

使用通用工具循环图：agent（带工具 LLM）→ tools → agent …
最终通过 finish 工具提交合并标注输出（阶段 1-4 合并 + 身份消歧决策）

身份消歧在循环内通过 register_identity / lookup_identity 工具完成，
不再存在独立的增量/最终消歧任务
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.config import settings

from .schema import MergedChunkAnnotation, MergedChunkAnnotationPatch


def build_annotation_graph(
    llm,
    tools: list[Any],
    *,
    response_validator: Callable[[MergedChunkAnnotation], None] | None = None,
) -> Any:
    """构建标注 agent 图"""
    from src.agents.graph import build_agent_graph

    max_attempts = max(1, settings.analysis.agents.annotation.max_iterations)
    return build_agent_graph(
        llm,
        tools,
        max_attempts=max_attempts,
        response_model=MergedChunkAnnotation,
        first_hint=(
            "请分析当前文本块并完成标注（按需查询身份记忆、权威事实、近期导航上下文与历史原文证据，"
            "首次完成时调用 finish 提交完整四阶段结果；若收到校验错误，改用 revise_finish 只提交需要修改的字段。"
        ),
        response_validator=response_validator,
        handle_tool_errors=False,
        revision_tool_name="revise_finish",
        revision_response_model=MergedChunkAnnotationPatch,
    )
