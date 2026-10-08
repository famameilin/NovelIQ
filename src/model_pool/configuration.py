"""选举后解析模型请求配置；配置类型由 config 拥有"""

from __future__ import annotations

from uuid import uuid4

from src.config.input_config import TaskModelConfig, TaskType
from src.config.settings import settings


def load_task_config(
    task_type: TaskType,
    *,
    model_id: str | None = None,
    selection_key: str | None = None,
) -> TaskModelConfig:
    """
    根据任务类型加载模型配置
    """
    task_settings = getattr(settings.models, task_type, None)
    if task_settings is None:
        raise ValueError(f"未知的任务类型: {task_type}")

    from src.model_pool.selection import select_annotation_model

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
