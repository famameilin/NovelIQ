"""
FastAPI 应用入口模块
"""

from __future__ import annotations

import socket
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy import text

from src.api.app_bootstrap import (
    analysis_router,
    linguistic_router,
    novels_router,
    register_exception_handlers,
    register_middlewares,
    results_router,
    settings_router,
    sse_router,
    tabs_router,
    timeline_router,
)
from src.workflows.startup_recovery import recover_orphaned_runs, resume_pending_tasks


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI application starting up...")

    # 启动只初始化缺失表；schema guard 失败必须直接阻断启动
    from src.storage.db import init_db

    init_db()
    from src.sse.manager import event_manager
    from src.sse.persistence import SseMessageRepository
    from src.storage.db import get_session_factory

    event_manager.configure_outbox(SseMessageRepository(lambda: get_session_factory()()))

    # 只有重启遗留任务收口链路允许降级失败
    try:
        from src.api.dependencies import get_task_manager, get_task_service

        failed_count, cancelled_count = recover_orphaned_runs()
        scheduled_pending_count, cancelled_pending_count = await resume_pending_tasks(
            get_task_service(), get_task_manager()
        )
        if failed_count > 0:
            logger.info(f"Successfully failed {failed_count} running task(s) left by the previous process")
        if cancelled_count > 0:
            logger.info(f"Successfully finalized {cancelled_count} cancelling task(s) left by the previous process")
        if scheduled_pending_count > 0:
            logger.info(f"Successfully rescheduled {scheduled_pending_count} pending task(s) on startup")
        if cancelled_pending_count > 0:
            logger.info(f"Successfully finalized {cancelled_pending_count} pending cancellation(s) on startup")
        if failed_count == 0 and cancelled_count == 0 and scheduled_pending_count == 0 and cancelled_pending_count == 0:
            logger.debug("No running/cancelling or pending tasks found on startup")
    except Exception as e:
        logger.warning(f"Failed to clean up tasks left by the previous process on startup: {e}")

    try:
        yield
    finally:
        logger.info("FastAPI application shutting down...")
        try:
            from src.sse.manager import event_manager

            # 应用 shutdown 不把仍在运行的分析任务收口成“用户取消”
            # TaskManager 运行态缓存仅供当前进程使用；测试单例由 fixture 显式调用 reset_for_testing() 清理
            await event_manager.shutdown()
        except Exception as exc:
            logger.warning(f"Failed to cleanly shut down runtime singletons: {exc}")


app = FastAPI(
    title="小说量化分析 API",
    version="0.2.2",
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
    """健康检查端点：检查数据库连接状态，异常时返回 503"""
    from src.storage.db import get_pool_status, get_session

    logger.debug("Health check endpoint called")

    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))

        pool_status = get_pool_status()
        return {
            "status": "healthy",
            "service": "novel-qa-api",
            "version": "0.2.2",
            "pool": pool_status,
        }
    except Exception as e:
        # 503 body 不得透传内部异常原文（可能含连接串/堆栈细节），错误详情只写日志，对外返回通用文案
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "service": "novel-qa-api",
                "version": "0.2.2",
                "error": "服务暂不可用，请稍后重试",
            },
        )


app.include_router(novels_router, prefix="/api")
app.include_router(analysis_router, prefix="/api")
app.include_router(results_router, prefix="/api")
app.include_router(linguistic_router, prefix="/api")
app.include_router(tabs_router, prefix="/api")
app.include_router(timeline_router, prefix="/api")
app.include_router(settings_router, prefix="/api", tags=["settings"])
app.include_router(sse_router, prefix="/api", tags=["SSE"])

register_exception_handlers(app)


def is_port_in_use(port: int) -> bool:
    """
    检测指定端口是否被占用
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
