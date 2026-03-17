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
修改内容: 添加云端fallback装饰器 with_cloud_fallback
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Tuple, Type, TypeVar

from loguru import logger

F = TypeVar("F", bound=Callable[..., Any])


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
        retryable_exceptions: Tuple[Type[Exception], ...] = (ConnectionError, TimeoutError),
        operation_name: str = "operation",
    ) -> None:
        self.max_retries = max_retries
        self.retryable_exceptions = retryable_exceptions
        self.operation_name = operation_name

    def execute(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        执行带重试的操作

        创建时间: 2026-03-13
        创建者: TraeAI
        任务: refactor-analysis-layer-functions
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
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


def with_retry(
    max_retries: int = 3,
    retryable_exceptions: Tuple[Type[Exception], ...] = (ConnectionError, TimeoutError),
    operation_name: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    统一的API调用重试装饰器

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    说明: 用于装饰需要重试机制的函数

    Args:
        max_retries: 最大重试次数
        retryable_exceptions: 可重试的异常类型元组
        operation_name: 操作名称，用于日志记录

    Returns:
        装饰器函数
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            name = operation_name or func.__name__
            operation = RetryableOperation(
                max_retries=max_retries,
                retryable_exceptions=retryable_exceptions,
                operation_name=name,
            )
            return operation.execute(func, *args, **kwargs)

        return wrapper

    return decorator


def with_cloud_fallback(
    max_retries: int = 3,
    retryable_exceptions: Tuple[Type[Exception], ...] = (ConnectionError, TimeoutError),
    operation_name: str | None = None,
    fallback_client_attr: str = "cloud_client",
) -> Callable[[F], F]:
    """
    带云端fallback的重试装饰器

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - 统一重试机制
    说明: 当本地重试耗尽后，尝试使用云端客户端进行fallback调用

    Args:
        max_retries: 本地最大重试次数
        retryable_exceptions: 可重试的异常类型元组
        operation_name: 操作名称，用于日志记录
        fallback_client_attr: fallback客户端在kwargs中的属性名

    Returns:
        装饰器函数
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            name = operation_name or func.__name__
            cloud_client = kwargs.get(fallback_client_attr)

            # 本地重试
            last_error: Exception | None = None
            for attempt in range(max_retries):
                try:
                    result = func(*args, **kwargs)
                    if attempt > 0:
                        logger.info(f"{name} succeeded on attempt {attempt + 1}/{max_retries}")
                    return result
                except retryable_exceptions as e:
                    last_error = e
                    logger.warning(f"{name} attempt {attempt + 1}/{max_retries} failed: {str(e)}")
                except Exception:
                    # 非可重试异常，直接抛出
                    raise

            # 本地重试耗尽，尝试云端fallback
            if cloud_client is not None:
                logger.info(f"{name} local retries exhausted, trying cloud fallback")
                try:
                    # 移除cloud_client参数后调用云端客户端的同名方法
                    cloud_kwargs = {k: v for k, v in kwargs.items() if k != fallback_client_attr}
                    cloud_method = getattr(cloud_client, func.__name__)
                    return cloud_method(*args, **cloud_kwargs)
                except Exception as e:
                    logger.error(f"{name} cloud fallback failed: {str(e)}")
                    raise MaxRetriesExceededError(
                        f"{name} failed after {max_retries} local retries and cloud fallback: {str(e)}"
                    ) from e

            logger.error(f"{name} failed after {max_retries} retries: {str(last_error)}")
            raise MaxRetriesExceededError(
                f"{name} failed after {max_retries} retries: {str(last_error)}"
            )

        return wrapper  # type: ignore[return-value]

    return decorator
