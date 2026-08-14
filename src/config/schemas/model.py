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
class TaskModelSettings:
    """
    任务模型配置（含 Agent 运行参数与行为开关）
    """

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_s: float | None = None
    temperature: float = 0.7
    top_p: float = 0.8
    thinking: bool = False
    streaming: bool = False
    structured_output: str = "json_schema"
    max_iterations: int = 10
    total_attempts: int = 3
    allow_future_context: bool = False
    # 2026-08-14 M7（§20）：章文本超过该字符数时在段落边界切成 Agent 运行时子块
    sub_chunk_max_chars: int = 5000


@dataclass
class EmbeddingModelSettings:
    """嵌入模型配置"""

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_s: float | None = None
    embedding_dim: int = 1536
    batch_size: int = 8
    semantic_enabled: bool = True
    top_k: int = 5


@dataclass
class ModelsSettings:
    """
    任务级模型配置集合
    """

    annotation: TaskModelSettings = field(default_factory=TaskModelSettings)
    paragraph_embedding: EmbeddingModelSettings = field(default_factory=EmbeddingModelSettings)
    diagnosis: TaskModelSettings = field(default_factory=TaskModelSettings)


_STRUCTURED_OUTPUT_ALLOWED_MODES = {"json_schema", "json_object"}


def _parse_structured_output_mode(data: dict[str, Any], key: str, default: str) -> str:
    """
    解析单个结构化输出模式
    """
    mode = data.get(key, default)
    if mode not in _STRUCTURED_OUTPUT_ALLOWED_MODES:
        allowed = ", ".join(sorted(_STRUCTURED_OUTPUT_ALLOWED_MODES))
        raise ValueError(f"models.{key}.structured_output 必须是以下值之一: {allowed}")
    return mode


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
        thinking=json_data.get("thinking", False),
        streaming=json_data.get("streaming", False),
        structured_output=_parse_structured_output_mode(
            json_data,
            "structured_output",
            TaskModelSettings().structured_output,
        ),
        max_iterations=json_data.get("max_iterations", 10),
        total_attempts=json_data.get("total_attempts", 3),
        allow_future_context=json_data.get("allow_future_context", False),
        sub_chunk_max_chars=json_data.get("sub_chunk_max_chars", 5000),
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
        semantic_enabled=json_data.get("semantic_enabled", True),
        top_k=json_data.get("top_k", 5),
    )


def _parse_models_settings(data: dict[str, Any] | None) -> ModelsSettings:
    """
    2026-08-03 用于解析任务级模型行为配置集合
    """
    if not data:
        data = {}
    return ModelsSettings(
        annotation=_parse_task_model_settings(data.get("annotation")),
        paragraph_embedding=_parse_embedding_model_settings(data.get("paragraph_embedding")),
        diagnosis=_parse_task_model_settings(data.get("diagnosis")),
    )


def apply_model_environment(
    settings: ModelsSettings,
    model_environment: ModelEnvironment | None,
    embedding_environment: ModelEnvironment | None,
) -> None:
    """
    2026-08-03 用于把两个模型环境对象映射到当前任务配置
    2026-08-12 环境变量缺失降级：None 表示该组未配置，保留 settings.json 的对应值
    """

    # 2026-08-14 P1：两组环境必须独立降级。此前 model_environment is None 时提前 return，
    # 会连带跳过已配置的 EMBEDDING_MODEL_*；改为两个独立 if，各自缺失各自保留 settings.json 值
    if model_environment is not None:
        model_base_url = _normalize_model_base_url_for_docker(model_environment.base_url)
        for task_settings in (
            settings.annotation,
            settings.diagnosis,
        ):
            task_settings.base_url = model_base_url
            task_settings.model = model_environment.model
            task_settings.api_key = model_environment.api_key

    if embedding_environment is not None:
        settings.paragraph_embedding.base_url = _normalize_model_base_url_for_docker(
            embedding_environment.base_url
        )
        settings.paragraph_embedding.model = embedding_environment.model
        settings.paragraph_embedding.api_key = embedding_environment.api_key
