"""
LiteLLM 工具函数和共享逻辑

创建时间: 2026-03-16
创建者: TraeAI
任务: 重构 LiteLLM 相关代码，提取共享逻辑
说明: 集中管理模型名称处理、客户端创建等通用功能
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import TaskModelConfig


def get_model_with_provider(model: str | None, config: "TaskModelConfig") -> str | None:
    """
    获取带 provider 前缀的模型名称

    如果 model 已经包含 provider 前缀（如 openai/gpt-4），直接返回
    如果配置了 provider，添加前缀（如 provider/model-name）
    否则默认使用 openai 前缀

    Args:
        model: 原始模型名称
        config: 任务模型配置

    Returns:
        带 provider 前缀的模型名称，或原值（如果输入为 None）
    """
    if not model:
        return model

    # 如果已经包含 provider 前缀，直接返回
    if "/" in model:
        return model

    # 如果配置了 provider，添加前缀
    if config.provider:
        return f"{config.provider}/{model}"

    # 默认使用 openai 前缀
    return f"openai/{model}"
