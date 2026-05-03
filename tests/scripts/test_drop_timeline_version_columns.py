from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest


def _load_drop_timeline_version_columns_module() -> ModuleType:
    """
    创建时间: 2026-04-28
    任务: harden-drop-timeline-version-columns-script
    说明: `scripts/` 目录不是 package；这里按文件路径加载脚本模块，
          便于单测脚本默认参数和环境边界，而不改项目导入结构。
    """

    script_path = Path(__file__).resolve().parents[2] / "scripts" / "db" / "drop_timeline_version_columns.py"
    spec = importlib.util.spec_from_file_location("test_drop_timeline_version_columns_script", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载脚本模块: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_skips_missing_default_test_database_url() -> None:
    module = _load_drop_timeline_version_columns_module()

    with (
        patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pw@localhost:5432/app"}, clear=True),
        patch.object(module, "drop_version_columns") as mock_drop_version_columns,
        patch("sys.argv", ["drop_timeline_version_columns.py"]),
    ):
        exit_code = module.main()

    assert exit_code == 0
    mock_drop_version_columns.assert_called_once_with(
        "postgresql://user:pw@localhost:5432/app",
        None,
        label="DATABASE_URL",
    )


def test_main_raises_for_explicit_missing_env_var() -> None:
    module = _load_drop_timeline_version_columns_module()

    with (
        patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pw@localhost:5432/app"}, clear=True),
        patch("sys.argv", ["drop_timeline_version_columns.py", "--env-var", "TEST_DATABASE_URL"]),
    ):
        with pytest.raises(RuntimeError, match="TEST_DATABASE_URL environment variable is not set"):
            module.main()
