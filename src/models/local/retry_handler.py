"""
标注客户端重试处理模块

创建时间: 2026-03-17
创建者: TraeAI
任务: code-quality-refactor - 统一重试机制
说明: 提供 AnnotationClient 专用的重试逻辑，支持主客户端重试和兜底客户端 fallback

修改时间: 2026-04-09
修改者: TraeAI
任务: 重构 AnnotationClient 使用 async
修改内容: execute 方法改为 async def
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NoReturn, TypeVar

from loguru import logger

T = TypeVar("T")


@dataclass
class RetryState:
    """重试状态"""

    attempt: int = 0
    last_error: Exception | None = None
    last_invalid_names: list[str] | None = None
    last_bad_output: str = ""
    last_validation_details: dict[str, list[str]] | None = None


@dataclass
class RetryConfig:
    """重试配置"""

    max_retries: int = 3
    operation_name: str = "operation"
    chunk_id: int | None = None


class AnnotationRetryHandler[T]:
    """
    标注重试处理器

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 统一重试机制
    说明: 处理标注客户端的复杂重试逻辑，包括主客户端重试和兜底客户端 fallback

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: execute 方法改为 async def，支持 async operation
    """

    def __init__(
        self,
        config: RetryConfig,
        primary_client: Any,
        fallback_client: Any | None = None,
        exception_type: type[Exception] | None = None,
    ) -> None:
        self.config = config
        self.primary_client = primary_client
        self.fallback_client = fallback_client
        self.exception_type = exception_type
        self.state = RetryState()

    async def execute(
        self,
        operation: Callable[..., Any],
        build_retry_messages: Callable[[], Any] | None = None,
    ) -> T:
        """
        执行带重试的操作

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 统一重试机制

        修改时间: 2026-04-09
        修改者: TraeAI
        任务: 重构 AnnotationClient 使用 async
        修改内容: 改为 async def，使用 await 调用 operation
        """
        for attempt in range(self.config.max_retries):
            self.state.attempt = attempt + 1
            try:
                logger.debug(
                    "{} attempt {}/{} chunk_id={}",
                    self.config.operation_name,
                    self.state.attempt,
                    self.config.max_retries,
                    self.config.chunk_id,
                )

                if build_retry_messages and self.state.last_bad_output:
                    messages = build_retry_messages()
                    result = await operation(self.primary_client, messages)
                else:
                    result = await operation(self.primary_client)

                if attempt > 0:
                    logger.info(
                        "{} succeeded on attempt {} chunk_id={}",
                        self.config.operation_name,
                        self.state.attempt,
                        self.config.chunk_id,
                    )
                return result

            except Exception as e:
                self.state.last_error = e
                self._handle_error(e)

        if self.fallback_client is not None:
            return await self._try_fallback_client(operation, build_retry_messages)

        self._raise_max_retries_error()

    def _handle_error(self, error: Exception) -> None:
        """处理错误，提取重试信息"""
        if hasattr(error, "invalid_names"):
            self.state.last_invalid_names = error.invalid_names
            self.state.last_bad_output = getattr(error, "bad_output", "")
            self.state.last_validation_details = getattr(error, "validation_details", None)

        if error.__class__.__name__ == "RepetitiveOutputError":
            self.state.last_bad_output = str(error)

        logger.error(
            "{} attempt {}/{} failed: {} chunk_id={}",
            self.config.operation_name,
            self.state.attempt,
            self.config.max_retries,
            str(error),
            self.config.chunk_id,
        )

    async def _try_fallback_client(
        self,
        operation: Callable[..., Any],
        build_retry_messages: Callable[[], Any] | None = None,
    ) -> T:
        """
        尝试兜底客户端。

        修改时间: 2026-04-27
        修改者: Codex
        任务: fix-phase3-fastpath-followup-review-findings
        修改内容: fallback 视为独立一次调用，进入兜底前补记真实 attempt 次数，避免 runtime 审计少记一次重试。
        """
        logger.warning(
            "{} primary client failed after {} attempts, falling back to fallback client chunk_id={}",
            self.config.operation_name,
            self.config.max_retries,
            self.config.chunk_id,
        )

        try:
            self.state.attempt = self.config.max_retries + 1
            logger.debug(
                "{} fallback attempt {} chunk_id={}",
                self.config.operation_name,
                self.state.attempt,
                self.config.chunk_id,
            )

            if build_retry_messages and self.state.last_bad_output:
                messages = build_retry_messages()
                result = await operation(self.fallback_client, messages)
            else:
                result = await operation(self.fallback_client)

            logger.info(
                "{} fallback succeeded on attempt {} chunk_id={}",
                self.config.operation_name,
                self.state.attempt,
                self.config.chunk_id,
            )
            return result

        except Exception as e:
            self.state.last_error = e
            logger.error(
                "{} fallback failed: {} chunk_id={}",
                self.config.operation_name,
                str(e),
                self.config.chunk_id,
            )
            self._raise_max_retries_error()

    def _raise_max_retries_error(self) -> NoReturn:
        """抛出最大重试次数 exceeded 错误"""
        error_msg = (
            f"{self.config.operation_name} failed after "
            f"{self.config.max_retries} primary + 1 fallback retries: "
            f"{str(self.state.last_error)}"
        )
        logger.error(
            "{} failed after all retries chunk_id={}: {}",
            self.config.operation_name,
            self.config.chunk_id,
            str(self.state.last_error),
        )

        if self.exception_type is not None:
            raise self.exception_type(error_msg)
        else:
            if "phase2" in self.config.operation_name.lower():
                from src.models.local.annotation import Phase2MaxRetriesExceededError

                raise Phase2MaxRetriesExceededError(error_msg)
            else:
                from src.models.local.annotation import Phase1MaxRetriesExceededError

                raise Phase1MaxRetriesExceededError(error_msg)
