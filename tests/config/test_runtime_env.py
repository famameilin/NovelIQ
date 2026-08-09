import pytest

from src.runtime_env import load_database_environment, load_model_environment


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


def _set_model_environment(
    monkeypatch,
    prefix: str,
    *,
    base_url: str,
    model_id: str,
    key: str,
) -> None:
    monkeypatch.setenv(f"{prefix}_BASE_URL", base_url)
    monkeypatch.setenv(f"{prefix}_ID", model_id)
    monkeypatch.setenv(f"{prefix}_KEY", key)


def test_load_flat_environment_fields(monkeypatch) -> None:
    """
    2026-08-08 用于验证四组配置从平铺环境变量映射到内部对象
    """

    _set_database_environment(
        monkeypatch,
        "DATABASE",
        url="postgresql+psycopg://localhost:5432/novel_analysis",
        username="postgres",
        password=" secret ",
    )
    _set_database_environment(
        monkeypatch,
        "TEST_DATABASE",
        url="postgresql+psycopg://localhost:5432/novel_analysis_test",
        username="tester",
        password="test-secret",
    )
    _set_model_environment(
        monkeypatch,
        "MODEL",
        base_url="https://api.example.com/v1",
        model_id="text-model",
        key=" text-key ",
    )
    _set_model_environment(
        monkeypatch,
        "EMBEDDING_MODEL",
        base_url="http://localhost:8080/v1",
        model_id="embedding-model",
        key="embedding-key",
    )

    database = load_database_environment("DATABASE")
    test_database = load_database_environment("TEST_DATABASE")
    model = load_model_environment("MODEL")
    embedding_model = load_model_environment("EMBEDDING_MODEL")

    assert database is not None
    assert database.username == "postgres"
    assert database.password == " secret "
    assert test_database is not None
    assert test_database.url.endswith("novel_analysis_test")
    assert model.model == "text-model"
    assert model.api_key == " text-key "
    assert embedding_model.base_url == "http://localhost:8080/v1"
    assert embedding_model.model == "embedding-model"


def test_load_model_environment_requires_each_flat_field(monkeypatch) -> None:
    """
    2026-08-08 用于验证部分模型配置报告缺失的平铺字段
    """

    _set_model_environment(
        monkeypatch,
        "MODEL",
        base_url="https://api.example.com/v1",
        model_id="text-model",
        key="key",
    )
    monkeypatch.delenv("MODEL_ID")

    with pytest.raises(RuntimeError, match="MODEL_ID"):
        load_model_environment("MODEL")


def test_load_model_environment_rejects_blank_key(monkeypatch) -> None:
    """
    2026-08-08 用于验证空模型密钥被拒绝
    """

    _set_model_environment(
        monkeypatch,
        "MODEL",
        base_url="https://api.example.com/v1",
        model_id="text-model",
        key=" ",
    )

    with pytest.raises(ValueError, match="MODEL_KEY"):
        load_model_environment("MODEL")


def test_load_model_environment_ignores_legacy_json_value(monkeypatch) -> None:
    """
    2026-08-08 用于确认旧 JSON 变量不能替代平铺模型变量
    """

    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("MODEL_ID", raising=False)
    monkeypatch.delenv("MODEL_KEY", raising=False)
    monkeypatch.setenv("MODEL", '{"base_url":"https://api.example.com/v1","model":"legacy-model"}')

    with pytest.raises(RuntimeError, match="MODEL"):
        load_model_environment("MODEL")


def test_load_optional_database_environment_returns_none_when_flat_fields_are_absent(monkeypatch) -> None:
    """
    2026-08-08 用于验证可选数据库配置忽略旧变量并返回空值
    """

    for field in ("URL", "USERNAME", "PASSWORD"):
        monkeypatch.delenv(f"TEST_DATABASE_{field}", raising=False)
    monkeypatch.setenv("TEST_DATABASE", '{"url":"legacy"}')

    assert load_database_environment("TEST_DATABASE", required=False) is None
