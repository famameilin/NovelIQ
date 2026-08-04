"""
四对象运行时环境配置解析
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Literal

DatabaseEnvironmentName = Literal["DATABASE", "TEST_DATABASE"]
ModelEnvironmentName = Literal["MODEL", "EMBEDDING_MODEL"]

_DATABASE_ENVIRONMENT_NAMES = {"DATABASE", "TEST_DATABASE"}
_MODEL_ENVIRONMENT_NAMES = {"MODEL", "EMBEDDING_MODEL"}


@dataclass(frozen=True)
class DatabaseEnvironment:
    """数据库环境配置"""

    url: str
    username: str
    password: str


@dataclass(frozen=True)
class ModelEnvironment:
    """模型服务环境配置"""

    base_url: str
    model: str
    api_key: str


def _load_json_object(env_var_name: str, *, required: bool) -> dict[str, object] | None:
    """
    2026-08-03 用于读取并校验 JSON 对象环境变量
    """

    raw_value = os.environ.get(env_var_name)
    if raw_value is None or not raw_value.strip():
        if required:
            raise RuntimeError(f"{env_var_name} 环境变量未配置")
        return None

    try:
        parsed_value = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{env_var_name} 必须是有效 JSON 对象") from exc

    if not isinstance(parsed_value, dict):
        raise ValueError(f"{env_var_name} 必须是 JSON 对象")
    return parsed_value


def _require_string_field(
    config: dict[str, object],
    env_var_name: str,
    field_name: str,
    *,
    preserve_whitespace: bool = False,
) -> str:
    """
    2026-08-03 用于读取必填字符串子字段并报告完整字段路径
    """

    value = config.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"{env_var_name}.{field_name} 必须是字符串")
    if not value.strip():
        raise ValueError(f"{env_var_name}.{field_name} 不能为空")
    return value if preserve_whitespace else value.strip()


def load_database_environment(
    env_var_name: DatabaseEnvironmentName,
    *,
    required: bool = True,
) -> DatabaseEnvironment | None:
    """
    2026-08-03 用于加载数据库 JSON 环境对象
    """

    if env_var_name not in _DATABASE_ENVIRONMENT_NAMES:
        raise ValueError(f"不支持的数据库环境变量: {env_var_name}")

    config = _load_json_object(env_var_name, required=required)
    if config is None:
        return None
    return DatabaseEnvironment(
        url=_require_string_field(config, env_var_name, "url"),
        username=_require_string_field(config, env_var_name, "username"),
        password=_require_string_field(
            config,
            env_var_name,
            "password",
            preserve_whitespace=True,
        ),
    )


def load_model_environment(env_var_name: ModelEnvironmentName) -> ModelEnvironment:
    """
    2026-08-03 用于加载模型 JSON 环境对象
    """

    if env_var_name not in _MODEL_ENVIRONMENT_NAMES:
        raise ValueError(f"不支持的模型环境变量: {env_var_name}")

    config = _load_json_object(env_var_name, required=True)
    if config is None:
        raise RuntimeError(f"{env_var_name} 环境变量未配置")
    return ModelEnvironment(
        base_url=_require_string_field(config, env_var_name, "base_url"),
        model=_require_string_field(config, env_var_name, "model"),
        api_key=_require_string_field(
            config,
            env_var_name,
            "api_key",
            preserve_whitespace=True,
        ),
    )
