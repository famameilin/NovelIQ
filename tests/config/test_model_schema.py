from src.config.schemas import _parse_embedding_model_settings


def test_parse_embedding_model_settings_includes_dimension() -> None:
    settings = _parse_embedding_model_settings(
        {
            "base_url": "http://localhost:8000",
            "model": "test-embedding-model",
            "embedding_dim": 1024,
        }
    )

    assert settings.model == "test-embedding-model"
    assert settings.embedding_dim == 1024


def test_parse_embedding_model_settings_supports_env_override(monkeypatch) -> None:
    monkeypatch.setenv("SEMANTIC_CHUNKING_EMBEDDING_DIM", "3072")

    settings = _parse_embedding_model_settings(
        {
            "embedding_dim": 1536,
        },
        "SEMANTIC_CHUNKING",
    )

    assert settings.embedding_dim == 3072

    monkeypatch.delenv("SEMANTIC_CHUNKING_EMBEDDING_DIM", raising=False)
