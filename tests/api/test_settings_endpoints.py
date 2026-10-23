"""统一模型池、设置保存与环境凭据的接口契约"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.config.env_file import read_env_file
from src.config.settings import Settings, apply_settings_onto

_ENV_KEYS = (
    "MODEL_POOL",
    "DIAGNOSIS_MODEL_ID",
    "EMBEDDING_MODEL_BASE_URL",
    "EMBEDDING_MODEL_ID",
    "EMBEDDING_MODEL_KEY",
    "LTP_MODEL_DIR",
)


@pytest.fixture
def isolated_settings(tmp_path: Path, monkeypatch) -> Path:
    """配置文件、单例和环境变量均隔离，测试不使用真实连接"""
    import src.api.routes.settings as routes
    import src.config.settings_service as settings_service

    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(settings_service, "settings_file_path", lambda: settings_file)
    monkeypatch.setattr(settings_service, "env_file_path", lambda: tmp_path / ".env")
    saved = deepcopy(routes.settings)
    # 设置接口会经 apply_env_updates_to_process 直写 os.environ（绕过 monkeypatch
    # 追踪），必须整表快照还原，否则泄漏进后续测试的 Settings.from_env()
    saved_environ = dict(os.environ)
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    apply_settings_onto(routes.settings, Settings())
    try:
        yield settings_file
    finally:
        os.environ.clear()
        os.environ.update(saved_environ)
        apply_settings_onto(routes.settings, saved)


def _entry(model_id: str = "model-a", **overrides: Any) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "base_url": f"https://{model_id}.example/v1",
        "api_key": f"sk-{model_id}-1234",
        "weight": 1,
        "max_in_flight": 2,
        "context_window_tokens": 128000,
        "temperature": 0.5,
        "top_p": 0.9,
        "max_tokens": 4096,
        **overrides,
    }


def _save_pool(client: TestClient) -> None:
    client.put(
        "/api/settings/env",
        json={
            "model_pool": [_entry(), _entry("diagnostic", weight=0, max_in_flight=1)],
            "diagnosis_model_id": "diagnostic",
        },
    ).raise_for_status()


def test_diagnosis_budget_setting_is_editable_and_used_by_scheduler(isolated_settings, api_client):
    from unittest.mock import MagicMock

    from src.agents.diagnosis.work_runtime import DiagnosisWorkScheduler
    from src.config import settings
    from src.event_bus import EventBus

    schema = api_client.get("/api/settings/schema").json()["fields"]
    field = next(item for item in schema if item["path"] == ["models", "diagnosis", "max_iterations"])
    assert field["editable"] is True and field["min_value"] == 1
    for limit in (3, 20):
        response = api_client.put(
            "/api/settings", json={"values": {"models": {"diagnosis": {"max_iterations": limit}}}}
        )
        response.raise_for_status()
        assert settings.models.diagnosis.max_iterations == limit
        scheduler = DiagnosisWorkScheduler(
            run_id="test",
            domain=MagicMock(),
            bus=EventBus(),
            model_id="model",
            llm_factory=MagicMock(),
            observer_factory=MagicMock(),
            audit_barrier=MagicMock(),
        )
        assert scheduler.report_max_rounds == limit
        scheduler.pool.close()


def test_pool_requires_context_window_and_roundtrips(isolated_settings, api_client):
    """上下文容量随模型池保存并回显；普通设置 schema 不暴露模型池字段"""
    schema_paths = [item["path"] for item in api_client.get("/api/settings/schema").json()["fields"]]
    assert ["models", "model_pool", "context_window_tokens"] not in schema_paths
    response = api_client.put("/api/settings/env", json={"model_pool": [_entry(context_window_tokens=32768)]})
    assert response.status_code == 200
    assert response.json()["values"]["models"]["model_pool"][0]["context_window_tokens"] == 32768
    missing = _entry()
    missing.pop("context_window_tokens")
    response = api_client.put("/api/settings/env", json={"model_pool": [missing]})
    assert response.status_code == 422
    response = api_client.put("/api/settings/env", json={"model_pool": [_entry(context_window_tokens=0)]})
    assert response.status_code == 422
    assert api_client.get("/api/settings").json()["values"]["models"]["model_pool"][0]["context_window_tokens"] == 32768


def test_pool_roundtrip_masks_keys_and_preserves_behavior_config(
    isolated_settings: Path,
    api_client: TestClient,
) -> None:
    from src.model_pool.configuration import load_task_config

    env_file = isolated_settings.parent / ".env"
    env_file.write_text("# 数据库\nDATABASE_PASSWORD=unrelated\n", encoding="utf-8")
    _save_pool(api_client)
    data = api_client.get("/api/settings").json()
    pool = data["values"]["models"]["model_pool"]
    assert pool[0] == {**_entry(), "api_key": "••••1234", "weight": 1.0}
    assert "sk-model-a-1234" not in json.dumps(data)
    assert "sk-diagnostic-1234" not in json.dumps(data)
    assert "text_model" not in data and "model_providers" not in data
    assert "api_key" not in data["values"]["models"]["annotation"]
    assert "model_pool" not in data["values"]["models"]["annotation"]
    assert data["defaults"]["models"]["model_pool"] == []
    assert not isolated_settings.exists()
    assert "DATABASE_PASSWORD=unrelated" in env_file.read_text(encoding="utf-8")
    assert json.loads(read_env_file(env_file)["MODEL_POOL"])[1]["max_in_flight"] == 1
    assert json.loads(read_env_file(env_file)["MODEL_POOL"])[1]["context_window_tokens"] == 128000
    assert read_env_file(env_file)["DIAGNOSIS_MODEL_ID"] == "diagnostic"
    annotation = load_task_config("annotation", selection_key="task")
    diagnosis = load_task_config("diagnosis")
    assert (annotation.model, annotation.api_key, annotation.max_in_flight) == ("model-a", "sk-model-a-1234", 2)
    # 采样参数来自池内模型配置
    assert (annotation.temperature, annotation.top_p, annotation.max_tokens) == (0.5, 0.9, 4096)
    assert annotation.context_window_tokens == 128000
    assert (diagnosis.model, diagnosis.base_url, diagnosis.max_in_flight) == (
        "diagnostic",
        "https://diagnostic.example/v1",
        1,
    )
    # 采样参数随模型保存（环境接口），不再经参数设置接口按任务配置
    api_client.put(
        "/api/settings/env",
        json={
            "model_pool": [_entry(), _entry("diagnostic", weight=0, max_in_flight=1, max_tokens=2048)],
            "diagnosis_model_id": "diagnostic",
        },
    ).raise_for_status()
    assert load_task_config("diagnosis").model == "diagnostic"
    assert load_task_config("diagnosis").max_tokens == 2048
    # 采样参数改走环境接口后本用例不再触发参数保存，settings.json 应保持不生成
    assert not isolated_settings.exists()


def test_pool_reload_uses_only_the_new_environment_contract(isolated_settings: Path, api_client: TestClient) -> None:
    _save_pool(api_client)
    reloaded = Settings.from_config_dict({})
    assert reloaded.models.model_pool[0].api_key == "sk-model-a-1234"
    assert reloaded.models.diagnosis_model_id == "diagnostic"


def test_edit_model_keeps_key_and_updates_diagnosis_on_rename(isolated_settings: Path, api_client: TestClient) -> None:
    _save_pool(api_client)
    first = _entry(max_in_flight=5)
    first.pop("api_key")
    renamed = _entry("renamed", weight=0)
    renamed.pop("api_key")
    renamed["original_model_id"] = "diagnostic"
    response = api_client.put(
        "/api/settings/env",
        json={
            "model_pool": [first, renamed],
            "diagnosis_model_id": "renamed",
        },
    )
    assert response.status_code == 200
    from src.model_pool.configuration import load_task_config

    assert load_task_config("diagnosis").api_key == "sk-diagnostic-1234"
    assert load_task_config("annotation", model_id="model-a").max_in_flight == 5


def test_delete_selected_model_requires_new_selection(isolated_settings: Path, api_client: TestClient) -> None:
    _save_pool(api_client)
    env_file = isolated_settings.parent / ".env"
    before = env_file.read_text(encoding="utf-8")
    response = api_client.put("/api/settings/env", json={"model_pool": [_entry()]})
    assert response.status_code == 422 and env_file.read_text(encoding="utf-8") == before
    response = api_client.put("/api/settings/env", json={"model_pool": [_entry()], "diagnosis_model_id": "model-a"})
    assert response.status_code == 200
    assert len(response.json()["values"]["models"]["model_pool"]) == 1


@pytest.mark.parametrize(
    "pool",
    [
        [],
        [_entry(weight=0)],
        [_entry(weight=-1)],
        [_entry(weight=True)],
        [_entry(), _entry()],
        [_entry(max_in_flight=0)],
        [_entry(max_in_flight=1.5)],
        [_entry(temperature=3)],
        [_entry(temperature=-0.1)],
        [_entry(top_p=1.5)],
        [_entry(max_tokens=0)],
        [_entry(api_key="")],
        [_entry(api_key="••••1234")],
        [_entry(api_key="key\nDATABASE_PASSWORD=evil")],
        [_entry(base_url="file:///tmp")],
    ],
)
def test_invalid_pool_does_not_write_config(
    isolated_settings: Path,
    api_client: TestClient,
    pool: list[dict[str, Any]],
) -> None:
    response = api_client.put("/api/settings/env", json={"model_pool": pool})
    assert response.status_code == 422
    assert not (isolated_settings.parent / ".env").exists()
    assert "MODEL_POOL" not in os.environ


def test_unknown_diagnosis_and_missing_new_key_are_rejected(isolated_settings: Path, api_client: TestClient) -> None:
    new = _entry()
    new.pop("api_key")
    assert api_client.put("/api/settings/env", json={"model_pool": [new]}).status_code == 422
    assert (
        api_client.put(
            "/api/settings/env",
            json={
                "model_pool": [_entry()],
                "diagnosis_model_id": "not-in-pool",
            },
        ).status_code
        == 422
    )
    assert not (isolated_settings.parent / ".env").exists()


def test_short_key_is_fully_masked(isolated_settings: Path, api_client: TestClient) -> None:
    response = api_client.put("/api/settings/env", json={"model_pool": [_entry(api_key="abc")]})
    assert response.status_code == 200
    assert response.json()["values"]["models"]["model_pool"][0]["api_key"] == "••••"


def test_pool_and_embedding_validation_is_atomic(isolated_settings: Path, api_client: TestClient) -> None:
    response = api_client.put(
        "/api/settings/env",
        json={
            "model_pool": [_entry()],
            "embedding_model": {"base_url": "https://embedding/v1"},
        },
    )
    assert response.status_code == 422
    assert not (isolated_settings.parent / ".env").exists() and "MODEL_POOL" not in os.environ


def test_legacy_connection_and_named_provider_contracts_are_absent(
    isolated_settings: Path,
    api_client: TestClient,
) -> None:
    for payload in (
        {"model": {"base_url": "https://old/v1", "model": "old", "api_key": "old"}},
        {"providers": {"secondary": {"api_key": "x"}}},
    ):
        assert api_client.put("/api/settings/env", json=payload).status_code == 422
    assert not (isolated_settings.parent / ".env").exists()
    assert api_client.post("/api/settings/agents/annotation/test").status_code == 404
    assert api_client.post("/api/settings/agents/diagnosis/test").status_code == 404


def test_pool_credentials_are_rejected_by_parameter_save(isolated_settings: Path, api_client: TestClient) -> None:
    response = api_client.put("/api/settings", json={"values": {"models": {"model_pool": [_entry()]}}})
    assert response.status_code == 422 and not isolated_settings.exists()


def test_update_settings_partial_save_and_hot_apply(isolated_settings: Path, api_client: TestClient) -> None:
    isolated_settings.write_text(
        json.dumps({"models": {"annotation": {"max_iterations": 15}}, "topic_model": {"num_topics": 25}}),
        encoding="utf-8",
    )
    response = api_client.put("/api/settings", json={"values": {"models": {"annotation": {"timeout_s": 60}}}})
    assert response.status_code == 200
    saved = json.loads(isolated_settings.read_text(encoding="utf-8"))
    assert saved["models"]["annotation"] == {"timeout_s": 60}
    assert "topic_model" not in saved
    from src.config import settings

    assert settings.models.annotation.timeout_s == 60
    assert settings.models.annotation.max_iterations == 15


def test_update_settings_invalid_and_corrupt_files_are_rejected(
    isolated_settings: Path,
    api_client: TestClient,
) -> None:
    response = api_client.put("/api/settings", json={"values": {"topic_model": {"topic_shift": {"window_size": 0}}}})
    assert response.status_code == 422 and not isolated_settings.exists()
    isolated_settings.write_text("{not-json", encoding="utf-8")
    assert api_client.put("/api/settings", json={"values": {"metrics": {"mtld_threshold": 0.8}}}).status_code == 422


def test_reset_default_removes_override_and_preserves_singleton_identity(
    isolated_settings: Path,
    api_client: TestClient,
) -> None:
    from src.config import settings

    singleton = settings
    isolated_settings.write_text('{"models":{"annotation":{"timeout_s":90}}}', encoding="utf-8")
    response = api_client.put("/api/settings", json={"values": {"models": {"annotation": {"timeout_s": None}}}})
    assert response.status_code == 200 and settings is singleton
    assert "models" not in json.loads(isolated_settings.read_text(encoding="utf-8"))


def test_parallel_parameter_updates_preserve_independent_fields(isolated_settings: Path) -> None:
    import src.api.routes.settings as routes
    from src.api.models.settings import UpdateSettingsRequest

    updates = [
        {"models": {"diagnosis": {"thinking": True}}},
        {"models": {"annotation": {"timeout_s": 60}}},
        {"metrics": {"mtld_threshold": 0.81}},
    ]
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda values: routes.update_settings(UpdateSettingsRequest(values=values)), updates))
    view = routes.get_settings().values
    assert view["models"]["diagnosis"]["thinking"] is True
    assert view["models"]["annotation"]["timeout_s"] == 60
    assert view["metrics"]["mtld_threshold"] == 0.81


def test_embedding_credentials_can_be_saved_preserved_and_cleared(
    isolated_settings: Path,
    api_client: TestClient,
) -> None:
    patch = {"base_url": "http://localhost:8080/v1", "model": "embedding", "api_key": "sk-embedding-9999"}
    response = api_client.put("/api/settings/env", json={"embedding_model": patch})
    assert response.status_code == 200
    assert response.json()["values"]["models"]["paragraph_embedding"]["api_key"] == "••••9999"
    api_client.put(
        "/api/settings/env", json={"embedding_model": {"base_url": "http://localhost:9090/v1"}}
    ).raise_for_status()
    assert os.environ["EMBEDDING_MODEL_KEY"] == "sk-embedding-9999"
    invalid = api_client.put("/api/settings/env", json={"embedding_model": {"api_key": "", "model": "new"}})
    assert invalid.status_code == 422
    response = api_client.put("/api/settings/env", json={"embedding_model": {"api_key": ""}})
    assert response.status_code == 200 and "EMBEDDING_MODEL_KEY" not in os.environ
    assert response.json()["values"]["models"]["paragraph_embedding"]["base_url"] is None


def test_ltp_directory_requires_existing_path(isolated_settings: Path, api_client: TestClient, tmp_path: Path) -> None:
    ltp = tmp_path / "ltp"
    ltp.mkdir()
    response = api_client.put("/api/settings/env", json={"ltp_model_dir": str(ltp)})
    assert response.status_code == 200 and os.environ["LTP_MODEL_DIR"] == str(ltp)
    assert api_client.put("/api/settings/env", json={"ltp_model_dir": str(tmp_path / "missing")}).status_code == 422


class _FakeOpenAIClient:
    last_init: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        self.last_init.update(kwargs)

    @property
    def models(self) -> _FakeOpenAIClient:
        return self

    def list(self) -> list[Any]:
        from types import SimpleNamespace

        return [SimpleNamespace(id="model-a"), SimpleNamespace(id="model-b")]


def test_pool_connection_uses_saved_key_and_unsaved_override(
    isolated_settings: Path,
    api_client: TestClient,
    monkeypatch,
) -> None:
    import src.api.routes.settings as routes

    monkeypatch.setattr(routes, "OpenAI", _FakeOpenAIClient)
    _save_pool(api_client)
    response = api_client.post("/api/settings/agents/pool/test", json={"model_id": "diagnostic"})
    assert response.status_code == 200 and response.json()["ok"] is True
    assert _FakeOpenAIClient.last_init["api_key"] == "sk-diagnostic-1234"
    assert _FakeOpenAIClient.last_init["base_url"] == "https://diagnostic.example/v1"
    assert _FakeOpenAIClient.last_init["max_retries"] == 0
    before = os.environ["MODEL_POOL"]
    response = api_client.post(
        "/api/settings/agents/pool/test",
        json={
            "model_id": "model-a",
            "base_url": "https://draft/v1",
            "api_key": "sk-draft",
        },
    )
    assert response.json()["ok"] is True and os.environ["MODEL_POOL"] == before
    assert _FakeOpenAIClient.last_init["api_key"] == "sk-draft"


def test_connection_failure_redacts_draft_key(isolated_settings: Path, api_client: TestClient, monkeypatch) -> None:
    import src.api.routes.settings as routes

    class FailingClient(_FakeOpenAIClient):
        def list(self) -> list[Any]:
            raise ConnectionError("failed Authorization: Bearer sk-draft-secret")

    monkeypatch.setattr(routes, "OpenAI", FailingClient)
    response = api_client.post(
        "/api/settings/agents/pool/test",
        json={
            "base_url": "https://draft/v1",
            "api_key": "sk-draft-secret",
        },
    )
    assert response.json()["ok"] is False and "sk-draft-secret" not in response.text
    assert not (isolated_settings.parent / ".env").exists()


def test_connection_without_configuration_does_not_call_remote(isolated_settings: Path, api_client: TestClient) -> None:
    assert api_client.post("/api/settings/agents/pool/test").json()["ok"] is False
    assert api_client.post("/api/settings/agents/unknown/test").status_code == 404


def test_schema_has_no_extra_model_categories(isolated_settings: Path, api_client: TestClient) -> None:
    paths = {tuple(entry["path"]) for entry in api_client.get("/api/settings/schema").json()["fields"]}
    assert not any(
        "continuity" in path
        or "provider_route" in path
        or "model_id" in path
        or "provider_max_in_flight" in path
        or "structured_output" in path
        for path in paths
    )
    assert "continuity" not in api_client.get("/api/settings").json()["values"]["models"]


def test_validation_errors_do_not_echo_pool_keys(isolated_settings: Path, api_client: TestClient) -> None:
    response = api_client.put(
        "/api/settings/env",
        json={
            "model_pool": [_entry(api_key="secret-pool-key", extra="bad")],
        },
    )
    assert response.status_code == 422 and "secret-pool-key" not in response.text
