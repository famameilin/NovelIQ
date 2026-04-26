"""
FastAPI 应用入口模块

创建时间: 2025-03-11
创建者: TraeAI
任务: 小说量化分析 API 服务

修改时间: 2026-03-11
修改者: TraeAI
修改内容: 添加端口占用检测功能，当使用 python -m uvicorn 启动时检测端口是否被占用

修改时间: 2026-03-14
修改者: TraeAI
修改内容: 修复日志配置顺序问题，确保日志配置在导入 routes 模块之前完成，
          避免 NovelService 初始化时的 DEBUG 日志输出到控制台

修改时间: 2026-03-16
修改者: TraeAI
修改内容: 添加 .env 文件加载，确保环境变量正确设置

修改时间: 2026-03-19
修改者: TraeAI
修改内容: 移除 load_dotenv，改为在 config 模块中统一加载

修改时间: 2026-04-04
修改者: AI Assistant
任务: fix-backend-stability
修改内容: 增强健康检查端点，添加数据库连接检测和降级响应

修改时间: 2026-04-07
修改者: TraeAI
任务: websocket-streaming-progress
修改内容: 注册 WebSocket 路由，支持实时进度推送

修改时间: 2026-04-09
修改者: TraeAI
任务: 实现 SSE 路由和事件管理器
修改内容: 注册 SSE 路由，支持 Server-Sent Events 实时推送
修改时间: 2026-04-19
修改者: TraeAI
任务: Task 7 - 实现启动时任务恢复逻辑
修改内容: 完善孤儿任务清理日志,记录清理的任务数量
"""

from __future__ import annotations

import socket
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy import text

from src.api.app_bootstrap import (
    analysis_router,
    novels_router,
    register_exception_handlers,
    register_middlewares,
    results_router,
    sse_router,
    timeline_router,
)

ORPHAN_TASK_HEARTBEAT_TIMEOUT = timedelta(minutes=5)


def _recover_orphaned_tasks() -> tuple[int, int]:
    """
    启动时收口上次进程遗留的孤儿任务。

    创建时间: 2026-04-19
    创建者: Codex (GPT-5)
    任务: fix-task-system-review-findings
    修改内容: 同时清理 orphaned running 与 orphaned cancelling，避免取消中的任务永久卡死。

    Returns:
        tuple[int, int]: (failed_count, cancelled_count)
    """
    from src.storage.db import get_session
    from src.storage.repositories import RunRepository

    stale_before = datetime.now(UTC) - ORPHAN_TASK_HEARTBEAT_TIMEOUT
    with get_session() as session:
        repo = RunRepository(session)
        failed_count = repo.mark_running_as_failed(stale_before=stale_before)
        cancelled_count = repo.mark_cancelling_as_cancelled(stale_before=stale_before)
        return failed_count, cancelled_count


async def _resume_pending_tasks() -> tuple[int, int]:
    """
    启动时把 DB 中可恢复的 pending 任务重新接回执行器。

    创建时间: 2026-04-20
    创建者: Codex (GPT-5)
    任务: fix-pending-task-pickup
    修改内容: 为 DB 中遗留的 pending 任务补启动恢复链，避免进程重启后只能人工点击 resume。

    Returns:
        tuple[int, int]: (scheduled_count, cancelled_count)
    """
    from src.api.dependencies import get_novel_service
    from src.api.routes.analysis import get_task_manager
    from src.api.services.analysis_service import AnalysisService

    analysis_service = AnalysisService(get_novel_service(), get_task_manager())
    return await analysis_service.recover_pending_tasks()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI application starting up...")

    # 中文注释：当前仓库以最新 schema 为唯一真相，启动时只初始化缺失表，
    # 然后再做孤儿任务恢复。
    try:
        from src.storage.db import init_db

        init_db()
        failed_count, cancelled_count = _recover_orphaned_tasks()
        scheduled_pending_count, cancelled_pending_count = await _resume_pending_tasks()
        if failed_count > 0:
            logger.info(f"Successfully cleaned {failed_count} orphaned running task(s)")
        if cancelled_count > 0:
            logger.info(f"Successfully finalized {cancelled_count} orphaned cancelling task(s)")
        if scheduled_pending_count > 0:
            logger.info(f"Successfully rescheduled {scheduled_pending_count} pending task(s) on startup")
        if cancelled_pending_count > 0:
            logger.info(f"Successfully finalized {cancelled_pending_count} pending cancellation(s) on startup")
        if failed_count == 0 and cancelled_count == 0 and scheduled_pending_count == 0 and cancelled_pending_count == 0:
            logger.debug("No orphaned running/cancelling or pending tasks found on startup")
    except Exception as e:
        logger.warning(f"Failed to clean up zombie tasks on startup: {e}")

    try:
        yield
    finally:
        logger.info("FastAPI application shutting down...")
        try:
            from src.api.dependencies import get_task_manager
            from src.api.services.event_manager import event_manager

            await get_task_manager().shutdown()
            await event_manager.shutdown()
        except Exception as exc:
            logger.warning(f"Failed to cleanly shut down runtime singletons: {exc}")


app = FastAPI(
    title="小说量化分析 API",
    version="0.1.0",
    description="小说文本量化分析服务的 RESTful API",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_middlewares(app)


@app.get("/health", tags=["Health"])
async def health_check():
    """
    健康检查端点

    创建时间: 2026-04-04
    创建者: AI Assistant
    任务: fix-backend-stability
    说明: 检查数据库连接状态，异常时返回 503
    """
    from src.storage.db import get_pool_status, get_session

    logger.debug("Health check endpoint called")

    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))

        pool_status = get_pool_status()
        return {
            "status": "healthy",
            "service": "novel-qa-api",
            "version": "0.1.0",
            "pool": pool_status,
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "service": "novel-qa-api",
                "version": "0.1.0",
                "error": str(e),
            },
        )


app.include_router(novels_router, prefix="/api")
app.include_router(analysis_router, prefix="/api")
app.include_router(results_router, prefix="/api")
app.include_router(timeline_router, prefix="/api")
app.include_router(sse_router, prefix="/api", tags=["SSE"])

register_exception_handlers(app)


def is_port_in_use(port: int) -> bool:
    """
    检测指定端口是否被占用

    创建时间: 2026-03-11
    创建者: TraeAI
    任务: 添加端口占用检测功能

    修改时间: 2026-03-11
    修改者: TraeAI
    修改内容: 同时检测 127.0.0.1 和 0.0.0.0 两个地址，避免 Windows 下的绑定差异问题
    """
    for check_host in ["127.0.0.1", "0.0.0.0"]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((check_host, port))
            except OSError:
                return True
    return False


def run_server(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """
    启动 FastAPI 服务器，带端口占用检测

    创建时间: 2026-03-11
    创建者: TraeAI
    任务: 添加端口占用检测功能
    """
    import uvicorn

    if is_port_in_use(port):
        print(f"\033[91m错误: 端口 {port} 已被占用，请使用其他端口或关闭占用该端口的进程。\033[0m")
        print("提示: 使用 --port 参数指定其他端口，例如: python -m src.api.main --port 8001")
        sys.exit(1)

    logger.info(f"正在启动服务器，监听 {host}:{port}")
    uvicorn.run(
        "src.api.main:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="启动小说量化分析 API 服务器")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址 (默认: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="监听端口 (默认: 8000)")
    parser.add_argument("--reload", action="store_true", help="启用开发模式自动重载")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port, reload=args.reload)
