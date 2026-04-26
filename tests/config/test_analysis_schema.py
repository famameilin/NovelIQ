from src.config.schemas import _parse_rag_settings
from src.config.schemas.analysis import _parse_multi_phase_annotation_settings


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


def test_parse_multi_phase_annotation_settings_reads_active_setup_pool_limit() -> None:
    settings = _parse_multi_phase_annotation_settings(
        {
            "parallel": False,
            "include_phase2_evidence": True,
            "active_setup_pool_limit": 12,
        }
    )

    assert settings.include_phase2_evidence is True
    assert settings.active_setup_pool_limit == 12


def test_parse_multi_phase_annotation_settings_falls_back_when_limit_invalid() -> None:
    settings = _parse_multi_phase_annotation_settings(
        {
            "active_setup_pool_limit": 0,
        }
    )

    assert settings.active_setup_pool_limit == 30
