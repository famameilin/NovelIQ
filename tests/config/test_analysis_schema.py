from src.config.schemas import _parse_rag_settings
from src.config.schemas.analysis import _parse_agent_settings


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


def test_parse_rag_settings_uses_top_k_as_level3_fallback() -> None:
    settings = _parse_rag_settings(
        {
            "top_k": 4,
            "level3_enabled": True,
        }
    )

    assert settings.top_k == 4
    assert settings.level3_top_k == 4


def test_parse_rag_settings_ignores_removed_mention_and_rerank_fields() -> None:
    settings = _parse_rag_settings(
        {
            "mention_extraction_enabled": True,
            "level3_rerank_enabled": True,
            "level3_max_queries": 6,
        }
    )

    assert not hasattr(settings, "mention_extraction_enabled")
    assert not hasattr(settings, "level3_rerank_enabled")
    assert not hasattr(settings, "level3_max_queries")


def test_parse_agent_settings_reads_annotation_and_diagnosis_limits() -> None:
    settings = _parse_agent_settings(
        {
            "annotation": {
                "max_iterations": 5,
                "max_sub_agents": 4,
                "active_setup_pool_limit": 12,
            },
            "diagnosis": {
                "max_iterations": 9,
            },
        }
    )

    assert settings.annotation.max_iterations == 5
    assert settings.annotation.max_sub_agents == 4
    assert settings.annotation.active_setup_pool_limit == 12
    assert settings.diagnosis.max_iterations == 9


def test_parse_agent_settings_defaults() -> None:
    settings = _parse_agent_settings(None)

    assert settings.annotation.max_iterations == 10
    assert settings.annotation.max_sub_agents == 8
    assert settings.annotation.active_setup_pool_limit == 30
    assert settings.diagnosis.max_iterations == 15
