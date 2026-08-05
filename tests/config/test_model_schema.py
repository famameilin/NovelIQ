from src.config.schemas import _parse_embedding_model_settings, _parse_models_settings
from src.config.schemas.model import apply_model_environment
from src.runtime_env import ModelEnvironment


def test_parse_embedding_model_settings_includes_runtime_parameters() -> None:
    """
    2026-08-03 用于验证 Embedding 行为参数继续来自 settings JSON
    """

    settings = _parse_embedding_model_settings(
        {
            "timeout_s": 120,
            "embedding_dim": 1024,
            "batch_size": 8,
        }
    )

    assert settings.base_url is None
    assert settings.model is None
    assert settings.timeout_s == 120
    assert settings.embedding_dim == 1024
    assert settings.batch_size == 8


def test_old_model_environment_variables_do_not_override_json(monkeypatch) -> None:
    """
    2026-08-03 用于确认旧模型变量不再覆盖行为配置
    """

    monkeypatch.setenv("SEMANTIC_CHUNKING_EMBEDDING_DIM", "3072")
    monkeypatch.setenv("SEMANTIC_CHUNKING_BATCH_SIZE", "16")

    settings = _parse_embedding_model_settings(
        {
            "embedding_dim": 1536,
            "batch_size": 8,
        }
    )

    assert settings.embedding_dim == 1536
    assert settings.batch_size == 8


def test_apply_model_environment_shares_text_model() -> None:
    """
    2026-08-05 用于验证 annotation 与 diagnosis 共享 MODEL
    """

    settings = _parse_models_settings(
        {
            "annotation": {"timeout_s": 180},
            "paragraph_embedding": {"timeout_s": 120},
            "diagnosis": {"timeout_s": 180},
        }
    )

    apply_model_environment(
        settings,
        ModelEnvironment(
            base_url="https://api.example.com/v1",
            model="text-model",
            api_key="text-key",
        ),
        ModelEnvironment(
            base_url="http://localhost:8080/v1",
            model="embedding-model",
            api_key="sk-no-key-required",
        ),
    )

    assert settings.annotation.model == "text-model"
    assert settings.diagnosis.model == "text-model"
    assert settings.paragraph_embedding.model == "embedding-model"
    assert settings.annotation.timeout_s == 180
    assert settings.paragraph_embedding.timeout_s == 120


def test_apply_model_environment_rewrites_loopback_for_docker(monkeypatch) -> None:
    """
    2026-08-03 用于验证 Docker 内模型地址继续转换到宿主机
    """

    monkeypatch.setattr("src.config.schemas.model._is_running_in_docker_container", lambda: True)
    settings = _parse_models_settings({})

    apply_model_environment(
        settings,
        ModelEnvironment(
            base_url="http://localhost:8111/v1",
            model="text-model",
            api_key="text-key",
        ),
        ModelEnvironment(
            base_url="http://127.0.0.1:8080/v1",
            model="embedding-model",
            api_key="embedding-key",
        ),
    )

    assert settings.annotation.base_url == "http://host.docker.internal:8111/v1"
    assert settings.paragraph_embedding.base_url == "http://host.docker.internal:8080/v1"
