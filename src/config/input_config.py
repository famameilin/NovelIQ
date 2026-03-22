from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .settings import settings


@dataclass(frozen=True)
class InputConfig:
    source_path: Path
    metadata_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.source_path.exists():
            raise FileNotFoundError(self.source_path)
        if self.metadata_path is not None and not self.metadata_path.exists():
            raise FileNotFoundError(self.metadata_path)


@dataclass(frozen=True)
class TaskModelConfig:
    """
    任务级模型配置

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 添加 provider 字段，支持明确指定 LLM provider

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 添加 stream_enabled 和 stream_cloud_only 字段支持流式响应

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: migrate-litellm-to-openai-sdk
    修改内容: 移除 backend_name 字段，迁移到 OpenAI SDK 后不再需要区分后端
    """

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_s: float | None = None
    max_retries: int = 2
    temperature: float = 0.7
    top_p: float = 0.8
    top_k: int = 20
    presence_penalty: float = 1.5
    thinking_enabled: bool = False
    thinking_budget_tokens: int | None = None
    provider: str | None = None
    stream_enabled: bool = False
    stream_cloud_only: bool = True

    def validate(self) -> None:
        if self.timeout_s is not None and self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.base_url is None:
            raise ValueError("base_url 不能为空")
        if self.model is None:
            raise ValueError("model 不能为空")


TaskType = Literal["annotation", "cloud_annotation", "incremental_disambig", "full_disambig", "diagnosis"]


def load_task_config(task_type: TaskType) -> TaskModelConfig:
    """
    根据任务类型加载模型配置

    修改时间: 2026-03-12
    修改者: TraeAI
    修改内容: thinking配置从顶层settings.thinking读取，而非各模型配置中

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 添加 provider 字段支持

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 添加 stream_enabled 支持

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: migrate-litellm-to-openai-sdk
    修改内容: 移除 backend_name 字段
    """
    task_settings = getattr(settings.models, task_type, None)
    if task_settings is None:
        raise ValueError(f"未知的任务类型: {task_type}")

    thinking_enabled = getattr(settings.thinking, task_type, False)
    stream_enabled = getattr(settings.streaming, task_type, False) if hasattr(settings, "streaming") else False

    stream_cloud_only = getattr(settings.streaming, "cloud_only", True) if hasattr(settings, "streaming") else True

    return TaskModelConfig(
        base_url=task_settings.base_url,
        model=task_settings.model,
        api_key=task_settings.api_key,
        timeout_s=task_settings.timeout_s,
        max_retries=task_settings.max_retries,
        temperature=task_settings.temperature,
        top_p=task_settings.top_p,
        top_k=task_settings.top_k,
        presence_penalty=task_settings.presence_penalty,
        thinking_enabled=thinking_enabled,
        thinking_budget_tokens=None,
        provider=getattr(task_settings, "provider", None),
        stream_enabled=stream_enabled,
        stream_cloud_only=stream_cloud_only,
    )
