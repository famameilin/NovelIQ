"""
说明: 提供错误处理和ID转换等中间件功能
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.exceptions import (
    AnalysisError,
    AnalysisNotCompleteError,
    FileStorageError,
    GraphReadinessError,
    InvalidFileError,
    NovelNotFoundError,
)
from src.storage.id_mapping import (
    IDMappingError,
    TaskIDNotFoundError,
    convert_response_run_ids_to_task_ids,
    run_id_to_task_id,
    task_id_to_run_id,
)


class ErrorResponse:
    def __init__(self, detail: str, error_type: str, status_code: int, extra: dict | None = None):
        self.detail = detail
        self.error_type = error_type
        self.status_code = status_code
        self.extra = extra or {}

    def to_dict(self) -> dict:
        return {
            "detail": self.detail,
            "error_type": self.error_type,
            "status_code": self.status_code,
            **self.extra,
        }

    def to_json_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content=self.to_dict(),
        )


def create_error_response(
    detail: str,
    error_type: str,
    status_code: int,
    extra: dict | None = None,
) -> ErrorResponse:
    return ErrorResponse(detail=detail, error_type=error_type, status_code=status_code, extra=extra)


async def novel_not_found_handler(request: Request, exc: NovelNotFoundError) -> JSONResponse:
    logger.error(f"NovelNotFoundError: {exc.message}")
    error_response = create_error_response(
        detail=exc.message,
        error_type="NovelNotFoundError",
        status_code=status.HTTP_404_NOT_FOUND,
    )
    return error_response.to_json_response()


async def invalid_file_handler(request: Request, exc: InvalidFileError) -> JSONResponse:
    logger.error(f"InvalidFileError: {exc.message}")
    error_response = create_error_response(
        detail=exc.message,
        error_type="InvalidFileError",
        status_code=status.HTTP_400_BAD_REQUEST,
    )
    return error_response.to_json_response()


async def analysis_not_complete_handler(request: Request, exc: AnalysisNotCompleteError) -> JSONResponse:
    logger.info(f"AnalysisNotCompleteError: {exc.message}")
    error_response = create_error_response(
        detail=exc.message,
        error_type="AnalysisNotCompleteError",
        status_code=status.HTTP_400_BAD_REQUEST,
        extra={"run_status": exc.run_status} if exc.run_status is not None else None,
    )
    return error_response.to_json_response()


async def analysis_error_handler(request: Request, exc: AnalysisError) -> JSONResponse:
    logger.error(f"AnalysisError: {exc.message}")
    error_response = create_error_response(
        detail=exc.message,
        error_type="AnalysisError",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
    return error_response.to_json_response()


async def file_storage_error_handler(request: Request, exc: FileStorageError) -> JSONResponse:
    logger.error(f"FileStorageError: {exc.message}")
    error_response = create_error_response(
        detail=exc.message,
        error_type="FileStorageError",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
    return error_response.to_json_response()


async def graph_readiness_error_handler(request: Request, exc: GraphReadinessError) -> JSONResponse:
    logger.error(f"GraphReadinessError: {exc.message}")
    error_response = create_error_response(
        detail=exc.message,
        error_type="GraphReadinessError",
        status_code=status.HTTP_409_CONFLICT,
    )
    return error_response.to_json_response()


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"Unhandled exception: {str(exc)}")
    error_response = create_error_response(
        detail="Internal server error",
        error_type="InternalServerError",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
    return error_response.to_json_response()


# ID转换相关异常处理器


async def task_id_not_found_handler(request: Request, exc: TaskIDNotFoundError) -> JSONResponse:
    """处理TaskIDNotFoundError异常"""
    logger.error(f"TaskIDNotFoundError: {str(exc)}")
    error_response = create_error_response(
        detail=str(exc),
        error_type="TaskIDNotFoundError",
        status_code=status.HTTP_404_NOT_FOUND,
    )
    return error_response.to_json_response()


async def id_mapping_error_handler(request: Request, exc: IDMappingError) -> JSONResponse:
    """处理IDMappingError异常"""
    logger.error(f"IDMappingError: {str(exc)}")
    error_response = create_error_response(
        detail=str(exc),
        error_type="IDMappingError",
        status_code=status.HTTP_400_BAD_REQUEST,
    )
    return error_response.to_json_response()


# ID转换工具函数


def convert_task_id_to_run_id(task_id: str, conn: Any) -> str:
    """
    将task_id转换为run_id

    Args:
        task_id: 8位task_id
        conn: 数据库连接

    Returns:
        36位run_id

    Raises:
        TaskIDNotFoundError: 如果找不到对应的run_id
    """
    return task_id_to_run_id(task_id, conn)


def convert_run_id_to_task_id(run_id: str) -> str:
    """
    将run_id转换为task_id

    Args:
        run_id: 36位run_id

    Returns:
        8位task_id
    """
    return run_id_to_task_id(run_id)


def convert_response_data(data: dict | list) -> dict | list:
    """
    将响应数据中的run_id转换为task_id

    Args:
        data: 包含run_id字段的字典或列表

    Returns:
        转换后的数据
    """
    return convert_response_run_ids_to_task_ids(data)


# 异常处理器注册


def register_exception_handlers(app) -> None:
    """注册所有异常处理器"""
    # 原有的异常处理器
    app.add_exception_handler(NovelNotFoundError, novel_not_found_handler)
    app.add_exception_handler(InvalidFileError, invalid_file_handler)
    app.add_exception_handler(AnalysisNotCompleteError, analysis_not_complete_handler)
    app.add_exception_handler(AnalysisError, analysis_error_handler)
    app.add_exception_handler(FileStorageError, file_storage_error_handler)
    app.add_exception_handler(GraphReadinessError, graph_readiness_error_handler)

    # ID转换相关异常处理器
    app.add_exception_handler(TaskIDNotFoundError, task_id_not_found_handler)
    app.add_exception_handler(IDMappingError, id_mapping_error_handler)

    # 通用异常处理器（最后注册）
    app.add_exception_handler(Exception, generic_exception_handler)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    请求日志中间件

    说明: 记录每个请求的进入、退出和耗时信息
    """

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        logger.info(f"[{request_id}] → {request.method} {request.url.path}")

        response = await call_next(request)
        duration = time.time() - start_time
        logger.info(f"[{request_id}] ← {response.status_code} ({duration:.3f}s)")
        response.headers["X-Request-ID"] = request_id
        return response


def register_middlewares(app) -> None:
    """
    注册所有中间件

    说明: 注册请求日志等中间件
    """
    app.add_middleware(RequestLoggingMiddleware)
