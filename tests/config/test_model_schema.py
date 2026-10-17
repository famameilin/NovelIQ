import pytest

from src.config.runtime_env import ModelEnvironment
from src.config.schemas import (
    _parse_embedding_model_settings,
    _parse_models_settings,
    _parse_task_model_settings,
)
from src.config.schemas.model import _parse_model_pool, apply_model_environment


def test_diagnosis_budget_defaults_to_ten_and_inherits_configured_value() -> None:
    from src.config.schemas.model import ModelsSettings

    assert ModelsSettings().diagnosis.max_iterations == 10
    assert _parse_models_settings({}).diagnosis.max_iterations == 10
    assert _parse_models_settings({"diagnosis": {}}).diagnosis.max_iterations == 10
    for value in (3, 8, 20):
        assert _parse_models_settings({"diagnosis": {"max_iterations": value}}).diagnosis.max_iterations == value


def test_parse_embedding_model_settings_includes_runtime_parameters() -> None:
    """
    2026-08-03 用于验证 Embedding 行为参数继续来自 settings JSON
    """

    settings = _parse_embedding_model_settings(
        {
            "timeout_s": 120,
            "batch_size": 8,
            "semantic_enabled": False,
            "top_k": 9,
        }
    )

    assert settings.base_url is None
    assert settings.model is None
    assert settings.timeout_s == 120
    assert settings.batch_size == 8
    assert settings.semantic_enabled is False
    assert settings.top_k == 9


def test_parse_task_model_settings_reads_agent_and_behavior_fields() -> None:
    """
    2026-08-08 用于验证任务级配置合并 thinking/Agent 参数

    2026-10-02 设置迁移：temperature/top_p/max_tokens 移入模型池配置，
    任务级解析不再读取这些键（settings.json 中的残留值被静默忽略）。
    2026-10-02 删除流式输出设置：streaming 键不再解析，流式固定开启。
    """
    settings = _parse_task_model_settings(
        {
            "timeout_s": 180,
            "temperature": 0.5,
            "top_p": 0.7,
            "max_tokens": 2048,
            "thinking": True,
            "streaming": True,
            "max_iterations": 20,
            "total_attempts": 3,
            "allow_future_context": True,
        }
    )

    assert settings.timeout_s == 180
    assert settings.thinking is True
    assert settings.max_iterations == 20
    assert settings.total_attempts == 3
    assert settings.allow_future_context is True
    assert not hasattr(settings, "temperature")
    assert not hasattr(settings, "top_p")
    assert not hasattr(settings, "max_tokens")
    assert not hasattr(settings, "streaming")


