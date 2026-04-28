"""
FastAPI 启动边界测试。

创建时间: 2026-04-28
创建者: Codex
任务: fix-startup-schema-guard-boundary
说明: 覆盖 lifespan 对数据库 schema guard 与僵尸任务恢复异常的边界处理，
      避免 fail-closed 的启动错误再被误降级成 warning。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import src.api.main as main_module


@pytest.mark.asyncio
async def test_lifespan_propagates_init_db_schema_guard_failure() -> None:
    """
    schema guard 失败时应直接阻断启动，而不是继续进入僵尸任务恢复。

    创建时间: 2026-04-28
    创建者: Codex
    任务: fix-startup-schema-guard-boundary
    说明: 旧 cloud_analysis protagonist 列属于结构性 schema 错误；
          这里要求 lifespan 原样抛出异常，保持 fail-closed 语义。
    """

    with (
        patch("src.storage.db.init_db", side_effect=RuntimeError("schema mismatch")) as mock_init_db,
        patch.object(main_module, "_recover_orphaned_tasks") as mock_recover_orphaned_tasks,
    ):
        with pytest.raises(RuntimeError, match="schema mismatch"):
            async with main_module.lifespan(main_module.app):
                pass

    mock_init_db.assert_called_once_with()
    mock_recover_orphaned_tasks.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_keeps_zombie_cleanup_failure_as_warning() -> None:
    """
    孤儿任务恢复失败时应记 warning，但不应掩盖已成功完成的 init_db。

    创建时间: 2026-04-28
    创建者: Codex
    任务: fix-startup-schema-guard-boundary
    说明: 只有真正的恢复链路异常允许降级；数据库初始化和 schema guard 不在此列。
    """

    mock_shutdown = AsyncMock()
    mock_resume_pending_tasks = AsyncMock()

    with (
        patch("src.storage.db.init_db") as mock_init_db,
        patch.object(main_module, "_recover_orphaned_tasks", side_effect=RuntimeError("cleanup boom")),
        patch.object(main_module, "_resume_pending_tasks", mock_resume_pending_tasks),
        patch("src.api.services.event_manager.event_manager.shutdown", mock_shutdown),
        patch.object(main_module.logger, "warning") as mock_warning,
    ):
        async with main_module.lifespan(main_module.app):
            pass

    mock_init_db.assert_called_once_with()
    mock_resume_pending_tasks.assert_not_awaited()
    mock_shutdown.assert_awaited_once_with()
    mock_warning.assert_any_call("Failed to clean up zombie tasks on startup: cleanup boom")
