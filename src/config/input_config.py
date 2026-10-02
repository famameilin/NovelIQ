from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from .settings import settings


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
    max_tokens: int | None = None
    # 2026-10-02 删除 stream_enabled 字段：流式输出固定开启（src/agents/llm.py），不再随任务配置
    provider_id: str = "default"
    max_in_flight: int = 8

    def validate(self) -> None:
        if self.timeout_s is not None and self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.base_url is None:
            raise ValueError("base_url 不能为空")
        if self.model is None:
            raise ValueError("model 不能为空")


TaskType = Literal[
    "annotation",
    "diagnosis",
]


def load_task_config(
    task_type: TaskType, *, model_id: str | None = None, selection_key: str | None = None,
) -> TaskModelConfig:
    """
    根据任务类型加载模型配置
    """
    task_settings = getattr(settings.models, task_type, None)
    if task_settings is None:
        raise ValueError(f"未知的任务类型: {task_type}")

    from .model_assignment import select_annotation_model

    selected_id = model_id
    if selected_id is None:
        if task_type == "diagnosis":
            selected_id = settings.models.diagnosis_model_id
            if not selected_id:
                raise ValueError("请从模型池指定诊断模型")
        else:
            selected_id = select_annotation_model(selection_key or str(uuid4()), settings.models.model_pool)
    selected = next((entry for entry in settings.models.model_pool if entry.model_id == selected_id), None)
    if selected is None:
        raise ValueError("指定模型不在模型池中")

    thinking_enabled = getattr(task_settings, "thinking", False)

    return TaskModelConfig(
        base_url=selected.base_url,
        model=selected.model_id,
        api_key=selected.api_key,
        max_in_flight=selected.max_in_flight,
        timeout_s=task_settings.timeout_s,
        # 2026-10-02 设置迁移：采样参数跟随选中的池内模型而非任务级配置
        temperature=selected.temperature,
        top_p=selected.top_p,
        thinking_enabled=thinking_enabled,
        thinking_budget_tokens=None,
        max_tokens=selected.max_tokens,
    )
