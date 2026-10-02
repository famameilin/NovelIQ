"""物理模型请求的 Provider permit 上下文"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from src.storage.repositories.provider_permits import (
    PermitReceipt,
    ProviderLimits,
    ProviderPermitRepository,
)


@dataclass(frozen=True, slots=True)
class ProviderRequestScope:
    """单个 Agent work 的网络预算与取消边界

    2026-10-02 删除工作级 deadline：并发语义归位为章槽位后，工作只在容量内启动，
    排队不再烧墙钟；单请求超时由模型客户端 timeout 承担，失败走 attempt 重选链。
    """

    repository: ProviderPermitRepository
    owner: str
    work_id: str | None
    hard_max_in_flight: int
    is_cancelled: Callable[[], bool] | None = None
    lease_seconds: int = 180
    model_pool_managed: bool = False


@dataclass(slots=True)
class PermitTicket:
    actual_tokens: int | None = None


_current_scope: ContextVar[ProviderRequestScope | None] = ContextVar("provider_request_scope", default=None)


@contextmanager
def provider_request_scope(scope: ProviderRequestScope):
    """把工作预算绑定到协程上下文，子模型回合沿用同一取消边界"""
    token = _current_scope.set(scope)
    try:
        yield
    finally:
        _current_scope.reset(token)


def _model_identity(model: Any) -> tuple[str, str]:
    bound = getattr(model, "bound", model)
    base_url = str(getattr(bound, "base_url", None) or getattr(bound, "openai_api_base", None) or "")
    name = str(getattr(bound, "model_name", None) or getattr(bound, "model", None) or "")
    if not base_url or not name:
        raise ValueError("受控模型请求缺少 base_url 或 model")
    return base_url, name


def _reserve_tokens(messages: list[Any], model: Any, *, endpoint: str = "chat_completions") -> int:
    """以 UTF-8 长度保守估算输入并预留完整输出上限，实耗在释放时校正"""
    bound = getattr(model, "bound", model)
    configured_output = getattr(bound, "max_completion_tokens", None) or getattr(bound, "max_tokens", None)
    output_reservation = 0 if endpoint == "embeddings" else max(int(configured_output or 2048), 1)
    input_bytes = sum(len(str(getattr(message, "content", message)).encode("utf-8")) for message in messages)
    return max(1, input_bytes + output_reservation)


def _status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return int(status) if isinstance(status, int) else None


def _retry_after_seconds(exc: BaseException) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    raw = headers.get("Retry-After") if headers is not None else None
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(str(raw))
        except (TypeError, ValueError):
            return None
        if date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
        return max(0.0, (date - datetime.now(UTC)).total_seconds())


async def _finish_permit_operation[Result](operation: asyncio.Task[Result]) -> Result:
    """取消不能终止数据库线程；重复取消时仍须取回许可并完成归还"""
    while True:
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            if operation.cancelled():
                raise


@asynccontextmanager
async def provider_permit_for_model(
    model: Any, messages: list[Any], *, endpoint: str = "chat_completions",
) -> AsyncIterator[PermitTicket]:
    """每次重试重新领取 permit；等待容量时不持有 Session"""
    scope = _current_scope.get()
    ticket = PermitTicket()
    if scope is None:
        yield ticket
        return
    base_url, model_name = _model_identity(model)
    concurrency = scope.hard_max_in_flight
    if scope.model_pool_managed and endpoint == "chat_completions":
        from src.config import settings

        configured = next((entry for entry in settings.models.model_pool if entry.model_id == model_name
                           and entry.base_url.rstrip("/") == base_url.rstrip("/")), None)
        if configured is None:
            raise ValueError("当前请求模型已不在模型池中")
        concurrency = configured.max_in_flight
    limits = ProviderLimits(
        base_url=base_url,
        model=model_name,
        endpoint=endpoint,
        hard_max_in_flight=concurrency,
    )
    provider_key = await asyncio.to_thread(
        scope.repository.configure, limits,
        authoritative_concurrency=scope.model_pool_managed and endpoint == "chat_completions",
    )
    reserved_tokens = _reserve_tokens(messages, model, endpoint=endpoint)
    receipt: PermitReceipt | None = None
    while receipt is None:
        if scope.is_cancelled is not None and scope.is_cancelled():
            raise asyncio.CancelledError("工作已取消，停止领取 Provider permit")
        acquisition = asyncio.create_task(asyncio.to_thread(
            scope.repository.acquire,
            provider_key=provider_key,
            owner=scope.owner,
            work_id=scope.work_id,
            reserved_tokens=reserved_tokens,
            lease_seconds=scope.lease_seconds,
        ))
        try:
            receipt = await asyncio.shield(acquisition)
        except asyncio.CancelledError:
            unused_receipt = await _finish_permit_operation(acquisition)
            if unused_receipt is not None:
                await _finish_permit_operation(asyncio.create_task(asyncio.to_thread(
                    scope.repository.release, unused_receipt, status_code=None, actual_tokens=0,
                )))
            raise
        if receipt is None:
            await asyncio.sleep(0.3 + random.uniform(0.0, 0.2))
    owner_task = asyncio.current_task()
    monitor_error: BaseException | None = None
    stopping = False

    async def monitor_request() -> None:
        nonlocal monitor_error
        next_renew = time.monotonic() + scope.lease_seconds / 3
        try:
            while True:
                await asyncio.sleep(0.1)
                if scope.is_cancelled is not None and scope.is_cancelled():
                    raise asyncio.CancelledError("模型流中的工作已取消")
                if time.monotonic() >= next_renew:
                    await asyncio.to_thread(scope.repository.renew, receipt, lease_seconds=scope.lease_seconds)
                    next_renew = time.monotonic() + scope.lease_seconds / 3
        except BaseException as exc:
            if stopping:
                return
            monitor_error = exc
            if owner_task is not None:
                owner_task.cancel()

    renew_task = asyncio.create_task(monitor_request())
    started = time.monotonic()
    status_code: int | None = 200
    retry_after: float | None = None
    try:
        yield ticket
    except BaseException as exc:
        effective_error = monitor_error or exc
        status_code = _status_code(effective_error)
        retry_after = _retry_after_seconds(effective_error)
        if monitor_error is not None:
            raise monitor_error from exc
        raise
    finally:
        stopping = True
        renew_task.cancel()
        await asyncio.gather(renew_task, return_exceptions=True)
        await asyncio.to_thread(
            scope.repository.release,
            receipt,
            status_code=status_code,
            actual_tokens=ticket.actual_tokens,
            retry_after_seconds=retry_after,
            latency_ms=(time.monotonic() - started) * 1000,
        )
