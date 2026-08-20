"""
说明: 提供错误处理和ID转换等中间件功能
"""

from __future__ import annotations

import time
import uuid

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
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
from src.storage.id_mapping import IDMappingError, TaskIDNotFoundError


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


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """2026-08-13 统一错误 body 契约：路由内直接 raise 的 HTTPException（400/404/409 等）
    此前返回 FastAPI 默认的 {detail}，与自定义异常处理器的 {detail, error_type, status_code}
    两种结构并存。统一为三字段格式（前端 client.ts 以 detail 为主读取，兼容）。
    注意：detail 可能是结构化对象，必须保留原结构不做字符串化。"""
    error_response = create_error_response(
        detail=exc.detail,
        error_type="HTTPException",
        status_code=exc.status_code,
    )
    return error_response.to_json_response()


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """2026-08-13 统一错误 body 契约：请求参数校验失败（422）也走三字段格式，
    detail 转可读字符串（FastAPI 默认 detail 是 [{loc, msg, type}] 列表）。"""
    error_response = create_error_response(
        detail=str(exc.errors()),
        error_type="ValidationError",
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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

    # 2026-08-13 统一错误 body 契约：路由内 HTTPException 与请求校验失败
    # 不再返回 FastAPI 默认 {detail}，与自定义异常处理器同为三字段结构
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

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
