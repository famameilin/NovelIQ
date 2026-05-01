from src.config.schemas import _parse_embedding_model_settings, _parse_task_model_settings


def test_parse_embedding_model_settings_includes_dimension() -> None:
    settings = _parse_embedding_model_settings(
        {
            "base_url": "http://localhost:8000",
            "model": "test-embedding-model",
            "embedding_dim": 1024,
            "batch_size": 8,
        }
    )

    assert settings.model == "test-embedding-model"
    assert settings.embedding_dim == 1024
    assert settings.batch_size == 8


def test_parse_embedding_model_settings_supports_env_override(monkeypatch) -> None:
    monkeypatch.setenv("SEMANTIC_CHUNKING_EMBEDDING_DIM", "3072")
    monkeypatch.setenv("SEMANTIC_CHUNKING_BATCH_SIZE", "16")

    settings = _parse_embedding_model_settings(
        {
            "embedding_dim": 1536,
            "batch_size": 8,
        },
        "SEMANTIC_CHUNKING",
    )

    assert settings.embedding_dim == 3072
    assert settings.batch_size == 16

    monkeypatch.delenv("SEMANTIC_CHUNKING_EMBEDDING_DIM", raising=False)
    monkeypatch.delenv("SEMANTIC_CHUNKING_BATCH_SIZE", raising=False)


def test_parse_task_model_settings_rewrites_localhost_for_docker(monkeypatch) -> None:
    monkeypatch.setattr("src.config.schemas.model._is_running_in_docker_container", lambda: True)

    settings = _parse_task_model_settings(
        {
            "base_url": "http://localhost:8111/v1",
            "model": "test-model",
        }
    )

    assert settings.base_url == "http://host.docker.internal:8111/v1"


def test_parse_embedding_model_settings_rewrites_loopback_for_docker(monkeypatch) -> None:
    monkeypatch.setattr("src.config.schemas.model._is_running_in_docker_container", lambda: True)

    settings = _parse_embedding_model_settings(
        {
            "base_url": "http://127.0.0.1:8081/v1",
            "model": "embedding-model",
        }
    )

    assert settings.base_url == "http://host.docker.internal:8081/v1"


def test_parse_task_model_settings_keeps_localhost_outside_docker(monkeypatch) -> None:
    monkeypatch.setattr("src.config.schemas.model._is_running_in_docker_container", lambda: False)

    settings = _parse_task_model_settings(
        {
            "base_url": "http://localhost:8111/v1",
            "model": "test-model",
        }
    )

    assert settings.base_url == "http://localhost:8111/v1"
