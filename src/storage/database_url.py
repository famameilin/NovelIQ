"""
数据库连接串环境变量解析工具
"""

from __future__ import annotations

import os
from typing import Literal, overload

from sqlalchemy.engine import make_url


def _get_related_credential_env_names(env_var_name: str) -> tuple[list[str], list[str]]:
    """
    2026-05-01: 拆分数据库连接串中的账号密码
    任务: split-database-url-credentials
    说明: 根据 `DATABASE_URL` / `TEST_DATABASE_URL` 自动推导可配套使用的用户名和密码变量名，
    既支持显式的 `*_USERNAME` / `*_PASSWORD`，也兼容 Docker 场景下已有的 `POSTGRES_USER` / `POSTGRES_PASSWORD`。
    """

    base_name = env_var_name[:-4] if env_var_name.endswith("_URL") else env_var_name
    username_env_names = [f"{base_name}_USERNAME"]
    password_env_names = [f"{base_name}_PASSWORD"]

    if env_var_name == "DATABASE_URL":
        username_env_names.append("POSTGRES_USER")
        password_env_names.append("POSTGRES_PASSWORD")
    elif env_var_name == "TEST_DATABASE_URL":
        username_env_names.extend(["DATABASE_USERNAME", "POSTGRES_USER"])
        password_env_names.extend(["DATABASE_PASSWORD", "POSTGRES_PASSWORD"])

    return username_env_names, password_env_names


def _get_first_non_empty_env(env_names: list[str]) -> str | None:
    """
    2026-05-01: 拆分数据库连接串中的账号密码
    任务: split-database-url-credentials
    说明: 环境变量允许存在空字符串占位；这里统一按“去空白后仍非空”作为有效值判断。
    """

    for env_name in env_names:
        env_value = os.environ.get(env_name)
        if env_value is None:
            continue
        normalized_value = env_value.strip()
        if normalized_value:
            return normalized_value
    return None


@overload
def resolve_database_url_from_env(env_var_name: str, *, required: Literal[True] = True) -> str: ...


@overload
def resolve_database_url_from_env(env_var_name: str, *, required: Literal[False]) -> str | None: ...


def resolve_database_url_from_env(env_var_name: str, *, required: bool = True) -> str | None:
    """
    2026-05-01: 拆分数据库连接串中的账号密码
    任务: split-database-url-credentials
    说明: 支持把数据库基础地址和账号密码拆到多个环境变量中配置。
    修改时间: 2026-05-02
    修改原因: 默认 `required=True` 的调用路径实际上是 fail-closed；
              这里补 overload，把类型合同收窄为 `str`，修复数据库入口的 typecheck 回归。
    例如：
    - `DATABASE_URL=postgresql+psycopg://localhost:5432/novel_analysis`
    - `DATABASE_USERNAME=postgres`
    - `DATABASE_PASSWORD=secret`
    """

    raw_database_url = os.environ.get(env_var_name)
    if raw_database_url is None or not raw_database_url.strip():
        if required:
            raise RuntimeError(f"{env_var_name} environment variable is not set")
        return None

    normalized_database_url = raw_database_url.strip()
    try:
        url = make_url(normalized_database_url)
    except Exception:
        return normalized_database_url

    username_env_names, password_env_names = _get_related_credential_env_names(env_var_name)
    username = _get_first_non_empty_env(username_env_names)
    password = _get_first_non_empty_env(password_env_names)

    if username is not None:
        url = url.set(username=username)
    if password is not None:
        url = url.set(password=password)

    effective_username = username if username is not None else url.username
    effective_password = password if password is not None else url.password
    if effective_password is not None and effective_username is None:
        username_keys = ", ".join(username_env_names)
        raise RuntimeError(
            f"{env_var_name} provided a password but no username. "
            f"Please set one of: {username_keys}"
        )

    return url.render_as_string(hide_password=False)
