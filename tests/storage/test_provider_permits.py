"""模型供应方跨会话 permit 与限流反馈"""

from __future__ import annotations

from datetime import timedelta

from src.storage.db import get_session_factory
from src.storage.models import ProviderBudget
from src.storage.repositories.provider_permits import ProviderLimits, ProviderPermitRepository


def test_equivalent_url_forms_share_budget_without_persisting_url_credentials() -> None:
    first = ProviderLimits("https://PROVIDER.example/v1/", "canonical", "embeddings", 2)
    second = ProviderLimits("https://user:secret@provider.example/v1?key=secret", "canonical", "embeddings", 2)
    assert first.provider_key == second.provider_key
    permits = ProviderPermitRepository(get_session_factory())
    key = permits.configure(second)
    with get_session_factory()() as session:
        assert session.get(ProviderBudget, key).base_url == "https://provider.example/v1"


def test_provider_limit_blocks_second_request_and_429_pauses_all_workers() -> None:
    permits = ProviderPermitRepository(get_session_factory())
    key = permits.configure(
        ProviderLimits(
            base_url="https://provider.example/v1", model="model-a", endpoint="chat_completions",
            hard_max_in_flight=1,
        )
    )
    first = permits.acquire(provider_key=key, owner="worker-1", reserved_tokens=100)
    assert first is not None
    assert permits.acquire(provider_key=key, owner="worker-2", reserved_tokens=100) is None
    permits.release(first, status_code=429, actual_tokens=0, retry_after_seconds=30)
    assert permits.acquire(provider_key=key, owner="worker-2", reserved_tokens=100) is None

    with get_session_factory()() as session, session.begin():
        budget = session.get(ProviderBudget, key)
        assert budget is not None
        assert budget.hard_max_in_flight == 1
        budget.pause_until -= timedelta(minutes=1)
    second = permits.acquire(provider_key=key, owner="worker-2", reserved_tokens=100)
    assert second is not None
    permits.release(second, status_code=200, actual_tokens=80, latency_ms=250)


def test_llm_and_embedding_use_independent_budgets() -> None:
    permits = ProviderPermitRepository(get_session_factory())
    common = {"base_url": "https://provider.example/v1", "model": "model-b", "hard_max_in_flight": 1}
    llm_key = permits.configure(ProviderLimits(endpoint="chat_completions", **common))
    embedding_key = permits.configure(ProviderLimits(endpoint="embeddings", **common))
    llm = permits.acquire(provider_key=llm_key, owner="worker-1", reserved_tokens=100)
    embedding = permits.acquire(provider_key=embedding_key, owner="worker-1", reserved_tokens=100)
    assert llm is not None and embedding is not None
    assert llm.provider_key != embedding.provider_key


def test_other_run_cannot_relax_shared_provider_budget() -> None:
    permits = ProviderPermitRepository(get_session_factory())
    common = {"base_url": "https://provider.example/v1", "model": "shared", "endpoint": "chat_completions"}
    key = permits.configure(ProviderLimits(**common, hard_max_in_flight=2))
    assert permits.configure(ProviderLimits(**common, hard_max_in_flight=8)) == key
    with get_session_factory()() as session:
        budget = session.get(ProviderBudget, key)
        assert budget.hard_max_in_flight == 2
    receipt = permits.acquire(provider_key=key, owner="large-request", reserved_tokens=1000000)
    assert receipt is not None
    permits.release(receipt, status_code=200)


def test_shorter_429_cannot_shorten_shared_pause_and_operations_preserve_window() -> None:
    permits = ProviderPermitRepository(get_session_factory())
    common = {"base_url": "https://provider.example/v1", "model": "pause-test", "endpoint": "chat_completions"}
    key = permits.configure(ProviderLimits(**common, hard_max_in_flight=2))
    first = permits.acquire(provider_key=key, owner="worker-1", reserved_tokens=100)
    second = permits.acquire(provider_key=key, owner="worker-2", reserved_tokens=100)
    assert first is not None and second is not None
    permits.release(first, status_code=429, retry_after_seconds=120)
    with get_session_factory()() as session:
        pause_until = session.get(ProviderBudget, key).pause_until
    permits.release(second, status_code=429, retry_after_seconds=1)
    permits.configure(ProviderLimits(**common, hard_max_in_flight=8), replace_limits=True)
    with get_session_factory()() as session:
        budget = session.get(ProviderBudget, key)
        assert budget.pause_until == pause_until
        assert budget.hard_max_in_flight == 8
        assert budget.requests_window == 2 and budget.tokens_window == 200
    assert permits.acquire(provider_key=key, owner="worker-3", reserved_tokens=100) is None


def test_pool_concurrency_updates_apply_without_erasing_429_feedback() -> None:
    permits = ProviderPermitRepository(get_session_factory())
    common = {"base_url": "https://pool.example/v1", "model": "editable", "endpoint": "chat_completions"}
    key = permits.configure(ProviderLimits(**common, hard_max_in_flight=1), authoritative_concurrency=True)
    permits.configure(ProviderLimits(**common, hard_max_in_flight=4), authoritative_concurrency=True)
    receipts = [permits.acquire(provider_key=key, owner=f"worker-{index}", reserved_tokens=10) for index in range(4)]
    assert all(receipt is not None for receipt in receipts)
    assert permits.acquire(provider_key=key, owner="overflow", reserved_tokens=10) is None
    permits.release(receipts[0], status_code=429, retry_after_seconds=30)
    permits.configure(ProviderLimits(**common, hard_max_in_flight=8), authoritative_concurrency=True)
    with get_session_factory()() as session:
        budget = session.get(ProviderBudget, key)
        assert budget.hard_max_in_flight == 8
        assert budget.requests_window == 4 and budget.pause_until is not None
