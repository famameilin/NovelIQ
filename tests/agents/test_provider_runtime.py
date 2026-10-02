"""物理模型调用是否真正经过跨进程 permit"""

from __future__ import annotations

import asyncio
import threading

import pytest
from langchain_core.messages import AIMessageChunk

from src.agents.provider_runtime import ProviderRequestScope, _reserve_tokens, provider_request_scope
from src.agents.stream import run_model_call
from src.storage.db import get_session_factory
from src.storage.models import ProviderBudget, ProviderPermitLease
from src.storage.repositories.provider_permits import ProviderLimits, ProviderPermitRepository


class _FakeModel:
    base_url = "https://provider.example/v1"
    model_name = "model-c"
    # 2026-10-02 删除流式输出设置后 run_model_call 固定走 astream，测试模型同步改为流式
    streaming = True
    max_completion_tokens = 128

    async def astream(self, _messages):
        yield AIMessageChunk(
            content="完成",
            usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        )


def test_embedding_reserves_input_without_chat_output_budget() -> None:
    assert _reserve_tokens(["中文"], _FakeModel(), endpoint="embeddings") == 6
    assert _reserve_tokens(["中文"], _FakeModel()) == 134


class _RateLimitError(Exception):
    status_code = 429

    def __init__(self) -> None:
        super().__init__("limited")
        self.response = type("Response", (), {"headers": {"Retry-After": "30"}})()


class _LimitedModel(_FakeModel):
    model_name = "model-d"

    async def astream(self, _messages):
        raise _RateLimitError()
        yield AIMessageChunk(content="不可达")


class _SlowModel(_FakeModel):
    model_name = "slow-model"

    async def astream(self, _messages):
        await asyncio.sleep(5)
        yield AIMessageChunk(content="不会返回")


@pytest.mark.asyncio
async def test_model_request_consumes_and_releases_provider_permit() -> None:
    repository = ProviderPermitRepository(get_session_factory())
    scope = ProviderRequestScope(repository, owner="worker-1", work_id="work-1", hard_max_in_flight=2)
    with provider_request_scope(scope):
        response = await run_model_call(_FakeModel(), [], None, require_tool_call=False)
    assert response.content == "完成"

    key = ProviderLimits(
        base_url=_FakeModel.base_url, model=_FakeModel.model_name,
        endpoint="chat_completions", hard_max_in_flight=2,
    ).provider_key
    with get_session_factory()() as session:
        budget = session.get(ProviderBudget, key)
        leases = session.query(ProviderPermitLease).filter_by(provider_key=key).all()
        assert budget is not None
        assert budget.requests_window == 1
        assert budget.tokens_window == 12
        assert len(leases) == 1 and leases[0].state == "released"


@pytest.mark.asyncio
async def test_annotation_and_diagnosis_share_pool_model_concurrency(monkeypatch) -> None:
    from src.config import settings
    from src.config.schemas.model import WeightedModelSettings

    repository = ProviderPermitRepository(get_session_factory())
    monkeypatch.setattr(settings.models, "model_pool", [
        WeightedModelSettings(_FakeModel.model_name, _FakeModel.base_url, "test-key", max_in_flight=1),
    ])
    active = 0
    peak = 0

    class MeasuredModel(_FakeModel):
        async def astream(self, messages):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.1)
            active -= 1
            async for chunk in super().astream(messages):
                yield chunk

    async def request(owner: str) -> None:
        scope = ProviderRequestScope(repository, owner=owner, work_id=None, hard_max_in_flight=10,
                                     model_pool_managed=True)
        with provider_request_scope(scope):
            await run_model_call(MeasuredModel(), [], None, require_tool_call=False)

    await asyncio.gather(request("annotation"), request("diagnosis"))
    assert peak == 1
    key = ProviderLimits(_FakeModel.base_url, _FakeModel.model_name, "chat_completions", 1).provider_key
    with get_session_factory()() as session:
        budget = session.get(ProviderBudget, key)
        assert budget.hard_max_in_flight == 1


@pytest.mark.asyncio
async def test_pool_request_uses_updated_concurrency_not_old_work_limit(monkeypatch) -> None:
    from src.config import settings
    from src.config.schemas.model import WeightedModelSettings

    repository = ProviderPermitRepository(get_session_factory())
    monkeypatch.setattr(settings.models, "model_pool", [
        WeightedModelSettings(_FakeModel.model_name, _FakeModel.base_url, "test-key", max_in_flight=4),
    ])
    scope = ProviderRequestScope(repository, owner="changed-config", work_id=None, hard_max_in_flight=1,
                                 model_pool_managed=True)
    with provider_request_scope(scope):
        await run_model_call(_FakeModel(), [], None, require_tool_call=False)
    key = ProviderLimits(_FakeModel.base_url, _FakeModel.model_name, "chat_completions", 4).provider_key
    with get_session_factory()() as session:
        assert session.get(ProviderBudget, key).hard_max_in_flight == 4


@pytest.mark.asyncio
async def test_429_sets_shared_pause_before_request_returns() -> None:
    repository = ProviderPermitRepository(get_session_factory())
    scope = ProviderRequestScope(repository, owner="worker-1", work_id="work-2", hard_max_in_flight=4)
    with provider_request_scope(scope), pytest.raises(_RateLimitError):
        await run_model_call(_LimitedModel(), [], None, total_attempts=1)

    key = ProviderLimits(
        base_url=_LimitedModel.base_url, model=_LimitedModel.model_name,
        endpoint="chat_completions", hard_max_in_flight=4,
    ).provider_key
    with get_session_factory()() as session:
        budget = session.get(ProviderBudget, key)
        assert budget is not None
        assert budget.hard_max_in_flight == 4
        assert budget.pause_until is not None and budget.pause_until > budget.updated_at


