"""
说明: HTTP 错误 body 统一契约（三字段 detail/error_type/status_code）与请求日志中间件

域异常由各域定义（运行编排 src/workflows、事实图 src/fact_graph、配置 src/config、存储 src/storage），
本模块只做「异常类型 → 状态码 + 文案」的映射表与注册。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

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
    SettingsValidationError,
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


def _message_of(exc: Exception) -> str:
    return getattr(exc, "message", None) or str(exc)


def _run_status_extra(exc: Exception) -> dict | None:
    run_status = getattr(exc, "run_status", None)
    return {"run_status": run_status} if run_status is not None else None


# 域异常映射表：(异常类型, error_type 标签, HTTP 状态码, 日志级别, 附加字段提取)
_EXCEPTION_MAP: tuple[tuple[type[Exception], str, int, str, Callable[[Exception], dict | None] | None], ...] = (
    (NovelNotFoundError, "NovelNotFoundError", status.HTTP_404_NOT_FOUND, "error", None),
    (InvalidFileError, "InvalidFileError", status.HTTP_400_BAD_REQUEST, "error", None),
    (AnalysisNotCompleteError, "AnalysisNotCompleteError", status.HTTP_400_BAD_REQUEST, "info", _run_status_extra),
    (AnalysisError, "AnalysisError", status.HTTP_500_INTERNAL_SERVER_ERROR, "error", None),
    (FileStorageError, "FileStorageError", status.HTTP_500_INTERNAL_SERVER_ERROR, "error", None),
    (GraphReadinessError, "GraphReadinessError", status.HTTP_409_CONFLICT, "error", None),
    (SettingsValidationError, "SettingsValidationError", status.HTTP_422_UNPROCESSABLE_ENTITY, "error", None),
    (TaskIDNotFoundError, "TaskIDNotFoundError", status.HTTP_404_NOT_FOUND, "error", None),
    (IDMappingError, "IDMappingError", status.HTTP_400_BAD_REQUEST, "error", None),
)


def _make_domain_handler(
    error_type: str,
    status_code: int,
    log_level: str,
    extra_of: Callable[[Exception], dict | None] | None,
) -> Callable[[Request, Exception], object]:
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        message = _message_of(exc)
        getattr(logger, log_level)(f"{error_type}: {message}")
        return create_error_response(
            detail=message,
            error_type=error_type,
            status_code=status_code,
            extra=extra_of(exc) if extra_of else None,
        ).to_json_response()

    return handler


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
    errors = exc.errors()
    if request.url.path.startswith("/api/settings"):
        # 设置请求包含模型 Key，校验失败也不能回显原始输入
        errors = [{key: value for key, value in error.items() if key not in {"input", "ctx"}} for error in errors]
    error_response = create_error_response(
        detail=str(errors),
        error_type="ValidationError",
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    return error_response.to_json_response()


def register_exception_handlers(app) -> None:
    """注册域异常映射表 + 三个契约级处理器（HTTPException/校验失败/兜底）"""
    for exc_type, error_type, status_code, log_level, extra_of in _EXCEPTION_MAP:
        app.add_exception_handler(exc_type, _make_domain_handler(error_type, status_code, log_level, extra_of))

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
