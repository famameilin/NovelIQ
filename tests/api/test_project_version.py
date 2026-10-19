"""项目发布版本与健康响应、OpenAPI、锁文件保持同一来源"""

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.api import main
from src.config.project_version import project_version


def test_single_project_version_is_independent_of_working_directory(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[2]
    expected = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    monkeypatch.chdir(tmp_path)
    project_version.cache_clear()
    assert project_version() == expected == main.app.version
    assert main.app.openapi()["info"]["version"] == expected
    python_lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    project = next(row for row in python_lock["package"] if row["name"] == "novel-qa")
    assert project["version"] == expected
    frontend = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))
    assert "version" not in frontend and "version" not in lock and "version" not in lock["packages"][""]
    assert lock["packages"][""]["dependencies"] == frontend["dependencies"]
    assert lock["packages"][""]["devDependencies"] == frontend["devDependencies"]


@pytest.mark.parametrize("unhealthy", [False, True])
def test_health_version_reads_project_source(monkeypatch, unhealthy):
    def check():
        if unhealthy:
            raise RuntimeError("test unavailable")

    monkeypatch.setattr(
        main, "get_storage", lambda: SimpleNamespace(reads=SimpleNamespace(api_main_health_check_1=check))
    )
    monkeypatch.setattr(main, "get_pool_status", lambda: None)
    response = TestClient(main.app).get("/health")
    assert response.status_code == (503 if unhealthy else 200)
    assert response.json()["version"] == project_version()
