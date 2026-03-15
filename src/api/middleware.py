from __future__ import annotations


from fastapi import Request, status
from fastapi.responses import JSONResponse
from loguru import logger

from src.api.exceptions import (
    AnalysisError,
    AnalysisNotCompleteError,
    FileStorageError,
    InvalidFileError,
    NovelNotFoundError,
)


class ErrorResponse:
    def __init__(self, detail: str, error_type: str, status_code: int):
        self.detail = detail
        self.error_type = error_type
        self.status_code = status_code

    def to_dict(self) -> dict:
        return {
            "detail": self.detail,
            "error_type": self.error_type,
            "status_code": self.status_code,
        }

    def to_json_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content=self.to_dict(),
        )


def create_error_response(detail: str, error_type: str, status_code: int) -> ErrorResponse:
    return ErrorResponse(detail=detail, error_type=error_type, status_code=status_code)


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
    logger.error(f"AnalysisNotCompleteError: {exc.message}")
    error_response = create_error_response(
        detail=exc.message,
        error_type="AnalysisNotCompleteError",
        status_code=status.HTTP_400_BAD_REQUEST,
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


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"Unhandled exception: {str(exc)}")
    error_response = create_error_response(
        detail="Internal server error",
        error_type="InternalServerError",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
    return error_response.to_json_response()


def register_exception_handlers(app) -> None:
    app.add_exception_handler(NovelNotFoundError, novel_not_found_handler)
    app.add_exception_handler(InvalidFileError, invalid_file_handler)
    app.add_exception_handler(AnalysisNotCompleteError, analysis_not_complete_handler)
    app.add_exception_handler(AnalysisError, analysis_error_handler)
    app.add_exception_handler(FileStorageError, file_storage_error_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
