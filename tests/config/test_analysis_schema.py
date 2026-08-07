from src.config.schemas import _parse_text_retrieval_settings
from src.config.schemas.analysis import _parse_agent_settings


def test_parse_text_retrieval_settings_reads_semantic_fields() -> None:
    settings = _parse_text_retrieval_settings(
        {
            "semantic_enabled": False,
            "top_k": 9,
        }
    )

    assert settings.semantic_enabled is False
    assert settings.top_k == 9


def test_parse_text_retrieval_settings_defaults() -> None:
    settings = _parse_text_retrieval_settings(None)

    assert settings.semantic_enabled is True
    assert settings.top_k == 5


def test_parse_text_retrieval_settings_ignores_removed_rag_fields() -> None:
    settings = _parse_text_retrieval_settings(
        {
            "level3_enabled": True,
            "level3_top_k": 9,
            "level3_rerank_enabled": True,
        }
    )

    assert not hasattr(settings, "level3_enabled")
    assert not hasattr(settings, "level3_top_k")
    assert not hasattr(settings, "level3_rerank_enabled")


def test_parse_agent_settings_reads_annotation_and_diagnosis_limits() -> None:
    settings = _parse_agent_settings(
        {
            "annotation": {
                "max_iterations": 5,
                "total_attempts": 3,
                "retry_backoff_seconds": [1.0, 2.0],
                "active_setup_pool_limit": 12,
                "allow_future_context": True,
            },
            "diagnosis": {
                "max_iterations": 9,
            },
        }
    )

    assert settings.annotation.max_iterations == 5
    assert settings.annotation.total_attempts == 3
    assert settings.annotation.retry_backoff_seconds == (1.0, 2.0)
    assert settings.annotation.active_setup_pool_limit == 12
    assert settings.annotation.allow_future_context is True
    assert settings.diagnosis.max_iterations == 9


def test_parse_agent_settings_defaults() -> None:
    settings = _parse_agent_settings(None)

    assert settings.annotation.max_iterations == 10
    assert settings.annotation.total_attempts == 3
    assert settings.annotation.retry_backoff_seconds == (1.0, 2.0)
    assert settings.annotation.active_setup_pool_limit == 30
    assert settings.annotation.allow_future_context is False
    assert settings.diagnosis.max_iterations == 15


def test_parse_agent_settings_rejects_non_boolean_future_switch() -> None:
    """2026-08-07 用于验证后文开关只接受严格布尔值"""
    try:
        _parse_agent_settings(
            {
                "annotation": {
                    "allow_future_context": "false",
                }
            }
        )
    except ValueError as exc:
        assert "allow_future_context 必须是 bool" in str(exc)
    else:
        raise AssertionError("非布尔 allow_future_context 应被拒绝")
