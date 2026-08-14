"""
数据库连接对象环境变量解析工具
"""

from __future__ import annotations

from typing import Literal, overload

from sqlalchemy.engine import make_url

from src.runtime_env import DatabaseEnvironmentName, load_database_environment


@overload
def resolve_database_url_from_env(
    env_var_name: DatabaseEnvironmentName,
    *,
    required: Literal[True] = True,
) -> str: ...


@overload
def resolve_database_url_from_env(
    env_var_name: DatabaseEnvironmentName,
    *,
    required: Literal[False],
) -> str | None: ...


def resolve_database_url_from_env(
    env_var_name: DatabaseEnvironmentName,
    *,
    required: bool = True,
) -> str | None:
    """
    2026-08-08 用于从数据库平铺变量生成完整 SQLAlchemy URL
    """

    database_environment = load_database_environment(env_var_name, required=required)
    if database_environment is None:
        return None

    try:
        url = make_url(database_environment.url)
    except Exception as exc:
        raise ValueError(f"{env_var_name}_URL 不是有效数据库 URL") from exc

    if url.username is not None or url.password is not None:
        raise ValueError(
            f"{env_var_name}_URL 不允许包含账号密码，请使用 "
            f"{env_var_name}_USERNAME 和 {env_var_name}_PASSWORD"
        )

    return url.set(
        username=database_environment.username,
        password=database_environment.password,
    ).render_as_string(hide_password=False)
