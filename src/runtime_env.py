"""
平铺运行时环境配置解析
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from loguru import logger

DatabaseEnvironmentName = Literal["DATABASE", "TEST_DATABASE"]
ModelEnvironmentName = Literal["MODEL", "EMBEDDING_MODEL"]

_DATABASE_ENVIRONMENT_NAMES = {"DATABASE", "TEST_DATABASE"}
_MODEL_ENVIRONMENT_NAMES = {"MODEL", "EMBEDDING_MODEL"}

_DATABASE_FIELD_NAMES: dict[str, tuple[tuple[str, str], ...]] = {
    "DATABASE": (
        ("url", "DATABASE_URL"),
        ("username", "DATABASE_USERNAME"),
        ("password", "DATABASE_PASSWORD"),
    ),
    "TEST_DATABASE": (
        ("url", "TEST_DATABASE_URL"),
        ("username", "TEST_DATABASE_USERNAME"),
        ("password", "TEST_DATABASE_PASSWORD"),
    ),
}

_MODEL_FIELD_NAMES: dict[str, tuple[tuple[str, str], ...]] = {
    "MODEL": (
        ("base_url", "MODEL_BASE_URL"),
        ("model", "MODEL_ID"),
        ("api_key", "MODEL_KEY"),
    ),
    "EMBEDDING_MODEL": (
        ("base_url", "EMBEDDING_MODEL_BASE_URL"),
        ("model", "EMBEDDING_MODEL_ID"),
        ("api_key", "EMBEDDING_MODEL_KEY"),
    ),
}


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


def _load_flat_fields(
    env_var_name: str,
    fields: tuple[tuple[str, str], ...],
    *,
    required: bool,
) -> dict[str, str] | None:
    """读取一组平铺环境变量，并区分整组缺失与部分缺失。"""

    raw_values = {field_name: os.environ.get(environment_name) for field_name, environment_name in fields}
    configured_values = [value for value in raw_values.values() if value is not None and value.strip()]
    if not configured_values:
        if required:
            raise RuntimeError(f"{env_var_name} 环境变量未配置")
        return None

    validated_values: dict[str, str] = {}
    for field_name, environment_name in fields:
        value = raw_values[field_name]
        if value is None:
            raise RuntimeError(f"{environment_name} 环境变量未配置")
        if not value.strip():
            raise ValueError(f"{environment_name} 不能为空")
        validated_values[field_name] = value
    return validated_values


def _get_value(values: dict[str, str], field_name: str, *, preserve_whitespace: bool = False) -> str:
    """读取已校验的字段，并按字段语义处理首尾空白。"""

    value = values[field_name]
    return value if preserve_whitespace else value.strip()


def load_database_environment(
    env_var_name: DatabaseEnvironmentName,
    *,
    required: bool = True,
) -> DatabaseEnvironment | None:
    """加载数据库平铺环境变量。"""

    if env_var_name not in _DATABASE_ENVIRONMENT_NAMES:
        raise ValueError(f"不支持的数据库环境变量: {env_var_name}")

    values = _load_flat_fields(env_var_name, _DATABASE_FIELD_NAMES[env_var_name], required=required)
    if values is None:
        return None
    return DatabaseEnvironment(
        url=_get_value(values, "url"),
        username=_get_value(values, "username"),
        password=_get_value(values, "password", preserve_whitespace=True),
    )


def load_model_environment(env_var_name: ModelEnvironmentName) -> ModelEnvironment | None:
    """
    加载模型平铺环境变量。

    2026-08-12 模型变量整组缺失或部分缺失时不再抛 RuntimeError：
    返回 None 并记录 warning，由装配层（Settings.from_env）降级使用 settings.json 的值；
    字段存在但为空白时仍视为格式错误抛 ValueError。
    """

    if env_var_name not in _MODEL_ENVIRONMENT_NAMES:
        raise ValueError(f"不支持的模型环境变量: {env_var_name}")

    raw_values = {
        field_name: os.environ.get(environment_name)
        for field_name, environment_name in _MODEL_FIELD_NAMES[env_var_name]
    }
    blank_variables: list[str] = []
    for field_name, environment_name in _MODEL_FIELD_NAMES[env_var_name]:
        value = raw_values[field_name]
        if value is not None and not value.strip():
            blank_variables.append(environment_name)
    if blank_variables:
        raise ValueError(f"{', '.join(blank_variables)} 不能为空")

    missing_variables: list[str] = []
    for field_name, environment_name in _MODEL_FIELD_NAMES[env_var_name]:
        if raw_values[field_name] is None:
            missing_variables.append(environment_name)
    if missing_variables:
        logger.warning(
            f"{env_var_name} 环境变量缺失（{', '.join(missing_variables)}），模型配置降级使用 settings.json 值"
        )
        return None

    validated_values = {field_name: value for field_name, value in raw_values.items() if value is not None}
    return ModelEnvironment(
        base_url=_get_value(validated_values, "base_url"),
        model=_get_value(validated_values, "model"),
        api_key=_get_value(validated_values, "api_key", preserve_whitespace=True),
    )
