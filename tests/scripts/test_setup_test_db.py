from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch


def _load_setup_test_db_module() -> ModuleType:
    """
    创建时间: 2026-04-27
    创建者: Codex
    任务: fix-test-db-timeline-contract-bootstrap
    说明: `scripts/` 目录不是 Python package；
          这里用 importlib 按文件路径加载脚本模块，便于只验证脚本行为而不改项目导入结构。
    """

    script_path = Path(__file__).resolve().parents[2] / "scripts" / "db" / "setup_test_db.py"
    spec = importlib.util.spec_from_file_location("test_setup_test_db_script", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载脚本模块: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_create_test_database_recreates_existing_database() -> None:
    module = _load_setup_test_db_module()
    engine = MagicMock()
    connection = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection

    executed_sql: list[tuple[str, object | None]] = []

    def execute_side_effect(statement, params=None):
        sql_text = str(statement)
        executed_sql.append((sql_text, params))
        result = MagicMock()
        if "FROM pg_database" in sql_text:
            result.fetchone.return_value = (1,)
        else:
            result.fetchone.return_value = None
        return result

    connection.execute.side_effect = execute_side_effect

    with patch.object(module, "create_engine", return_value=engine):
        module.create_test_database()

    assert any("SELECT 1 FROM pg_database" in sql for sql, _ in executed_sql)
    assert any("SELECT pg_terminate_backend(pid)" in sql for sql, _ in executed_sql)
    assert any(sql == f"DROP DATABASE {module.QUOTED_TEST_DB_NAME}" for sql, _ in executed_sql)
    assert any(sql == f"CREATE DATABASE {module.QUOTED_TEST_DB_NAME}" for sql, _ in executed_sql)
    engine.dispose.assert_called_once()


def test_create_tables_bootstraps_test_db_via_init_db() -> None:
    """
    创建时间: 2026-04-27
    创建者: Codex
    任务: tighten-setup-test-db-contract-regression
    说明: 直接验证 setup_test_db.py 的 create_tables() 会切换到测试库，
          并通过 src.storage.db.init_db(include_level3_tables=True) 拉起 fresh schema。
          这条测试保护的是脚本引导链，而不是仅验证单个 SQL 片段。
    """

    module = _load_setup_test_db_module()
    call_order: list[str] = []

    def mark_dispose() -> None:
        call_order.append("dispose")

    def mark_init_db(*, include_level3_tables: bool) -> None:
        call_order.append(f"init:{include_level3_tables}")

    with (
        patch.dict(os.environ, {}, clear=False),
        patch("src.storage.db.dispose_engine", side_effect=mark_dispose) as mock_dispose_engine,
        patch("src.storage.db.init_db", side_effect=mark_init_db) as mock_init_db,
    ):
        module.create_tables()

    assert os.environ["DATABASE_URL"] == module.TEST_DB_URL
    assert call_order == ["dispose", "init:True", "dispose"]
    assert mock_dispose_engine.call_count == 2
    mock_init_db.assert_called_once_with(include_level3_tables=True)
