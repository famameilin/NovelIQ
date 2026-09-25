"""2026-09-10 设置端点测试（/api/settings）

覆盖：
- GET /schema、GET /（生效值打码 + 默认值 + 来源）
- PUT /：部分保存（文件稀疏化 + 单例热生效）、校验失败 422、恢复默认剔除
- PUT /env：凭据写入 .env + os.environ 同步 + 单例终态（含整组清空显式置 None）
- POST /model-providers/{task}/test：连通性（mock OpenAI 客户端）

单例与环境变量的现场在 fixture 中备份恢复，测试间零泄漏。
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.config.settings import apply_settings_onto

_ENV_KEYS = (
    "MODEL_BASE_URL",
    "MODEL_ID",
    "MODEL_KEY",
    "EMBEDDING_MODEL_BASE_URL",
    "EMBEDDING_MODEL_ID",
    "EMBEDDING_MODEL_KEY",
    "LTP_MODEL_DIR",
)


@pytest.fixture
def isolated_settings(tmp_path: Path, monkeypatch) -> Path:
    """settings.json 与 .env 重定向到临时目录，单例与 os.environ 现场备份恢复"""
    import src.api.routes.settings as settings_routes

    settings_file = tmp_path / "settings.json"
    env_file = tmp_path / ".env"
    monkeypatch.setattr(settings_routes, "_settings_file_path", lambda: settings_file)
    monkeypatch.setattr(settings_routes, "_env_file_path", lambda: env_file)

    saved_settings = deepcopy(settings_routes.settings)
    saved_env = {key: os.environ.get(key) for key in _ENV_KEYS}
    try:
        yield settings_file
    finally:
        apply_settings_onto(settings_routes.settings, saved_settings)
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_get_settings_view_masks_api_key(isolated_settings: Path, api_client: TestClient) -> None:
    # 单例在 import 期已加载真实 .env，先走被测链路写入测试凭据
    setup = api_client.put(
        "/api/settings/env",
        json={
            "model": {
                "base_url": "https://api.example.com/v1",
                "model": "text-model",
                "api_key": "sk-test-abcdef123456",
            }
        },
    )
    assert setup.status_code == 200

    response = api_client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()

    annotation = data["values"]["models"]["annotation"]
    assert annotation["base_url"] == "https://api.example.com/v1"
    assert annotation["api_key"] == "••••3456"
    assert annotation["model"] == "text-model"
    # defaults 来自 dataclass，不含 env 注入值
    assert data["defaults"]["models"]["annotation"]["api_key"] is None
    # 来源：注册表字段中文件里存在的标 file
    assert data["sources"]["models/annotation/temperature"] == "default"


def test_update_settings_partial_save_and_hot_apply(
    isolated_settings: Path, api_client: TestClient
) -> None:
    isolated_settings.write_text(
        json.dumps({"models": {"annotation": {"max_iterations": 15}}, "topic_model": {"num_topics": 25}}),
        encoding="utf-8",
    )

    response = api_client.put("/api/settings", json={"values": {"models": {"annotation": {"temperature": 0.9}}}})
    assert response.status_code == 200

    saved = json.loads(isolated_settings.read_text(encoding="utf-8"))
    # 未提及的键保留；等于默认的 num_topics 25 被稀疏化剔除
    assert saved["models"]["annotation"] == {"max_iterations": 15, "temperature": 0.9}
    assert "topic_model" not in saved

    # 单例热生效
    from src.config.settings import settings as singleton

    assert singleton.models.annotation.temperature == 0.9
    assert singleton.models.annotation.max_iterations == 15


def test_update_settings_rejects_invalid(isolated_settings: Path, api_client: TestClient) -> None:
    response = api_client.put(
        "/api/settings",
        json={"values": {"topic_model": {"topic_shift": {"window_size": 0}}}},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error_type"] == "SettingsValidationError"
    # 失败不落盘
    assert not isolated_settings.exists()


def test_update_settings_reset_to_default_removes_override(
    isolated_settings: Path, api_client: TestClient
) -> None:
    isolated_settings.write_text(
        json.dumps({"models": {"annotation": {"temperature": 0.9}}}), encoding="utf-8"
    )

    response = api_client.put(
        "/api/settings",
        json={"values": {"models": {"annotation": {"temperature": 0.7}}}},
    )
    assert response.status_code == 200
    saved = json.loads(isolated_settings.read_text(encoding="utf-8"))
    assert "models" not in saved


def test_update_settings_rejects_corrupt_file(isolated_settings: Path, api_client: TestClient) -> None:
    isolated_settings.write_text("{not-json", encoding="utf-8")
    response = api_client.put("/api/settings", json={"values": {"models": {"annotation": {"temperature": 0.9}}}})
    assert response.status_code == 422


def test_update_env_sets_model_credentials(
    isolated_settings: Path, api_client: TestClient, monkeypatch
) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    response = api_client.put(
        "/api/settings/env",
        json={"model": {"base_url": "https://api.example.com/v1", "model": "gpt-x", "api_key": "sk-live-key-9999"}},
    )
    assert response.status_code == 200
    data = response.json()

    env_content = (isolated_settings.parent / ".env").read_text(encoding="utf-8")
    assert "MODEL_BASE_URL=https://api.example.com/v1" in env_content
    assert "MODEL_ID=gpt-x" in env_content
    assert "MODEL_KEY=sk-live-key-9999" in env_content

    # os.environ 同步 + 单例热生效（annotation/diagnosis 共用文本模型组）
    assert os.environ["MODEL_KEY"] == "sk-live-key-9999"
    from src.config.settings import settings as singleton

    assert singleton.models.annotation.api_key == "sk-live-key-9999"
    assert singleton.models.diagnosis.model == "gpt-x"
    # 回显打码
    assert data["values"]["models"]["annotation"]["api_key"] == "••••9999"


def test_update_env_clear_group_requires_no_other_fields(
    isolated_settings: Path, api_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("MODEL_BASE_URL", "https://old/v1")
    monkeypatch.setenv("MODEL_ID", "old-model")
    monkeypatch.setenv("MODEL_KEY", "old-key")

    # 清空时同时设置其他字段 → 422
    response = api_client.put(
        "/api/settings/env",
        json={"model": {"base_url": "https://new/v1", "api_key": ""}},
    )
    assert response.status_code == 422

    # 整组清空：文件删键 + os.environ 删键 + 单例显式置 None（不走降级保留旧值）
    response = api_client.put("/api/settings/env", json={"model": {"api_key": ""}})
    assert response.status_code == 200

    env_content = (isolated_settings.parent / ".env").read_text(encoding="utf-8")
    assert "MODEL_KEY" not in env_content
    assert "MODEL_ID" not in env_content
    assert os.environ.get("MODEL_KEY") is None

    from src.config.settings import settings as singleton

    assert singleton.models.annotation.api_key is None
    assert singleton.models.annotation.base_url is None
    assert singleton.models.diagnosis.model is None


def test_update_env_rejects_incomplete_group(
    isolated_settings: Path, api_client: TestClient, monkeypatch
) -> None:
    # 未配置组只能整组设置（真实环境可能已配置部分键，先清干净再验证完整性校验）
    for key in ("EMBEDDING_MODEL_BASE_URL", "EMBEDDING_MODEL_ID", "EMBEDDING_MODEL_KEY"):
        monkeypatch.delenv(key, raising=False)

    response = api_client.put(
        "/api/settings/env",
        json={"embedding_model": {"base_url": "http://localhost:8080/v1"}},
    )
    assert response.status_code == 422
    assert "EMBEDDING_MODEL" in response.json()["detail"]


def test_update_env_ltp_model_dir(isolated_settings: Path, api_client: TestClient, tmp_path: Path) -> None:
    ltp_dir = tmp_path / "ltp-model"
    ltp_dir.mkdir()

    response = api_client.put("/api/settings/env", json={"ltp_model_dir": str(ltp_dir)})
    assert response.status_code == 200
    assert os.environ["LTP_MODEL_DIR"] == str(ltp_dir)

    from src.config.settings import settings as singleton

    assert singleton.linguistic.ltp.model_dir == str(ltp_dir)

    # 不存在的目录 → 422
    response = api_client.put("/api/settings/env", json={"ltp_model_dir": str(tmp_path / "missing")})
    assert response.status_code == 422


def test_update_env_ignores_non_whitelisted_keys(isolated_settings: Path, api_client: TestClient) -> None:
    response = api_client.put(
        "/api/settings/env",
        json={"model": {"base_url": "https://x/v1", "model": "m", "api_key": "k"}},
    )
    assert response.status_code == 200
    # .env 中只出现白名单键，DATABASE_* 等 UI 不可触碰
    env_content = (isolated_settings.parent / ".env").read_text(encoding="utf-8")
    assert "DATABASE" not in env_content


class _FakeModel:
    def __init__(self, model_id: str) -> None:
        self.id = model_id


class _FakeModelsPage:
    def __init__(self, model_ids: list[str]) -> None:
        self._model_ids = model_ids

    def __iter__(self):
        return iter(_FakeModel(model_id) for model_id in self._model_ids)


class _FakeOpenAIClient:
    last_init: dict[str, Any] = {}

    def __init__(self, base_url: str, api_key: str, timeout: float) -> None:
        _FakeOpenAIClient.last_init = {"base_url": base_url, "api_key": api_key, "timeout": timeout}

    @property
    def models(self):
        return self

    def list(self) -> _FakeModelsPage:
        return _FakeModelsPage(["model-a", "model-b"])


def test_test_model_provider_success(isolated_settings: Path, api_client: TestClient, monkeypatch) -> None:
    import src.api.routes.settings as settings_routes

    monkeypatch.setattr(settings_routes, "OpenAI", _FakeOpenAIClient)
    response = api_client.post(
        "/api/settings/model-providers/annotation/test",
        json={"base_url": "https://api.example.com/v1", "api_key": "sk-test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["model_ids"] == ["model-a", "model-b"]
    assert data["latency_ms"] is not None
    assert _FakeOpenAIClient.last_init["base_url"] == "https://api.example.com/v1"


def test_test_model_provider_failure_returns_ok_false(
    isolated_settings: Path, api_client: TestClient, monkeypatch
) -> None:
    import src.api.routes.settings as settings_routes

    class _FailingClient(_FakeOpenAIClient):
        def list(self) -> _FakeModelsPage:
            raise ConnectionError("connection refused")

    monkeypatch.setattr(settings_routes, "OpenAI", _FailingClient)
    response = api_client.post("/api/settings/model-providers/embedding/test")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "connection refused" in data["error"]


def test_test_model_provider_unknown_task(isolated_settings: Path, api_client: TestClient) -> None:
    response = api_client.post("/api/settings/model-providers/unknown/test")
    assert response.status_code == 404


def test_test_model_provider_without_base_url(isolated_settings: Path, api_client: TestClient) -> None:
    response = api_client.post("/api/settings/model-providers/annotation/test")
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_settings_roundtrip_preserves_singleton_identity(isolated_settings: Path, api_client: TestClient) -> None:
    """PUT 前后单例对象身份不变——28 处 from src.config import settings 的前提"""
    from src.config.settings import settings as singleton_before

    response = api_client.put("/api/settings", json={"values": {"metrics": {"mtld_threshold": 0.8}}})
    assert response.status_code == 200

    from src.config.settings import settings as singleton_after

    assert singleton_before is singleton_after
    assert singleton_after.metrics.mtld_threshold == 0.8
