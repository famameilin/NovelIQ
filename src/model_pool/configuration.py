"""选举后解析模型请求配置；配置类型由 config 拥有"""

from __future__ import annotations

from uuid import uuid4

from src.config.input_config import TaskModelConfig, TaskType
from src.config.settings import settings
from src.model_pool.selection import select_annotation_model


def _resolve_entry(*, entry_id: str | None, model_id: str | None) -> str:
    """把条目身份或模型名解析到池内唯一条目身份；模型名重名时取池内首条"""
    pool = settings.models.model_pool
    if entry_id is not None:
        entry = next((item for item in pool if item.entry_id == entry_id), None)
    else:
        entry = next((item for item in pool if item.model_id == model_id), None)
    if entry is None:
        raise ValueError("指定模型不在模型池中")
    return entry.entry_id


def load_task_config(
    task_type: TaskType,
    *,
    entry_id: str | None = None,
    model_id: str | None = None,
    selection_key: str | None = None,
) -> TaskModelConfig:
    """按池内条目加载任务模型配置；不给条目时按权重选举"""
    task_settings = getattr(settings.models, task_type, None)
    if task_settings is None:
        raise ValueError(f"未知的任务类型: {task_type}")

    pool = settings.models.model_pool
    selected_id = entry_id
    if selected_id is None and model_id is None:
        if task_type == "diagnosis":
            model_id = settings.models.diagnosis_model_id
            if not model_id:
                raise ValueError("请从模型池指定诊断模型")
        else:
            selected_id = select_annotation_model(selection_key or str(uuid4()), pool)
            if selected_id is None:
                raise ValueError("模型池没有可用模型")
    if selected_id is None:
        selected_id = _resolve_entry(entry_id=None, model_id=model_id)
    selected = next((item for item in pool if item.entry_id == selected_id), None)
    if selected is None:
        raise ValueError("指定模型不在模型池中")

    return TaskModelConfig(
        base_url=selected.base_url,
        model=selected.model_id,
        api_key=selected.api_key,
        entry_id=selected.entry_id,
        max_in_flight=selected.max_in_flight,
        timeout_s=task_settings.timeout_s,
        # 采样参数跟随选中的池内模型，而非任务级配置
        temperature=selected.temperature,
        top_p=selected.top_p,
        reasoning_effort=task_settings.reasoning_effort,
        max_tokens=selected.max_tokens,
        context_window_tokens=selected.context_window_tokens,
    )


def model_context_window(entry_id: str) -> int | None:
    """按条目身份读取池内上下文容量；不在池内时返回 None"""
    entry = next((entry for entry in settings.models.model_pool if entry.entry_id == entry_id), None)
    return entry.context_window_tokens if entry is not None else None
