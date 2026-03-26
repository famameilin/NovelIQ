"""
重试工具模块

创建时间: 2026-03-14
创建者: TraeAI
任务: 提取核心业务逻辑到 workflows
说明: 从 src/cli/retry_utils.py 提取的核心业务逻辑，提供统一的API调用重试机制
原始文件: src/cli/retry_utils.py

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - 统一重试机制
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from loguru import logger


class MaxRetriesExceededError(Exception):
    """
    重试次数耗尽异常

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    """

    pass


class RetryableOperation:
    """
    可重试操作封装类

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
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

    def execute(
        self,
        func: Callable[..., Any],
        *args: Any,
        pass_attempt_number: bool = False,
        **kwargs: Any,
    ) -> Any:
        """
        执行带重试的操作

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-analysis-layer-functions

        修改时间: 2026-03-19
        修改者: TraeAI
        任务: 添加模型交互记录保存
        修改内容: 添加 pass_attempt_number 参数，支持传递尝试次数
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                if pass_attempt_number:
                    kwargs["attempt_number"] = attempt + 1
                result = func(*args, **kwargs)
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



