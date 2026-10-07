"""
FastAPI 启动边界测试。

创建时间: 2026-04-28
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
    任务: fix-startup-schema-guard-boundary
    说明: 旧诊断表的 protagonist 列属于结构性 schema 错误；
          这里要求 lifespan 原样抛出异常，保持 fail-closed 语义。
    """

    with (
        patch("src.storage.db.init_db", side_effect=RuntimeError("schema mismatch")) as mock_init_db,
        patch.object(main_module, "recover_orphaned_runs") as mock_recover_orphaned_tasks,
    ):
        with pytest.raises(RuntimeError, match="schema mismatch"):
            async with main_module.lifespan(main_module.app):
                pass

    mock_init_db.assert_called_once_with()
    mock_recover_orphaned_tasks.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_keeps_startup_cleanup_failure_as_warning() -> None:
    """
    重启遗留任务收口失败时应记 warning，但不应掩盖已成功完成的 init_db。

    创建时间: 2026-04-28
    任务: fix-startup-schema-guard-boundary
    说明: 只有真正的恢复链路异常允许降级；数据库初始化和 schema guard 不在此列。
    """

    mock_shutdown = AsyncMock()
    mock_resume_pending_tasks = AsyncMock()

    with (
        patch("src.storage.db.init_db") as mock_init_db,
        patch.object(main_module, "recover_orphaned_runs", side_effect=RuntimeError("cleanup boom")),
        patch.object(main_module, "resume_pending_tasks", mock_resume_pending_tasks),
        patch("src.sse.manager.event_manager.shutdown", mock_shutdown),
        patch.object(main_module.logger, "warning") as mock_warning,
    ):
        async with main_module.lifespan(main_module.app):
            pass

    mock_init_db.assert_called_once_with()
    mock_resume_pending_tasks.assert_not_awaited()
    mock_shutdown.assert_awaited_once_with()
    # 只要求降级成 warning 且带上失败原因，不锁定文案
    assert any("cleanup boom" in str(call.args[0]) for call in mock_warning.call_args_list)
