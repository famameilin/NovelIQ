"""主题模型路径解析测试"""

from pathlib import Path

import pytest

from src.storage.path_resolver import _find_project_root, resolve_model_dir, resolve_project_root


def test_resolve_project_root_is_repository_root() -> None:
    """2026-08-20 验证项目根目录由配置锚点确定"""
    root = resolve_project_root()
    assert (root / "config" / "settings.json").is_file()
    assert root == Path(__file__).resolve().parents[2]


def test_resolve_model_dir_is_absolute_and_run_scoped(monkeypatch, tmp_path: Path) -> None:
    """2026-08-20 验证主题模型目录是绝对路径并按 run 隔离"""
    monkeypatch.chdir(tmp_path)
    model_dir = resolve_model_dir("run-1")
    assert model_dir.is_absolute()
    assert model_dir == resolve_project_root() / "models" / "topic" / "run-1"


def test_resolve_model_dir_rejects_path_like_run_id() -> None:
    """2026-08-20 验证路径型 run_id 被拒绝"""
    with pytest.raises(ValueError, match="非法 run_id"):
        resolve_model_dir("nested/run")

    with pytest.raises(ValueError, match="非法 run_id"):
        resolve_model_dir("..")


def test_find_project_root_fails_without_settings_anchor(tmp_path: Path) -> None:
    """2026-08-20 验证缺少配置锚点时明确失败"""
    with pytest.raises(RuntimeError, match="config/settings.json"):
        _find_project_root(tmp_path)
