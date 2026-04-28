"""
本模块包含模型相关的配置数据类
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ThinkingConfig:
    """任务级思考模式配置"""

    enabled: bool = False
    budget_tokens: int | None = None


@dataclass
class TaskModelSettings:
    """
    任务模型配置（不包含thinking，thinking统一在顶层配置）
    """

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_s: float | None = None
    temperature: float = 0.7
    top_p: float = 0.8


@dataclass
class EmbeddingModelSettings:
    """嵌入模型配置"""

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_s: float | None = None
    embedding_dim: int = 1536
    batch_size: int = 8


@dataclass
class ModelsSettings:
    """
    任务级模型配置集合
    """

    annotation: TaskModelSettings = field(default_factory=TaskModelSettings)
    annotation_fallback: TaskModelSettings = field(default_factory=TaskModelSettings)
    incremental_disambig: TaskModelSettings = field(default_factory=TaskModelSettings)
    mention_extraction: TaskModelSettings = field(default_factory=TaskModelSettings)
    semantic_chunking: EmbeddingModelSettings = field(default_factory=EmbeddingModelSettings)
    full_disambig: TaskModelSettings = field(default_factory=TaskModelSettings)
    level3_rerank: TaskModelSettings = field(default_factory=TaskModelSettings)
    diagnosis: TaskModelSettings = field(default_factory=TaskModelSettings)


@dataclass
class ThinkingSettings:
    """
    各任务thinking开关配置
    """

    annotation: bool = False
    annotation_fallback: bool = True
    incremental_disambig: bool = True
    mention_extraction: bool = False
    full_disambig: bool = True
    level3_rerank: bool = False
    diagnosis: bool = True
    phase3_candidates_per_batch: int = 5
    phase3_batch_parallelism: int = 2

    def validate(self) -> None:
        """
        验证配置
        """
        if not isinstance(self.phase3_candidates_per_batch, int) or isinstance(self.phase3_candidates_per_batch, bool):
            raise ValueError("thinking.phase3_candidates_per_batch 必须是大于等于 1 的整数")
        if self.phase3_candidates_per_batch < 1:
            raise ValueError("thinking.phase3_candidates_per_batch 必须是大于等于 1 的整数")
        if not isinstance(self.phase3_batch_parallelism, int) or isinstance(self.phase3_batch_parallelism, bool):
            raise ValueError("thinking.phase3_batch_parallelism 必须是大于等于 1 的整数")
        if self.phase3_batch_parallelism < 1:
            raise ValueError("thinking.phase3_batch_parallelism 必须是大于等于 1 的整数")


@dataclass
class StreamingSettings:
    """
    各任务streaming开关配置
    """

    annotation: bool = False
    annotation_fallback: bool = True
    incremental_disambig: bool = True
    mention_extraction: bool = False
    full_disambig: bool = True
    level3_rerank: bool = False
    diagnosis: bool = True
    cloud_only: bool = True  # 是否仅在云端模型启用流式模式

    def validate(self) -> None:
        """验证配置"""
        pass


@dataclass
class StructuredOutputSettings:
    """
    结构化输出模式配置

    说明: 集中配置各任务默认使用 json_schema / json_object，
          并允许按 provider marker 覆盖，避免业务模块散落 provider 兼容判断
    """

    annotation: str = "json_schema"
    annotation_fallback: str = "json_object"
    incremental_disambig: str = "json_schema"
    mention_extraction: str = "json_object"
    full_disambig: str = "json_schema"
    level3_rerank: str = "json_schema"
    diagnosis: str = "json_schema"
    provider_overrides: dict[str, str] = field(default_factory=lambda: {"deepseek": "json_object"})


_STRUCTURED_OUTPUT_ALLOWED_MODES = {"json_schema", "json_object"}


def _parse_structured_output_mode(data: dict[str, Any], key: str, default: str) -> str:
    """
    解析单个结构化输出模式
    """
    mode = data.get(key, default)
    if mode not in _STRUCTURED_OUTPUT_ALLOWED_MODES:
        allowed = ", ".join(sorted(_STRUCTURED_OUTPUT_ALLOWED_MODES))
        raise ValueError(f"structured_output.{key} 必须是以下值之一: {allowed}")
    return mode


def _parse_structured_output_settings(data: dict[str, Any] | None) -> StructuredOutputSettings:
    """
    解析结构化输出模式配置
    """
    json_data = data or {}
    defaults = StructuredOutputSettings()
    provider_overrides = json_data.get("provider_overrides", defaults.provider_overrides)
    if not isinstance(provider_overrides, dict):
        raise ValueError("structured_output.provider_overrides 必须是对象")
    normalized_provider_overrides: dict[str, str] = {}
    for marker, mode in provider_overrides.items():
        marker_text = str(marker).strip().lower()
        if not marker_text:
            raise ValueError("structured_output.provider_overrides 不允许空 provider marker")
        if mode not in _STRUCTURED_OUTPUT_ALLOWED_MODES:
            allowed = ", ".join(sorted(_STRUCTURED_OUTPUT_ALLOWED_MODES))
            raise ValueError(f"structured_output.provider_overrides.{marker_text} 必须是以下值之一: {allowed}")
        normalized_provider_overrides[marker_text] = str(mode)
    return StructuredOutputSettings(
        annotation=_parse_structured_output_mode(json_data, "annotation", defaults.annotation),
        annotation_fallback=_parse_structured_output_mode(
            json_data,
            "annotation_fallback",
            defaults.annotation_fallback,
        ),
        incremental_disambig=_parse_structured_output_mode(
            json_data,
            "incremental_disambig",
            defaults.incremental_disambig,
        ),
        mention_extraction=_parse_structured_output_mode(
            json_data,
            "mention_extraction",
            defaults.mention_extraction,
        ),
        full_disambig=_parse_structured_output_mode(json_data, "full_disambig", defaults.full_disambig),
        level3_rerank=_parse_structured_output_mode(json_data, "level3_rerank", defaults.level3_rerank),
        diagnosis=_parse_structured_output_mode(json_data, "diagnosis", defaults.diagnosis),
        provider_overrides=normalized_provider_overrides,
    )


def _get_env_var(prefix: str, suffix: str, default: str | None = None) -> str | None:
    """获取环境变量值"""
    return os.getenv(f"{prefix}_{suffix}", default)


def _parse_task_model_settings(data: dict[str, Any] | None, env_prefix: str = "") -> TaskModelSettings:
    """
    解析任务模型配置
    """
    env_base_url = _get_env_var(env_prefix, "BASE_URL")
    env_model = _get_env_var(env_prefix, "MODEL")
    env_api_key = _get_env_var(env_prefix, "API_KEY")
    env_timeout = _get_env_var(env_prefix, "TIMEOUT_S")

    json_data = data or {}

    timeout_val = None
    if env_timeout:
        try:
            timeout_val = float(env_timeout)
        except ValueError:
            pass
    elif json_data.get("timeout_s") is not None:
        timeout_val = json_data.get("timeout_s")

    return TaskModelSettings(
        base_url=env_base_url or json_data.get("base_url"),
        model=env_model or json_data.get("model"),
        api_key=env_api_key or json_data.get("api_key"),
        timeout_s=timeout_val,
        temperature=json_data.get("temperature", 0.7),
        top_p=json_data.get("top_p", 0.8),
    )


def _parse_embedding_model_settings(data: dict[str, Any] | None, env_prefix: str = "") -> EmbeddingModelSettings:
    """
    解析嵌入模型配置
    """
    env_base_url = _get_env_var(env_prefix, "BASE_URL")
    env_model = _get_env_var(env_prefix, "MODEL")
    env_api_key = _get_env_var(env_prefix, "API_KEY")
    env_timeout = _get_env_var(env_prefix, "TIMEOUT_S")
    env_embedding_dim = _get_env_var(env_prefix, "EMBEDDING_DIM")
    env_batch_size = _get_env_var(env_prefix, "BATCH_SIZE")

    json_data = data or {}

    timeout_val = None
    if env_timeout:
        try:
            timeout_val = float(env_timeout)
        except ValueError:
            pass
    elif json_data.get("timeout_s") is not None:
        timeout_val = json_data.get("timeout_s")

    embedding_dim_val = 1536
    if env_embedding_dim:
        try:
            embedding_dim_val = int(env_embedding_dim)
        except ValueError:
            embedding_dim_val = json_data.get("embedding_dim", 1536)
    else:
        embedding_dim_val = json_data.get("embedding_dim", 1536)

    batch_size_val = 8
    if env_batch_size:
        try:
            batch_size_val = int(env_batch_size)
        except ValueError:
            batch_size_val = json_data.get("batch_size", 8)
    else:
        batch_size_val = json_data.get("batch_size", 8)

    return EmbeddingModelSettings(
        base_url=env_base_url or json_data.get("base_url"),
        model=env_model or json_data.get("model"),
        api_key=env_api_key or json_data.get("api_key"),
        timeout_s=timeout_val,
        embedding_dim=embedding_dim_val,
        batch_size=batch_size_val,
    )


def _parse_models_settings(data: dict[str, Any] | None) -> ModelsSettings:
    """
    解析任务级模型配置集合
    """
    if not data:
        data = {}
    return ModelsSettings(
        annotation=_parse_task_model_settings(data.get("annotation"), "ANNOTATION"),
        annotation_fallback=_parse_task_model_settings(
            data.get("annotation_fallback"),
            "ANNOTATION_FALLBACK",
        ),
        incremental_disambig=_parse_task_model_settings(data.get("incremental_disambig"), "INCREMENTAL_DISAMBIG"),
        mention_extraction=_parse_task_model_settings(data.get("mention_extraction"), "MENTION_EXTRACTION"),
        semantic_chunking=_parse_embedding_model_settings(data.get("semantic_chunking"), "SEMANTIC_CHUNKING"),
        full_disambig=_parse_task_model_settings(data.get("full_disambig"), "FULL_DISAMBIG"),
        level3_rerank=_parse_task_model_settings(data.get("level3_rerank"), "LEVEL3_RERANK"),
        diagnosis=_parse_task_model_settings(data.get("diagnosis"), "DIAGNOSIS"),
    )


def _parse_thinking_settings(data: dict[str, Any] | None) -> ThinkingSettings:
    """
    解析thinking配置
    """
    if not data:
        raise ValueError("thinking 配置不能为空，请检查 config/settings.json 中的 thinking 配置项")
    settings = ThinkingSettings(
        annotation=data.get("annotation", False),
        annotation_fallback=data.get("annotation_fallback", True),
        incremental_disambig=data.get("incremental_disambig", True),
        mention_extraction=data.get("mention_extraction", False),
        full_disambig=data.get("full_disambig", True),
        level3_rerank=data.get("level3_rerank", False),
        diagnosis=data.get("diagnosis", True),
        phase3_candidates_per_batch=data.get("phase3_candidates_per_batch", 5),
        phase3_batch_parallelism=data.get("phase3_batch_parallelism", 2),
    )
    settings.validate()
    return settings


def _parse_streaming_settings(data: dict[str, Any] | None) -> StreamingSettings:
    """
    解析streaming配置
    """
    if not data:
        return StreamingSettings()
    return StreamingSettings(
        annotation=data.get("annotation", False),
        annotation_fallback=data.get("annotation_fallback", True),
        incremental_disambig=data.get("incremental_disambig", True),
        mention_extraction=data.get("mention_extraction", False),
        full_disambig=data.get("full_disambig", True),
        level3_rerank=data.get("level3_rerank", False),
        diagnosis=data.get("diagnosis", True),
        cloud_only=data.get("cloud_only", True),
    )
