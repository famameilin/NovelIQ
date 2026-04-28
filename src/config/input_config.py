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
    """

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_s: float | None = None
    temperature: float = 0.7
    top_p: float = 0.8
    thinking_enabled: bool = False
    thinking_budget_tokens: int | None = None
    stream_enabled: bool = False
    stream_cloud_only: bool = True

    def validate(self) -> None:
        if self.timeout_s is not None and self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.base_url is None:
            raise ValueError("base_url 不能为空")
        if self.model is None:
            raise ValueError("model 不能为空")


TaskType = Literal[
    "annotation",
    "annotation_fallback",
    "incremental_disambig",
    "mention_extraction",
    "full_disambig",
    "level3_rerank",
    "diagnosis",
]


def load_task_config(task_type: TaskType) -> TaskModelConfig:
    """
    根据任务类型加载模型配置
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
        temperature=task_settings.temperature,
        top_p=task_settings.top_p,
        thinking_enabled=thinking_enabled,
        thinking_budget_tokens=None,
        stream_enabled=stream_enabled,
        stream_cloud_only=stream_cloud_only,
    )
