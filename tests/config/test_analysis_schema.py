from src.config.schemas import _parse_rag_settings


def test_parse_rag_settings_includes_level3_fields() -> None:
    settings = _parse_rag_settings(
        {
            "enabled": True,
            "embedding_enabled": True,
            "similarity_threshold": 0.8,
            "lookback_chunks": 12,
            "top_k": 4,
            "level1_enabled": True,
            "level2_enabled": False,
            "level3_enabled": False,
            "level3_top_k": 9,
        }
    )

    assert settings.level3_enabled is False
    assert settings.level3_top_k == 9

