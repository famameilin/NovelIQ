import pytest
from sqlalchemy.engine import make_url

from src.storage.database_url import resolve_database_url_from_env


def _set_database_environment(
    monkeypatch,
    prefix: str,
    *,
    url: str,
    username: str,
    password: str,
) -> None:
    monkeypatch.setenv(f"{prefix}_URL", url)
    monkeypatch.setenv(f"{prefix}_USERNAME", username)
    monkeypatch.setenv(f"{prefix}_PASSWORD", password)


def test_resolve_database_url_from_flat_variables(monkeypatch) -> None:
    """
    2026-08-08 用于验证平铺数据库变量生成完整连接地址
    """

    _set_database_environment(
        monkeypatch,
        "DATABASE",
        url="postgresql+psycopg://localhost:5432/novel_analysis",
        username="postgres",
        password="secret",
    )

    database_url = resolve_database_url_from_env("DATABASE")

    assert database_url == "postgresql+psycopg://postgres:secret@localhost:5432/novel_analysis"


def test_resolve_test_database_url_uses_its_own_credentials(monkeypatch) -> None:
    """
    2026-08-08 用于验证测试数据库平铺变量不回退开发库凭据
    """

    _set_database_environment(
        monkeypatch,
        "TEST_DATABASE",
        url="postgresql+psycopg://localhost:5432/novel_analysis_test",
        username="tester",
        password="test-secret",
    )

    database_url = resolve_database_url_from_env("TEST_DATABASE")

    assert database_url == "postgresql+psycopg://tester:test-secret@localhost:5432/novel_analysis_test"


def test_resolve_database_url_encodes_special_characters(monkeypatch) -> None:
    """
    2026-08-03 用于验证账号密码特殊字符由 SQLAlchemy URL 语义化编码
    """

    _set_database_environment(
        monkeypatch,
        "DATABASE",
        url="postgresql+psycopg://localhost:5432/novel_analysis",
        username="user@example.com",
        password="p@ss:/?#",
    )

    resolved_url = make_url(resolve_database_url_from_env("DATABASE"))

    assert resolved_url.username == "user@example.com"
    assert resolved_url.password == "p@ss:/?#"


def test_resolve_database_url_rejects_credentials_inside_url(monkeypatch) -> None:
    """
    2026-08-03 用于拒绝数据库 URL 与独立凭据双重配置
    """

    _set_database_environment(
        monkeypatch,
        "DATABASE",
        url="postgresql+psycopg://legacy:secret@localhost:5432/novel_analysis",
        username="postgres",
        password="secret",
    )

    with pytest.raises(ValueError, match=r"DATABASE_URL"):
        resolve_database_url_from_env("DATABASE")


def test_flat_database_variables_satisfy_new_contract(monkeypatch) -> None:
    """
    2026-08-08 用于确认平铺数据库变量满足新契约
    """

    _set_database_environment(
        monkeypatch,
        "DATABASE",
        url="postgresql+psycopg://localhost:5432/novel_analysis",
        username="postgres",
        password="secret",
    )

    assert resolve_database_url_from_env("DATABASE").endswith("/novel_analysis")


def test_json_database_variable_does_not_satisfy_new_contract(monkeypatch) -> None:
    """
    2026-08-08 用于确认旧 JSON 数据库变量不能替代平铺变量
    """

    for field in ("URL", "USERNAME", "PASSWORD"):
        monkeypatch.delenv(f"DATABASE_{field}", raising=False)
    monkeypatch.setenv("DATABASE", '{"url":"postgresql+psycopg://localhost:5432/novel_analysis"}')

    with pytest.raises(RuntimeError, match="DATABASE"):
        resolve_database_url_from_env("DATABASE")


def test_resolve_database_url_returns_none_when_optional_and_unset(monkeypatch) -> None:
    """
    2026-08-03 用于验证可选测试数据库对象保持空值语义
    """

    for field in ("URL", "USERNAME", "PASSWORD"):
        monkeypatch.delenv(f"TEST_DATABASE_{field}", raising=False)

    database_url = resolve_database_url_from_env("TEST_DATABASE", required=False)

    assert database_url is None