@pytest.mark.asyncio
@pytest.mark.parametrize("cancellation_count", [1, 2])
async def test_cancel_during_permit_acquisition_does_not_leave_unused_capacity(
    monkeypatch, cancellation_count: int,
) -> None:
    repository = ProviderPermitRepository(get_session_factory())
    acquire = repository.acquire
    acquired = threading.Event()
    return_receipt = threading.Event()
    acquisition_finished = threading.Event()
    calls = 0
    work_id = f"cancel-acquisition:{cancellation_count}"

    def delayed_acquire(**kwargs):
        receipt = acquire(**kwargs)
        acquired.set()
        assert return_receipt.wait(timeout=5)
        acquisition_finished.set()
        return receipt

    class UncalledModel(_FakeModel):
        model_name = "cancel-acquisition"

        async def astream(self, messages):
            nonlocal calls
            calls += 1
            async for chunk in super().astream(messages):
                yield chunk

    monkeypatch.setattr(repository, "acquire", delayed_acquire)

    async def request() -> None:
        scope = ProviderRequestScope(repository, owner="cancel-acquisition", work_id=work_id,
                                     hard_max_in_flight=1)
        with provider_request_scope(scope):
            await run_model_call(UncalledModel(), [], None, total_attempts=1, require_tool_call=False)

    task = asyncio.create_task(request())
    try:
        assert await asyncio.to_thread(acquired.wait, 3)
        for _ in range(cancellation_count):
            task.cancel()
            await asyncio.sleep(0)
        return_receipt.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(acquisition_finished.wait, 3)
    finally:
        return_receipt.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert calls == 0
    with get_session_factory()() as session:
        leases = session.query(ProviderPermitLease).filter_by(work_id=work_id).all()
        assert len(leases) == 1 and leases[0].state == "released"


@pytest.mark.asyncio
@pytest.mark.parametrize("requests_per_chapter", [
    pytest.param([1] * 100, id="100-chapters-one-request-each"),
    pytest.param([3] * 33 + [1], id="34-chapters-mixed-one-and-three-requests"),
    pytest.param([1] * 25 + [2] * 15 + [3] * 15, id="55-chapters-mixed-one-two-and-three-requests"),
])
async def test_100_concurrency_counts_requests_not_chapter_tasks(
    monkeypatch, requests_per_chapter: list[int],
) -> None:
    """合成模型阻塞到许可占满；不发送收费请求，也不测量真实模型吞吐"""
    from src.config import settings
    from src.config.schemas.model import WeightedModelSettings

    repository = ProviderPermitRepository(get_session_factory())
    acquire = repository.acquire
    waiting_overflow = threading.Event()
    filled = asyncio.Event()
    release_requests = asyncio.Event()
    active_requests = 0
    peak_requests = 0
    per_chapter: dict[int, int] = {}
    model_name = f"request-count:{len(requests_per_chapter)}"

    def observe_acquire(**kwargs):
        receipt = acquire(**kwargs)
        if kwargs.get("work_id") == "overflow" and receipt is None:
            waiting_overflow.set()
        return receipt

    class MeasuredModel(_FakeModel):
        def __init__(self, chapter_id: int) -> None:
            self.chapter_id = chapter_id
            self.model_name = model_name

        async def astream(self, messages):
            nonlocal active_requests, peak_requests
            active_requests += 1
            peak_requests = max(peak_requests, active_requests)
            per_chapter[self.chapter_id] = per_chapter.get(self.chapter_id, 0) + 1
            if active_requests == 100:
                filled.set()
            try:
                await release_requests.wait()
                async for chunk in super().astream(messages):
                    yield chunk
            finally:
                active_requests -= 1

    monkeypatch.setattr(repository, "acquire", observe_acquire)
    monkeypatch.setattr(settings.models, "model_pool", [
        WeightedModelSettings(model_name, _FakeModel.base_url, "test-key", max_in_flight=100),
    ])

    async def chapter(chapter_id: int, request_count: int, *, work_id: str) -> None:
        scope = ProviderRequestScope(repository, owner=f"chapter:{chapter_id}", work_id=work_id,
                                     hard_max_in_flight=100, model_pool_managed=True)
        with provider_request_scope(scope):
            await asyncio.gather(*[
                run_model_call(MeasuredModel(chapter_id), [], None, total_attempts=1, require_tool_call=False)
                for _ in range(request_count)
            ])

    tasks = [asyncio.create_task(chapter(chapter_id, count, work_id=f"chapter:{chapter_id}"))
             for chapter_id, count in enumerate(requests_per_chapter)]
    try:
        await asyncio.wait_for(filled.wait(), timeout=8)
        assert active_requests == peak_requests == 100
        assert per_chapter == dict(enumerate(requests_per_chapter))
        tasks.append(asyncio.create_task(chapter(1000, 1, work_id="overflow")))
        assert await asyncio.to_thread(waiting_overflow.wait, 3)
        assert 1000 not in per_chapter
        release_requests.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=8)
    finally:
        release_requests.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    assert active_requests == 0 and peak_requests == 100
    assert per_chapter[1000] == 1
    key = ProviderLimits(_FakeModel.base_url, model_name, "chat_completions", 100).provider_key
    with get_session_factory()() as session:
        leases = session.query(ProviderPermitLease).filter_by(provider_key=key).all()
        assert len(leases) == 101 and all(lease.state == "released" for lease in leases)