@pytest.mark.parametrize("field", ["max_iterations", "total_attempts"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_parse_task_model_settings_rejects_invalid_agent_limits(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        _parse_task_model_settings({field: value})


def _pool_entry(model_id: str = "a", **overrides: object) -> dict[str, object]:
    return {"model_id": model_id, "base_url": f"https://{model_id}.example/v1", "api_key": f"key-{model_id}",
            "weight": 1, "max_in_flight": 2, **overrides}


def test_parse_model_pool_reads_sampling_parameters_per_model() -> None:
    """
    2026-10-02 设置迁移：采样参数随模型池条目解析，缺省回退模型级默认
    """

    pool = _parse_model_pool([
        _pool_entry("a", temperature=0.3, top_p=0.9, max_tokens=2048),
        _pool_entry("b"),
    ])

    assert (pool[0].temperature, pool[0].top_p, pool[0].max_tokens) == (0.3, 0.9, 2048)
    assert (pool[1].temperature, pool[1].top_p, pool[1].max_tokens) == (0.7, 0.8, 131072)


@pytest.mark.parametrize("overrides", [
    {"temperature": 2.5}, {"temperature": -0.1}, {"temperature": "0.5"}, {"temperature": True},
    {"top_p": 1.5}, {"top_p": -0.5}, {"max_tokens": 0}, {"max_tokens": True}, {"max_tokens": 1.5},
    {"unknown_key": 1},
])
def test_parse_model_pool_rejects_invalid_sampling_parameters(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _parse_model_pool([_pool_entry(**overrides)])


def test_old_model_environment_variables_do_not_override_json(monkeypatch) -> None:
    """
    2026-08-03 用于确认旧模型变量不再覆盖行为配置
    """

    monkeypatch.setenv("SEMANTIC_CHUNKING_EMBEDDING_DIM", "3072")
    monkeypatch.setenv("SEMANTIC_CHUNKING_BATCH_SIZE", "16")

    settings = _parse_embedding_model_settings(
        {
            "batch_size": 8,
        }
    )

    assert settings.batch_size == 8


def test_apply_model_environment_loads_pool_and_embedding(monkeypatch) -> None:
    """
    文本连接来自统一模型池，任务参数不携带凭据
    """

    monkeypatch.delenv("DIAGNOSIS_MODEL_ID", raising=False)
    settings = _parse_models_settings(
        {
            "annotation": {"timeout_s": 180},
            "paragraph_embedding": {"timeout_s": 120},
            "diagnosis": {"timeout_s": 180},
        }
    )

    apply_model_environment(
        settings,
        [{"model_id": "text-model", "base_url": "https://api.example.com/v1", "api_key": "text-key",
          "weight": 1, "max_in_flight": 4, "temperature": 0.3, "top_p": 0.9, "max_tokens": 2048}],
        ModelEnvironment(
            base_url="http://localhost:8080/v1",
            model="embedding-model",
            api_key="sk-no-key-required",
        ),
    )

    assert settings.model_pool[0].model_id == "text-model"
    assert settings.model_pool[0].max_in_flight == 4
    assert settings.model_pool[0].temperature == 0.3
    assert settings.model_pool[0].max_tokens == 2048
    assert not hasattr(settings.annotation, "api_key")
    assert not hasattr(settings.diagnosis, "model")
    assert settings.paragraph_embedding.model == "embedding-model"
    assert settings.annotation.timeout_s == 180
    assert settings.paragraph_embedding.timeout_s == 120


def test_apply_model_environment_rewrites_loopback_for_docker(monkeypatch) -> None:
    """
    2026-08-03 用于验证 Docker 内模型地址继续转换到宿主机
    """

    monkeypatch.setattr("src.config.schemas.model._is_running_in_docker_container", lambda: True)
    monkeypatch.delenv("DIAGNOSIS_MODEL_ID", raising=False)
    settings = _parse_models_settings({})

    apply_model_environment(
        settings,
        [{"model_id": "text-model", "base_url": "http://localhost:8111/v1", "api_key": "text-key",
          "weight": 1, "max_in_flight": 4}],
        ModelEnvironment(
            base_url="http://127.0.0.1:8080/v1",
            model="embedding-model",
            api_key="embedding-key",
        ),
    )

    assert settings.model_pool[0].base_url == "http://host.docker.internal:8111/v1"
    assert settings.paragraph_embedding.base_url == "http://host.docker.internal:8080/v1"


def test_apply_model_environment_keeps_behavior_when_pool_missing(monkeypatch) -> None:
    """
    模型池缺失时不生成共享连接，非凭据参数仍然生效
    """

    settings = _parse_models_settings({"annotation": {"timeout_s": 180}})
    monkeypatch.delenv("DIAGNOSIS_MODEL_ID", raising=False)
    settings.paragraph_embedding.base_url = "http://json-embedding.example.com/v1"
    settings.paragraph_embedding.model = "json-embedding-model"

    apply_model_environment(settings, [], None)

    assert settings.model_pool == []
    assert settings.annotation.timeout_s == 180
    assert settings.paragraph_embedding.base_url == "http://json-embedding.example.com/v1"
    assert settings.paragraph_embedding.model == "json-embedding-model"


def test_apply_model_environment_embedding_only_still_applies(monkeypatch) -> None:
    """
    2026-08-14 用于验证 MODEL_* 缺失时 EMBEDDING_MODEL_* 仍独立生效
    （此前 model_environment is None 提前 return 会连带跳过 embedding 组）
    """

    settings = _parse_models_settings({})
    monkeypatch.delenv("DIAGNOSIS_MODEL_ID", raising=False)
    settings.paragraph_embedding.base_url = "http://json-embedding.example.com/v1"
    settings.paragraph_embedding.model = "json-embedding-model"

    apply_model_environment(
        settings,
        [],
        ModelEnvironment(
            base_url="http://localhost:8080/v1",
            model="embedding-model",
            api_key="embedding-key",
        ),
    )

    assert settings.model_pool == []
    # 嵌入组已应用环境值
    assert settings.paragraph_embedding.model == "embedding-model"
    assert settings.paragraph_embedding.api_key == "embedding-key"
