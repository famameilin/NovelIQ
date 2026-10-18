"""
本模块包含模型相关的配置数据类
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

from src.config.runtime_env import ModelEnvironment


@dataclass
class WeightedModelSettings:
    """每个模型独立拥有连接、采样参数、标注分配权重和物理请求并发上限

    池内不同模型可各自指定采样与输出上限，随加权选择一并生效。
    """

    model_id: str
    base_url: str
    api_key: str = field(repr=False)
    temperature: float = 0.7
    top_p: float = 0.8
    # 显式封顶 128K：思考模式补全上限不依赖 provider 默认值
    max_tokens: int = 131072
    weight: float = 1.0
    max_in_flight: int = 8


@dataclass
class TaskModelSettings:
    """
    任务模型配置（含 Agent 运行参数与行为开关）
    """

    timeout_s: float | None = None
    thinking: bool = False
    max_iterations: int = 15
    total_attempts: int = 3
    # 标注期不能读取未来章节原文
    allow_future_context: bool = False
    # 章正文超过该字数派发三条职责 Agent 并发，不超线走单 agent 路径
    sub_chunk_max_chars: int = 3500


@dataclass
class EmbeddingModelSettings:
    """嵌入模型配置

    嵌入维度不在配置中：以嵌入服务探测输出为准，pgvector 列宽建表时按探测值固化。
    """

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_s: float | None = None
    batch_size: int = 8
    semantic_enabled: bool = True
    top_k: int = 5


@dataclass
class ModelsSettings:
    """
    任务级模型配置集合
    """

    model_pool: list[WeightedModelSettings] = field(default_factory=list)
    diagnosis_model_id: str | None = None
    annotation: TaskModelSettings = field(default_factory=TaskModelSettings)
    paragraph_embedding: EmbeddingModelSettings = field(default_factory=EmbeddingModelSettings)
    diagnosis: TaskModelSettings = field(default_factory=lambda: TaskModelSettings(max_iterations=15))


def _positive_integer(data: dict[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"models.{key} 必须是正整数")
    return value


_POOL_REQUIRED_KEYS = {"model_id", "base_url", "api_key", "weight", "max_in_flight"}
# 采样参数随模型池条目可选提供，缺省用模型级默认
_POOL_SAMPLING_KEYS = {"temperature", "top_p", "max_tokens"}


def _parse_pool_sampling(item: dict[str, Any]) -> tuple[float, float, int]:
    """
    解析模型级采样参数（temperature/top_p/max_tokens）
    缺省回退模型级默认；越界或类型错误直接拒绝整个模型池。
    """

    temperature = item.get("temperature", 0.7)
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not math.isfinite(temperature)
        or not 0 <= temperature <= 2
    ):
        raise ValueError("模型温度必须是 [0, 2] 内的数值")
    top_p = item.get("top_p", 0.8)
    if (
        isinstance(top_p, bool)
        or not isinstance(top_p, (int, float))
        or not math.isfinite(top_p)
        or not 0 <= top_p <= 1
    ):
        raise ValueError("模型 top_p 必须是 [0, 1] 内的数值")
    max_tokens = item.get("max_tokens", 131072)
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
        raise ValueError("模型输出 Token 上限必须是正整数")
    return float(temperature), float(top_p), max_tokens


def _parse_model_pool(value: Any) -> list[WeightedModelSettings]:
    """标注至少有一个正权重模型；诊断可指定零权重模型"""
    if not isinstance(value, list) or not value:
        raise ValueError("模型池不能为空")
    result: list[WeightedModelSettings] = []
    for item in value:
        keys = set(item) if isinstance(item, dict) else set()
        if not _POOL_REQUIRED_KEYS <= keys or not keys <= _POOL_REQUIRED_KEYS | _POOL_SAMPLING_KEYS:
            raise ValueError("每个模型必须配置 URL、Key、ID、权重和并发")
        name, weight = item["model_id"], item["weight"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("模型 ID 不能为空")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight < 0:
            raise ValueError("模型权重必须是非负有限数值")
        base_url, api_key = item["base_url"], item["api_key"]
        if not isinstance(base_url, str) or any(char in base_url for char in "\r\n\0"):
            raise ValueError("模型 URL 无效")
        try:
            url = urlsplit(base_url.strip())
            valid_url = url.scheme in {"http", "https"} and bool(url.hostname) and url.port != 0
        except ValueError:
            valid_url = False
        if not valid_url or url.username or url.password or url.query or url.fragment:
            raise ValueError("模型 URL 必须是无内嵌凭据的 HTTP 或 HTTPS 服务地址")
        if not isinstance(api_key, str) or not api_key.strip() or any(char in api_key for char in "\r\n\0"):
            raise ValueError("模型 Key 必须是非空单行字符串")
        concurrency = item["max_in_flight"]
        if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
            raise ValueError("模型并发必须是正整数")
        temperature, top_p, max_tokens = _parse_pool_sampling(item)
        result.append(
            WeightedModelSettings(
                model_id=name.strip(),
                base_url=base_url.strip().rstrip("/"),
                api_key=api_key,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                weight=float(weight),
                max_in_flight=concurrency,
            )
        )
    if len({item.model_id for item in result}) != len(result):
        raise ValueError("模型 ID 不能重复")
    if not any(item.weight > 0 for item in result):
        raise ValueError("至少一个模型的权重必须大于零")
    return result


def _is_running_in_docker_container() -> bool:
    """判断当前后端是否运行在 Docker 容器内"""

    return os.path.exists("/.dockerenv")


def _replace_url_hostname(parts: SplitResult, new_hostname: str) -> str:
    """保留原 URL 的协议、端口、路径和鉴权信息，仅替换主机名。"""

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
    """容器内运行时把模型地址的 localhost/127.0.0.1/::1 改写为 host.docker.internal，数据库 URL 等非模型地址不走这里"""

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


def _parse_task_model_settings(data: dict[str, Any] | None, *, default_iterations: int = 15) -> TaskModelSettings:
    """解析任务模型的非敏感行为参数"""

    json_data = data or {}
    return TaskModelSettings(
        timeout_s=json_data.get("timeout_s"),
        thinking=json_data.get("thinking", False),
        max_iterations=_positive_integer(json_data, "max_iterations", default_iterations),
        total_attempts=_positive_integer(json_data, "total_attempts", 3),
        allow_future_context=json_data.get("allow_future_context", False),
        sub_chunk_max_chars=_positive_integer(json_data, "sub_chunk_max_chars", 3500),
    )


def _parse_embedding_model_settings(data: dict[str, Any] | None) -> EmbeddingModelSettings:
    """解析嵌入模型的非敏感行为参数"""

    json_data = data or {}

    return EmbeddingModelSettings(
        timeout_s=json_data.get("timeout_s"),
        batch_size=json_data.get("batch_size", 8),
        semantic_enabled=json_data.get("semantic_enabled", True),
        top_k=json_data.get("top_k", 5),
    )


def _parse_models_settings(data: dict[str, Any] | None) -> ModelsSettings:
    """解析任务级模型行为配置集合"""
    if not data:
        data = {}
    if "model_pool" in data or "diagnosis_model_id" in data:
        raise ValueError("模型池和诊断模型请通过模型池配置接口保存")
    diagnosis = _parse_task_model_settings(data.get("diagnosis"))
    return ModelsSettings(
        annotation=_parse_task_model_settings(data.get("annotation")),
        paragraph_embedding=_parse_embedding_model_settings(data.get("paragraph_embedding")),
        diagnosis=diagnosis,
    )


def apply_model_environment(
    settings: ModelsSettings,
    model_pool: list[dict[str, Any]],
    embedding_environment: ModelEnvironment | None,
) -> None:
    """凭据只来自环境；任务配置仅保留行为参数"""
    settings.model_pool = _parse_model_pool(model_pool) if model_pool else []
    for entry in settings.model_pool:
        entry.base_url = _normalize_model_base_url_for_docker(entry.base_url) or entry.base_url
    selected = os.environ.get("DIAGNOSIS_MODEL_ID")
    settings.diagnosis_model_id = selected.strip() if selected else None
    if settings.diagnosis_model_id and not any(
        entry.model_id == settings.diagnosis_model_id for entry in settings.model_pool
    ):
        raise ValueError("指定的诊断模型不在模型池中")

    if embedding_environment is not None:
        settings.paragraph_embedding.base_url = _normalize_model_base_url_for_docker(embedding_environment.base_url)
        settings.paragraph_embedding.model = embedding_environment.model
        settings.paragraph_embedding.api_key = embedding_environment.api_key
