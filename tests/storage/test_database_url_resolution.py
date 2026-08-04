import json

import pytest
from sqlalchemy.engine import make_url

from src.storage.database_url import resolve_database_url_from_env


def test_resolve_database_url_from_json_object(monkeypatch) -> None:
    """
    2026-08-03 用于验证数据库 JSON 对象生成完整连接地址
    """

    monkeypatch.setenv(
        "DATABASE",
        json.dumps(
            {
                "url": "postgresql+psycopg://localhost:5432/novel_analysis",
                "username": "postgres",
                "password": "secret",
            }
        ),
    )

    database_url = resolve_database_url_from_env("DATABASE")

    assert database_url == "postgresql+psycopg://postgres:secret@localhost:5432/novel_analysis"


def test_resolve_test_database_url_uses_its_own_credentials(monkeypatch) -> None:
    """
    2026-08-03 用于验证测试数据库对象不再回退开发库凭据
    """

    monkeypatch.setenv(
        "TEST_DATABASE",
        json.dumps(
            {
                "url": "postgresql+psycopg://localhost:5432/novel_analysis_test",
                "username": "tester",
                "password": "test-secret",
            }
        ),
    )

    database_url = resolve_database_url_from_env("TEST_DATABASE")

    assert database_url == "postgresql+psycopg://tester:test-secret@localhost:5432/novel_analysis_test"


def test_resolve_database_url_encodes_special_characters(monkeypatch) -> None:
    """
    2026-08-03 用于验证账号密码特殊字符由 SQLAlchemy URL 语义化编码
    """

    monkeypatch.setenv(
        "DATABASE",
        json.dumps(
            {
                "url": "postgresql+psycopg://localhost:5432/novel_analysis",
                "username": "user@example.com",
                "password": "p@ss:/?#",
            }
        ),
    )

    resolved_url = make_url(resolve_database_url_from_env("DATABASE"))

    assert resolved_url.username == "user@example.com"
    assert resolved_url.password == "p@ss:/?#"


def test_resolve_database_url_rejects_credentials_inside_url(monkeypatch) -> None:
    """
    2026-08-03 用于拒绝数据库 URL 与独立凭据双重配置
    """

    monkeypatch.setenv(
        "DATABASE",
        json.dumps(
            {
                "url": "postgresql+psycopg://legacy:secret@localhost:5432/novel_analysis",
                "username": "postgres",
                "password": "secret",
            }
        ),
    )

    with pytest.raises(ValueError, match=r"DATABASE\.url"):
        resolve_database_url_from_env("DATABASE")


def test_old_database_variables_do_not_satisfy_new_contract(monkeypatch) -> None:
    """
    2026-08-03 用于确认旧数据库变量不再形成兼容回退
    """

    monkeypatch.delenv("DATABASE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost:5432/novel_analysis")
    monkeypatch.setenv("DATABASE_USERNAME", "postgres")
    monkeypatch.setenv("DATABASE_PASSWORD", "secret")

    with pytest.raises(RuntimeError, match="DATABASE 环境变量未配置"):
        resolve_database_url_from_env("DATABASE")


def test_resolve_database_url_returns_none_when_optional_and_unset(monkeypatch) -> None:
    """
    2026-08-03 用于验证可选测试数据库对象保持空值语义
    """

    monkeypatch.delenv("TEST_DATABASE", raising=False)

    database_url = resolve_database_url_from_env("TEST_DATABASE", required=False)

    assert database_url is None
