"""
本模块包含模型相关的配置数据类
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

from src.runtime_env import ModelEnvironment


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
    paragraph_embedding: EmbeddingModelSettings = field(default_factory=EmbeddingModelSettings)
    diagnosis: TaskModelSettings = field(default_factory=TaskModelSettings)


@dataclass
class ThinkingSettings:
    """
    各任务thinking开关配置
    """

    annotation: bool = False
    annotation_fallback: bool = True
    diagnosis: bool = True

    def validate(self) -> None:
        """验证配置"""
        pass


@dataclass
class StreamingSettings:
    """
    各任务streaming开关配置
    """

    annotation: bool = False
    annotation_fallback: bool = True
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
        diagnosis=_parse_structured_output_mode(json_data, "diagnosis", defaults.diagnosis),
        provider_overrides=normalized_provider_overrides,
    )


def _is_running_in_docker_container() -> bool:
    """
    2026-05-01: Docker 本机模型地址自动兼容
    任务: docker-model-base-url-autofix
    说明: 仅用于判断当前后端是否运行在 Docker 容器内，避免把宿主机源码运行时的 localhost 配置误改写。
    """

    return os.path.exists("/.dockerenv")


def _replace_url_hostname(parts: SplitResult, new_hostname: str) -> str:
    """
    2026-05-01: Docker 本机模型地址自动兼容
    任务: docker-model-base-url-autofix
    说明: 保留原 URL 的协议、端口、路径和鉴权信息，仅替换主机名。
    """

    auth_prefix = ""
    if parts.username is not None:
        auth_prefix = parts.username
        if parts.password is not None:
            auth_prefix = f"{auth_prefix}:{parts.password}"
        auth_prefix = f"{auth_prefix}@"

    port_suffix = f":{parts.port}" if parts.port is not None else ""
    host_text = f"[{new_hostname}]" if ":" in new_hostname and not new_hostname.startswith("[") else new_hostname
    return urlunsplit(
        (
            parts.scheme,
            f"{auth_prefix}{host_text}{port_suffix}",
            parts.path,
            parts.query,
            parts.fragment,
        )
    )


def _normalize_model_base_url_for_docker(base_url: str | None) -> str | None:
    """
    2026-05-01: Docker 本机模型地址自动兼容
    任务: docker-model-base-url-autofix
    说明: 当后端运行在 Docker 容器内时，把模型配置里误写的 localhost/127.0.0.1/::1
    自动改写为 host.docker.internal，降低部署文档理解门槛；数据库 URL 等非模型地址不走这里。
    """

    if not base_url or not _is_running_in_docker_container():
        return base_url

    try:
        parts = urlsplit(base_url)
    except ValueError:
        return base_url

    hostname = parts.hostname
    if not hostname:
        return base_url

    normalized_hostname = hostname.strip().lower()
    if normalized_hostname not in {"localhost", "127.0.0.1", "::1"}:
        return base_url

    host_alias = os.getenv("HOST_DOCKER_INTERNAL_ALIAS", "host.docker.internal").strip() or "host.docker.internal"
    return _replace_url_hostname(parts, host_alias)


def _parse_task_model_settings(data: dict[str, Any] | None) -> TaskModelSettings:
    """
    2026-08-03 用于解析任务模型的非敏感行为参数
    """

    json_data = data or {}

    return TaskModelSettings(
        timeout_s=json_data.get("timeout_s"),
        temperature=json_data.get("temperature", 0.7),
        top_p=json_data.get("top_p", 0.8),
    )


def _parse_embedding_model_settings(data: dict[str, Any] | None) -> EmbeddingModelSettings:
    """
    2026-08-03 用于解析嵌入模型的非敏感行为参数
    """

    json_data = data or {}

    return EmbeddingModelSettings(
        timeout_s=json_data.get("timeout_s"),
        embedding_dim=json_data.get("embedding_dim", 1536),
        batch_size=json_data.get("batch_size", 8),
    )


def _parse_models_settings(data: dict[str, Any] | None) -> ModelsSettings:
    """
    2026-08-03 用于解析任务级模型行为配置集合
    """
    if not data:
        data = {}
    return ModelsSettings(
        annotation=_parse_task_model_settings(data.get("annotation")),
        annotation_fallback=_parse_task_model_settings(data.get("annotation_fallback")),
        paragraph_embedding=_parse_embedding_model_settings(data.get("paragraph_embedding")),
        diagnosis=_parse_task_model_settings(data.get("diagnosis")),
    )


def apply_model_environment(
    settings: ModelsSettings,
    model_environment: ModelEnvironment,
    embedding_environment: ModelEnvironment,
) -> None:
    """
    2026-08-03 用于把两个模型环境对象映射到当前任务配置
    """

    model_base_url = _normalize_model_base_url_for_docker(model_environment.base_url)
    for task_settings in (
        settings.annotation,
        settings.annotation_fallback,
        settings.diagnosis,
    ):
        task_settings.base_url = model_base_url
        task_settings.model = model_environment.model
        task_settings.api_key = model_environment.api_key

    settings.paragraph_embedding.base_url = _normalize_model_base_url_for_docker(
        embedding_environment.base_url
    )
    settings.paragraph_embedding.model = embedding_environment.model
    settings.paragraph_embedding.api_key = embedding_environment.api_key


def _parse_thinking_settings(data: dict[str, Any] | None) -> ThinkingSettings:
    """
    解析thinking配置
    """
    if not data:
        raise ValueError("thinking 配置不能为空，请检查 config/settings.json 中的 thinking 配置项")
    settings = ThinkingSettings(
        annotation=data.get("annotation", False),
        annotation_fallback=data.get("annotation_fallback", True),
        diagnosis=data.get("diagnosis", True),
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
        diagnosis=data.get("diagnosis", True),
        cloud_only=data.get("cloud_only", True),
    )
