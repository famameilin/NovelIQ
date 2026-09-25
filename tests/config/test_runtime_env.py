import pytest
from loguru import logger

from src.config.settings import Settings
from src.runtime_env import (
    load_database_environment,
    load_ltp_environment,
    load_model_environment,
)


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


def test_load_model_environment_degrades_when_flat_field_missing(monkeypatch) -> None:
    """
    2026-08-12 用于验证部分模型字段缺失时降级为 None 并记录 warning
    """

    _set_model_environment(
        monkeypatch,
        "MODEL",
        base_url="https://api.example.com/v1",
        model_id="text-model",
        key="key",
    )
    monkeypatch.delenv("MODEL_ID")

    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="WARNING")
    try:
        assert load_model_environment("MODEL") is None
    finally:
        logger.remove(handler_id)

    assert any("MODEL_ID" in message for message in messages)


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


def test_load_model_environment_degrades_when_group_fully_missing(monkeypatch) -> None:
    """
    2026-08-12 用于确认整组缺失（含旧 JSON 变量）时降级为 None 并记录 warning
    """

    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("MODEL_ID", raising=False)
    monkeypatch.delenv("MODEL_KEY", raising=False)
    monkeypatch.setenv("MODEL", '{"base_url":"https://api.example.com/v1","model":"legacy-model"}')

    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="WARNING")
    try:
        assert load_model_environment("MODEL") is None
    finally:
        logger.remove(handler_id)

    assert any("MODEL" in message for message in messages)


def test_load_optional_database_environment_returns_none_when_flat_fields_are_absent(monkeypatch) -> None:
    """
    2026-08-08 用于验证可选数据库配置忽略旧变量并返回空值
    """

    for field in ("URL", "USERNAME", "PASSWORD"):
        monkeypatch.delenv(f"TEST_DATABASE_{field}", raising=False)
    monkeypatch.setenv("TEST_DATABASE", '{"url":"legacy"}')

    assert load_database_environment("TEST_DATABASE", required=False) is None


def test_settings_from_env_degrades_to_json_when_model_environment_missing(monkeypatch) -> None:
    """
    2026-08-12 用于验证模型环境变量缺失时配置装配不再抛 RuntimeError：
    模型身份字段保持 settings.json 的默认值，行为参数继续来自 settings.json
    """

    for variable in (
        "MODEL_BASE_URL",
        "MODEL_ID",
        "MODEL_KEY",
        "EMBEDDING_MODEL_BASE_URL",
        "EMBEDDING_MODEL_ID",
        "EMBEDDING_MODEL_KEY",
    ):
        monkeypatch.delenv(variable, raising=False)

    settings = Settings.from_env()

    assert settings.models.annotation.base_url is None
    assert settings.models.annotation.model is None
    assert settings.models.paragraph_embedding.base_url is None
    assert settings.models.annotation.streaming is True
    assert settings.models.annotation.timeout_s == 180


def test_load_ltp_environment_reads_model_dir(monkeypatch) -> None:
    """
    2026-08-28 用于验证 LTP_MODEL_DIR 从平铺环境变量映射到内部对象
    """

    monkeypatch.setenv("LTP_MODEL_DIR", "models/ltp/small")

    ltp_environment = load_ltp_environment()

    assert ltp_environment is not None
    assert ltp_environment.model_dir == "models/ltp/small"


def test_load_ltp_environment_returns_none_when_unset_or_blank(monkeypatch) -> None:
    """
    2026-08-28 用于验证 LTP 整组未配置（缺失或空白）时返回 None，
    由装配层降级使用 settings.json 的 model_dir
    """

    monkeypatch.delenv("LTP_MODEL_DIR", raising=False)
    assert load_ltp_environment() is None

    monkeypatch.setenv("LTP_MODEL_DIR", "  ")
    assert load_ltp_environment() is None


def test_settings_from_env_applies_ltp_model_dir(monkeypatch) -> None:
    """
    2026-08-28 用于验证 LTP_MODEL_DIR 覆盖 settings.json 的 model_dir
    """

    monkeypatch.setenv("LTP_MODEL_DIR", "models/ltp/small")

    settings = Settings.from_env()

    assert settings.linguistic.ltp.model_dir == "models/ltp/small"


def test_settings_from_env_leaves_ltp_model_dir_empty_when_env_missing(monkeypatch) -> None:
    """
    2026-08-28 用于验证 LTP_MODEL_DIR 缺失时 model_dir 保持为空
    （LTP 模型目录仅由环境变量提供，不走 settings.json）
    """

    monkeypatch.delenv("LTP_MODEL_DIR", raising=False)

    settings = Settings.from_env()

    assert settings.linguistic.ltp.model_dir is None
