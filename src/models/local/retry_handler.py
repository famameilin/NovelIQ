"""
标注客户端重试处理模块

创建时间: 2026-03-17
创建者: TraeAI
任务: code-quality-refactor - 统一重试机制
说明: 提供AnnotationClient专用的重试逻辑，支持本地重试和云端fallback

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - Task 3 统一重试机制
修改内容: 修复循环导入问题，异常类型通过参数传入
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
    说明: 处理标注客户端的复杂重试逻辑，包括本地重试和云端fallback

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 3 统一重试机制
    修改内容: 添加异常类型参数避免循环导入
    """

    def __init__(
        self,
        config: RetryConfig,
        local_client: Any,
        cloud_client: Any | None = None,
        exception_type: type[Exception] | None = None,
    ) -> None:
        self.config = config
        self.local_client = local_client
        self.cloud_client = cloud_client
        self.exception_type = exception_type
        self.state = RetryState()

    def execute(
        self,
        operation: Callable[..., T],
        build_retry_messages: Callable[[], Any] | None = None,
    ) -> T:
        """
        执行带重试的操作

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 统一重试机制
        """
        # 本地重试
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

                # 如果有重试消息构建函数，使用它
                if build_retry_messages and self.state.last_bad_output:
                    messages = build_retry_messages()
                    result = operation(self.local_client, messages)
                else:
                    result = operation(self.local_client)

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

        # 云端fallback
        if self.cloud_client is not None:
            return self._try_cloud_fallback(operation, build_retry_messages)

        # 所有重试失败
        self._raise_max_retries_error()

    def _handle_error(self, error: Exception) -> None:
        """处理错误，提取重试信息"""
        # 检查是否有invalid_names属性（NameValidationMaxRetriesExceededError）
        if hasattr(error, "invalid_names"):
            self.state.last_invalid_names = error.invalid_names
            self.state.last_bad_output = getattr(error, "bad_output", "")
            self.state.last_validation_details = getattr(error, "validation_details", None)

        # 检查是否是重复输出错误
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

    def _try_cloud_fallback(
        self,
        operation: Callable[..., T],
        build_retry_messages: Callable[[], Any] | None = None,
    ) -> T:
        """尝试云端fallback"""
        logger.warning(
            "{} local model failed after {} attempts, falling back to cloud model chunk_id={}",
            self.config.operation_name,
            self.config.max_retries,
            self.config.chunk_id,
        )

        try:
            logger.debug(
                "{} cloud attempt chunk_id={}",
                self.config.operation_name,
                self.config.chunk_id,
            )

            if build_retry_messages and self.state.last_bad_output:
                messages = build_retry_messages()
                result = operation(self.cloud_client, messages)
            else:
                result = operation(self.cloud_client)

            logger.info(
                "{} cloud succeeded chunk_id={}",
                self.config.operation_name,
                self.config.chunk_id,
            )
            return result

        except Exception as e:
            self.state.last_error = e
            logger.error(
                "{} cloud failed: {} chunk_id={}",
                self.config.operation_name,
                str(e),
                self.config.chunk_id,
            )
            self._raise_max_retries_error()

    def _raise_max_retries_error(self) -> NoReturn:
        """抛出最大重试次数 exceeded 错误"""
        error_msg = f"{self.config.operation_name} failed after {self.config.max_retries} local + 1 cloud retries: {str(self.state.last_error)}"
        logger.error(
            "{} failed after all retries chunk_id={}: {}",
            self.config.operation_name,
            self.config.chunk_id,
            str(self.state.last_error),
        )

        # 使用传入的异常类型或默认异常
        if self.exception_type is not None:
            raise self.exception_type(error_msg)
        else:
            # 根据操作名选择异常类型
            if "phase2" in self.config.operation_name.lower():
                from src.models.local.annotation import Phase2MaxRetriesExceededError

                raise Phase2MaxRetriesExceededError(error_msg)
            else:
                from src.models.local.annotation import Phase1MaxRetriesExceededError

                raise Phase1MaxRetriesExceededError(error_msg)
