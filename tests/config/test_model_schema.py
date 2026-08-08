from src.config.schemas import (
    _parse_embedding_model_settings,
    _parse_models_settings,
    _parse_task_model_settings,
)
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
            "semantic_enabled": False,
            "top_k": 9,
        }
    )

    assert settings.base_url is None
    assert settings.model is None
    assert settings.timeout_s == 120
    assert settings.embedding_dim == 1024
    assert settings.batch_size == 8
    assert settings.semantic_enabled is False
    assert settings.top_k == 9


def test_parse_task_model_settings_reads_agent_and_behavior_fields() -> None:
    """
    2026-08-08 用于验证任务级配置合并 thinking/streaming/Agent 参数
    """
    settings = _parse_task_model_settings(
        {
            "timeout_s": 180,
            "temperature": 0.5,
            "top_p": 0.7,
            "thinking": True,
            "streaming": True,
            "cloud_only": False,
            "structured_output": "json_object",
            "max_iterations": 20,
            "total_attempts": 3,
            "retry_backoff_seconds": 5000,
            "allow_future_context": True,
        }
    )

    assert settings.timeout_s == 180
    assert settings.thinking is True
    assert settings.streaming is True
    assert settings.stream_cloud_only is False
    assert settings.structured_output == "json_object"
    assert settings.max_iterations == 20
    assert settings.total_attempts == 3
    assert settings.retry_backoff_ms == 5000
    assert settings.allow_future_context is True


def test_parse_task_model_settings_defaults() -> None:
    """
    2026-08-08 用于验证任务级配置默认值
    """
    settings = _parse_task_model_settings(None)

    assert settings.thinking is False
    assert settings.streaming is False
    assert settings.structured_output == "json_schema"
    assert settings.max_iterations == 10
    assert settings.total_attempts == 3
    assert settings.retry_backoff_ms == 5000
    assert settings.allow_future_context is False


def test_parse_task_model_settings_rejects_invalid_structured_output() -> None:
    """
    2026-08-08 用于验证结构化输出模式只接受闭合枚举
    """
    try:
        _parse_task_model_settings({"structured_output": "xml"})
    except ValueError as exc:
        assert "structured_output" in str(exc)
    else:
        raise AssertionError("非法 structured_output 应被拒绝")


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
