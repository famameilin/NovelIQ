"""
结构化输出 provider 能力判断。

创建时间: 2026-04-24
任务: structured-output-adapter-instructor-unification
说明: 集中处理 json_schema / json_object / Instructor mode 选择，业务模块不再感知 provider 差异。
"""

from __future__ import annotations

from typing import Any, cast

from loguru import logger

from src.config import settings
from src.models.structured_output.modes import (
    JSON_OBJECT_MODE,
    JSON_SCHEMA_MODE,
    STRUCTURED_OUTPUT_MODES,
    StructuredOutputMode,
)

_STRUCTURED_OUTPUT_TASK_KEYS = {
    "annotation",
    "annotation_fallback",
    "incremental_disambig",
    "mention_extraction",
    "full_disambig",
    "level3_rerank",
    "diagnosis",
}

_ANNOTATION_PHASE_CALL_TYPES = {"phase2", "phase3", "phase4"}
_JSON_OBJECT_ONLY_PROVIDER_MARKERS = ("deepseek",)


def resolve_structured_output_task_key(client: Any, call_type: str) -> str:
    """
    解析结构化输出配置键。

    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    新建原因: annotation phase 的 call_type 是 phase2/3/4，但 mode 应跟随客户端任务角色；
              这里集中做映射，避免各业务模块重复判断。
    """
    task_type = getattr(client, "_task_type", None)
    if isinstance(task_type, str) and task_type in _STRUCTURED_OUTPUT_TASK_KEYS:
        return task_type
    if call_type in _ANNOTATION_PHASE_CALL_TYPES:
        return "annotation"
    if call_type in _STRUCTURED_OUTPUT_TASK_KEYS:
        return call_type
    return call_type


def provider_supports_strict_json_schema(client: Any) -> bool:
    """
    判断当前 provider 是否应走 strict json_schema。

    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    新建原因: 将 DeepSeek 等 json_object-only provider 的兼容判断收口到适配层，
              不让 annotation / RAG / diagnosis 分别硬编码 base_url。
    """
    config = getattr(client, "_config", None)
    provider_hint = " ".join(
        str(value or "").lower()
        for value in (
            getattr(config, "base_url", None),
            getattr(config, "model", None),
        )
    )
    if any(marker in provider_hint for marker in _JSON_OBJECT_ONLY_PROVIDER_MARKERS):
        return False
    return True


def resolve_structured_output_mode(client: Any, call_type: str) -> StructuredOutputMode:
    """
    解析本次结构化调用应使用的 mode。

    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    新建原因: 按项目配置选择默认 mode，并用 provider 能力做最后兜底；
              业务层只传 call_type 和 response_model。
    """
    task_key = resolve_structured_output_task_key(client, call_type)
    configured_mode = getattr(settings.structured_output, task_key, JSON_SCHEMA_MODE)
    if configured_mode not in STRUCTURED_OUTPUT_MODES:
        allowed = ", ".join(sorted(STRUCTURED_OUTPUT_MODES))
        raise ValueError(f"structured_output.{task_key} 模式无效: {configured_mode}，允许值: {allowed}")

    mode = cast(StructuredOutputMode, configured_mode)
    if mode == JSON_SCHEMA_MODE and not provider_supports_strict_json_schema(client):
        logger.info(
            "structured output mode downgraded to json_object: task_key={} call_type={} provider_model={}",
            task_key,
            call_type,
            getattr(getattr(client, "_config", None), "model", None),
        )
        return JSON_OBJECT_MODE
    return mode
