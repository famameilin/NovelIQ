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
"""

from __future__ import annotations

import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src.config.logging_config import setup_logging

setup_logging(verbose=True, debug=False)

from src.api.routes import novels_router, analysis_router, results_router  # noqa: E402
from src.api.middleware import register_exception_handlers  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI application starting up...")
    yield
    logger.info("FastAPI application shutting down...")


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


@app.get("/health", tags=["Health"])
async def health_check():
    logger.debug("Health check endpoint called")
    return {"status": "healthy", "service": "novel-qa-api", "version": "0.1.0"}


app.include_router(novels_router, prefix="/api")
app.include_router(analysis_router, prefix="/api")
app.include_router(results_router, prefix="/api")

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
