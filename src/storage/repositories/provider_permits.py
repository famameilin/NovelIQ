"""跨进程模型供应方并发与限流预算"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.agents.annotation.identity import stable_digest
from src.storage.models import ProviderBudget, ProviderPermitLease


@dataclass(frozen=True, slots=True)
class ProviderLimits:
    base_url: str
    model: str
    endpoint: str
    hard_max_in_flight: int

    @property
    def provider_key(self) -> str:
        return stable_digest(_safe_base_url(self.base_url), self.model, self.endpoint)


@dataclass(frozen=True, slots=True)
class PermitReceipt:
    permit_id: str
    provider_key: str
    owner: str
    reserved_tokens: int
    lease_expires_at: datetime


class StalePermitError(RuntimeError):
    """物理请求的 permit 已释放或被过期回收"""


def _database_now(session: Session) -> datetime:
    return session.execute(select(func.clock_timestamp())).scalar_one()


def _safe_base_url(value: str) -> str:
    """预算行不保存 URL 内嵌凭据或查询参数"""
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError("供应方 base_url 无效")
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme, f"{host}{port}", parsed.path.rstrip("/"), "", ""))


class ProviderPermitRepository:
    """每次物理请求领取许可；用户并发及服务端 429 暂停在进程间共享"""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def configure(
        self, limits: ProviderLimits, *, replace_limits: bool = False, authoritative_concurrency: bool = False,
    ) -> str:
        """模型池请求使用当前并发配置；其他请求只收紧预算，重配不清空统计或暂停"""
        if limits.hard_max_in_flight <= 0:
            raise ValueError("hard_max_in_flight 必须大于零")
        safe_url = _safe_base_url(limits.base_url)
        with self.session_factory() as session, session.begin():
            statement = insert(ProviderBudget).values(
                provider_key=limits.provider_key,
                base_url=safe_url,
                model=limits.model,
                endpoint=limits.endpoint,
                hard_max_in_flight=limits.hard_max_in_flight,
                window_started_at=_database_now(session),
            )
            session.execute(statement.on_conflict_do_nothing(index_elements=[ProviderBudget.provider_key]))
            budget = session.get(ProviderBudget, limits.provider_key, with_for_update=True)
            assert budget is not None
            if replace_limits:
                budget.hard_max_in_flight = limits.hard_max_in_flight
            elif authoritative_concurrency:
                budget.hard_max_in_flight = limits.hard_max_in_flight
            else:
                budget.hard_max_in_flight = min(budget.hard_max_in_flight, limits.hard_max_in_flight)
        return limits.provider_key

    def acquire(
        self,
        *,
        provider_key: str,
        owner: str,
        reserved_tokens: int,
        work_id: str | None = None,
        lease_seconds: int = 180,
    ) -> PermitReceipt | None:
        if reserved_tokens < 0 or lease_seconds <= 0:
            raise ValueError("reserved_tokens 不能为负，lease_seconds 必须大于零")
        with self.session_factory() as session, session.begin():
            budget = session.get(ProviderBudget, provider_key, with_for_update=True)
            if budget is None:
                raise ValueError(f"供应方预算未配置: {provider_key}")
            now = _database_now(session)
            if budget.pause_until is not None and budget.pause_until > now:
                return None
            if now - budget.window_started_at >= timedelta(minutes=1):
                budget.window_started_at = now
                budget.requests_window = 0
                budget.tokens_window = 0
            active = session.execute(
                select(func.count()).select_from(ProviderPermitLease).where(
                    ProviderPermitLease.provider_key == provider_key,
                    ProviderPermitLease.state == "active",
                    ProviderPermitLease.lease_expires_at > now,
                )
            ).scalar_one()
            if active >= budget.hard_max_in_flight:
                return None
            permit_id = secrets.token_hex(32)
            expires_at = now + timedelta(seconds=lease_seconds)
            session.add(
                ProviderPermitLease(
                    permit_id=permit_id,
                    provider_key=provider_key,
                    owner=owner,
                    work_id=work_id,
                    reserved_tokens=reserved_tokens,
                    acquired_at=now,
                    lease_expires_at=expires_at,
                )
            )
            budget.requests_window += 1
            budget.tokens_window += reserved_tokens
            budget.updated_at = now
            return PermitReceipt(permit_id, provider_key, owner, reserved_tokens, expires_at)

    def renew(self, receipt: PermitReceipt, *, lease_seconds: int = 180) -> datetime:
        with self.session_factory() as session, session.begin():
            lease = session.get(ProviderPermitLease, receipt.permit_id, with_for_update=True)
            now = _database_now(session)
            if (
                lease is None or lease.state != "active" or lease.owner != receipt.owner
                or lease.lease_expires_at <= now
            ):
                raise StalePermitError(f"供应方 permit 已过期: {receipt.permit_id}")
            lease.lease_expires_at = now + timedelta(seconds=lease_seconds)
            return lease.lease_expires_at

    def release(
        self,
        receipt: PermitReceipt,
        *,
        status_code: int | None,
        actual_tokens: int | None = None,
        retry_after_seconds: float | None = None,
        latency_ms: float | None = None,
    ) -> None:
        """归还实际请求容量；429 遵守服务端等待但不改用户配置的并发"""
        with self.session_factory() as session, session.begin():
            budget = session.get(ProviderBudget, receipt.provider_key, with_for_update=True)
            lease = session.get(ProviderPermitLease, receipt.permit_id, with_for_update=True)
            if budget is None or lease is None or lease.state != "active" or lease.owner != receipt.owner:
                raise StalePermitError(f"供应方 permit 已失效: {receipt.permit_id}")
            now = _database_now(session)
            lease.state = "released"
            lease.released_at = now
            if actual_tokens is not None and lease.acquired_at >= budget.window_started_at:
                if actual_tokens < 0:
                    raise ValueError("actual_tokens 不能为负")
                budget.tokens_window = max(0, budget.tokens_window + actual_tokens - lease.reserved_tokens)
            if status_code == 429:
                requested_pause = now + timedelta(seconds=max(0.0, retry_after_seconds or 1.0))
                budget.pause_until = max(budget.pause_until or requested_pause, requested_pause)
            if latency_ms is not None:
                budget.ewma_latency_ms = (
                    latency_ms if budget.ewma_latency_ms is None
                    else 0.2 * latency_ms + 0.8 * budget.ewma_latency_ms
                )
            failed = 0.0 if status_code is not None and 200 <= status_code < 400 else 1.0
            budget.ewma_error_rate = (
                failed if budget.ewma_error_rate is None
                else 0.2 * failed + 0.8 * budget.ewma_error_rate
            )
            budget.updated_at = now
