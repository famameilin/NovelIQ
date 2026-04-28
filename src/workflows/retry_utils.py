"""
重试工具模块

从 src/cli/retry_utils.py 提取的核心业务逻辑，提供统一的API调用重试机制
原始文件: src/cli/retry_utils.py

"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from loguru import logger


class MaxRetriesExceededError(Exception):
    """
    重试次数耗尽异常

    """

    pass


class RetryableOperation:
    """
    可重试操作封装类

    """

    def __init__(
        self,
        max_retries: int = 3,
        retryable_exceptions: tuple[type[Exception], ...] = (ConnectionError, TimeoutError),
        operation_name: str = "operation",
    ) -> None:
        self.max_retries = max_retries
        self.retryable_exceptions = retryable_exceptions
        self.operation_name = operation_name

    async def execute(
        self,
        func: Callable[..., Any],
        *args: Any,
        pass_attempt_number: bool = False,
        **kwargs: Any,
    ) -> Any:
        """
        执行带重试的操作（async 版本）



        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                if pass_attempt_number:
                    kwargs["attempt_number"] = attempt + 1
                result = await func(*args, **kwargs)
                if attempt > 0:
                    logger.info(f"{self.operation_name} succeeded on attempt {attempt + 1}/{self.max_retries}")
                return result
            except self.retryable_exceptions as e:
                last_error = e
                logger.warning(f"{self.operation_name} attempt {attempt + 1}/{self.max_retries} failed: {str(e)}")
            except Exception as e:
                last_error = e
                logger.error(f"{self.operation_name} attempt {attempt + 1}/{self.max_retries} failed: {str(e)}")

        logger.error(f"{self.operation_name} failed after {self.max_retries} retries: {str(last_error)}")
        raise MaxRetriesExceededError(
            f"{self.operation_name} failed after {self.max_retries} retries: {str(last_error)}"
        )
