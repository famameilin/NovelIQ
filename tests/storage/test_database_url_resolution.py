from src.storage.database_url import resolve_database_url_from_env


def test_resolve_database_url_supports_split_credentials(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost:5432/novel_analysis")
    monkeypatch.setenv("DATABASE_USERNAME", "postgres")
    monkeypatch.setenv("DATABASE_PASSWORD", "secret")

    database_url = resolve_database_url_from_env("DATABASE_URL")

    assert database_url == "postgresql+psycopg://postgres:secret@localhost:5432/novel_analysis"


def test_resolve_test_database_url_falls_back_to_database_credentials(monkeypatch) -> None:
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+psycopg://localhost:5432/novel_analysis_test")
    monkeypatch.setenv("DATABASE_USERNAME", "postgres")
    monkeypatch.setenv("DATABASE_PASSWORD", "secret")

    database_url = resolve_database_url_from_env("TEST_DATABASE_URL")

    assert database_url == "postgresql+psycopg://postgres:secret@localhost:5432/novel_analysis_test"


def test_resolve_database_url_prefers_explicit_test_credentials(monkeypatch) -> None:
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+psycopg://localhost:5432/novel_analysis_test")
    monkeypatch.setenv("DATABASE_USERNAME", "postgres")
    monkeypatch.setenv("DATABASE_PASSWORD", "secret")
    monkeypatch.setenv("TEST_DATABASE_USERNAME", "tester")
    monkeypatch.setenv("TEST_DATABASE_PASSWORD", "test-secret")

    database_url = resolve_database_url_from_env("TEST_DATABASE_URL")

    assert database_url == "postgresql+psycopg://tester:test-secret@localhost:5432/novel_analysis_test"


def test_resolve_database_url_returns_none_when_optional_and_unset(monkeypatch) -> None:
    """
    创建时间: 2026-05-02
    任务: fix-database-url-typecheck-regression
    新建原因: 这次修复只收窄默认 `required=True` 的类型合同；
              需要补一条回归测试，确认 `required=False` 仍保持可选返回语义。
    """
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

    database_url = resolve_database_url_from_env("TEST_DATABASE_URL", required=False)

    assert database_url is None
