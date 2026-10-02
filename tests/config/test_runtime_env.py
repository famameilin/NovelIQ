import json
from pathlib import Path

import pytest
from loguru import logger

from src.config.settings import Settings
from src.runtime_env import (
    load_database_environment,
    load_ltp_environment,
    load_model_environment,
    load_model_pool_environment,
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
    monkeypatch.setenv("MODEL_POOL", json.dumps([{
        "model_id": "text-model", "base_url": "https://api.example.com/v1", "api_key": " text-key ",
        "weight": 1, "max_in_flight": 3,
    }]))
    _set_model_environment(
        monkeypatch,
        "EMBEDDING_MODEL",
        base_url="http://localhost:8080/v1",
        model_id="embedding-model",
        key="embedding-key",
    )

    database = load_database_environment("DATABASE")
    test_database = load_database_environment("TEST_DATABASE")
    pool = load_model_pool_environment()
    embedding_model = load_model_environment("EMBEDDING_MODEL")

    assert database is not None
    assert database.username == "postgres"
    assert database.password == " secret "
    assert test_database is not None
    assert test_database.url.endswith("novel_analysis_test")
    assert pool[0]["model_id"] == "text-model"
    assert pool[0]["api_key"] == " text-key "
    assert embedding_model.base_url == "http://localhost:8080/v1"
    assert embedding_model.model == "embedding-model"


def test_load_model_environment_remains_unconfigured_when_flat_field_missing(monkeypatch) -> None:
    """
    嵌入连接字段缺失时保持未配置并记录缺失字段
    """

    _set_model_environment(
        monkeypatch,
        "EMBEDDING_MODEL",
        base_url="https://api.example.com/v1",
        model_id="text-model",
        key="key",
    )
    monkeypatch.delenv("EMBEDDING_MODEL_ID")

    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="WARNING")
    try:
        assert load_model_environment("EMBEDDING_MODEL") is None
    finally:
        logger.remove(handler_id)

    assert any("EMBEDDING_MODEL_ID" in message for message in messages)
    assert all("settings.json" not in message for message in messages)


def test_load_model_environment_rejects_blank_key(monkeypatch) -> None:
    """
    2026-08-08 用于验证空模型密钥被拒绝
    """

    _set_model_environment(
        monkeypatch,
        "EMBEDDING_MODEL",
        base_url="https://api.example.com/v1",
        model_id="text-model",
        key=" ",
    )

    with pytest.raises(ValueError, match="EMBEDDING_MODEL_KEY"):
        load_model_environment("EMBEDDING_MODEL")


def test_missing_pool_does_not_construct_legacy_shared_connection(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_POOL", raising=False)
    monkeypatch.setenv("MODEL_BASE_URL", "https://old.example/v1")
    monkeypatch.setenv("MODEL_ID", "old")
    monkeypatch.setenv("MODEL_KEY", "old-key")
    assert load_model_pool_environment() == []


@pytest.mark.parametrize("raw", ["", "not-json", "{}", '"model"'])
def test_model_pool_environment_rejects_non_array_json(monkeypatch, raw: str) -> None:
    monkeypatch.setenv("MODEL_POOL", raw)
    with pytest.raises(ValueError, match="JSON"):
        load_model_pool_environment()


def test_load_optional_database_environment_returns_none_when_flat_fields_are_absent(monkeypatch) -> None:
    """
    2026-08-08 用于验证可选数据库配置忽略旧变量并返回空值
    """

    for field in ("URL", "USERNAME", "PASSWORD"):
        monkeypatch.delenv(f"TEST_DATABASE_{field}", raising=False)
    monkeypatch.setenv("TEST_DATABASE", '{"url":"legacy"}')

    assert load_database_environment("TEST_DATABASE", required=False) is None


def test_settings_keeps_behavior_without_model_credentials(monkeypatch, tmp_path: Path) -> None:
    """
    凭据未配置时模型池和嵌入连接保持空值，行为参数仍可从文件读取
    """

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    # 2026-10-02 streaming 字段已删除：settings.json 中的残留键应被静默忽略
    (config_dir / "settings.json").write_text(
        '{"models":{"annotation":{"streaming":true,"timeout_s":180}}}', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    for variable in (
        "MODEL_POOL",
        "DIAGNOSIS_MODEL_ID",
        "EMBEDDING_MODEL_BASE_URL",
        "EMBEDDING_MODEL_ID",
        "EMBEDDING_MODEL_KEY",
    ):
        monkeypatch.delenv(variable, raising=False)

    settings = Settings.from_env()

    assert settings.models.model_pool == []
    assert settings.models.diagnosis_model_id is None
    assert settings.models.paragraph_embedding.base_url is None
    assert not hasattr(settings.models.annotation, "streaming")
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
