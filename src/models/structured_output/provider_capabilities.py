"""
结构化输出 provider 能力判断。

说明: 集中处理 json_schema / json_object mode 选择，业务模块不再感知 provider 差异。
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
def resolve_structured_output_task_key(client: Any, call_type: str) -> str:
    """
    解析结构化输出配置键。
    """
    task_type = getattr(client, "_task_type", None)
    if isinstance(task_type, str) and task_type in _STRUCTURED_OUTPUT_TASK_KEYS:
        return task_type
    if call_type in _ANNOTATION_PHASE_CALL_TYPES:
        return "annotation"
    if call_type in _STRUCTURED_OUTPUT_TASK_KEYS:
        return call_type
    return call_type


def _build_provider_hint(client: Any) -> str:
    """
    构建 provider 能力匹配文本。
    """
    config = getattr(client, "_config", None)
    return " ".join(
        str(value or "").lower()
        for value in (
            getattr(config, "base_url", None),
            getattr(config, "model", None),
        )
    )


def resolve_provider_override_mode(client: Any) -> StructuredOutputMode | None:
    """
    按配置解析 provider 级 mode 覆盖。
    """
    provider_hint = _build_provider_hint(client)
    provider_overrides = getattr(settings.structured_output, "provider_overrides", {})
    for marker, mode in provider_overrides.items():
        if marker and marker in provider_hint:
            if mode not in STRUCTURED_OUTPUT_MODES:
                allowed = ", ".join(sorted(STRUCTURED_OUTPUT_MODES))
                raise ValueError(f"structured_output.provider_overrides.{marker} 模式无效: {mode}，允许值: {allowed}")
            return cast(StructuredOutputMode, mode)
    return None


def provider_supports_strict_json_schema(client: Any) -> bool:
    """
    判断当前 provider 是否应走 strict json_schema。
    """
    override_mode = resolve_provider_override_mode(client)
    if override_mode == JSON_OBJECT_MODE:
        return False
    return True


def resolve_structured_output_mode(client: Any, call_type: str) -> StructuredOutputMode:
    """
    解析本次结构化调用应使用的 mode。
    """
    task_key = resolve_structured_output_task_key(client, call_type)
    configured_mode = getattr(settings.structured_output, task_key, JSON_SCHEMA_MODE)
    if configured_mode not in STRUCTURED_OUTPUT_MODES:
        allowed = ", ".join(sorted(STRUCTURED_OUTPUT_MODES))
        raise ValueError(f"structured_output.{task_key} 模式无效: {configured_mode}，允许值: {allowed}")

    mode = cast(StructuredOutputMode, configured_mode)
    override_mode = resolve_provider_override_mode(client)
    if override_mode is not None and override_mode != mode:
        logger.info(
            "structured output mode overridden by provider capability: task_key={} call_type={} mode={} override={}",
            task_key,
            call_type,
            mode,
            override_mode,
        )
        return override_mode
    if mode == JSON_SCHEMA_MODE and not provider_supports_strict_json_schema(client):
        return JSON_OBJECT_MODE
    return mode
