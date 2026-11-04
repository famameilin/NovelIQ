"聚合缓存的并发合并与失效边界"

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from src.metrics.queries import aggregate


def test_simultaneous_requests_share_one_aggregate_computation(monkeypatch):
    started, release = Event(), Event()
    calls = []
    expected = object()

    def compute(*args):
        calls.append(args)
        started.set()
        assert release.wait(3)
        return expected

    monkeypatch.setattr(aggregate, "query_aggregate_metrics", compute)
    service = aggregate.MetricsQueryService()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.get_aggregate_result, "run", object())
        assert started.wait(2)
        second = pool.submit(service.get_aggregate_result, "run", object())
        release.set()
        assert first.result(timeout=3) is expected
        assert second.result(timeout=3) is expected
    assert len(calls) == 1


def test_invalidated_inflight_result_cannot_replace_new_cache(monkeypatch):
    started, release = Event(), Event()
    old, new = object(), object()
    calls = []

    def compute(*args):
        calls.append(args)
        if len(calls) == 1:
            started.set()
            assert release.wait(3)
            return old
        return new

    monkeypatch.setattr(aggregate, "query_aggregate_metrics", compute)
    service = aggregate.MetricsQueryService()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.get_aggregate_result, "run", object())
        assert started.wait(2)
        service.invalidate_cache("run")
        try:
            assert service.get_aggregate_result("run", object()) is new
        finally:
            release.set()
        assert pending.result(timeout=3) is old
    assert service.get_aggregate_result("run", object()) is new
    assert len(calls) == 2


def test_failed_aggregate_can_be_retried(monkeypatch):
    def fail(*args):
        raise ValueError("failed")

    monkeypatch.setattr(aggregate, "query_aggregate_metrics", fail)
    service = aggregate.MetricsQueryService()
    with pytest.raises(ValueError, match="failed"):
        service.get_aggregate_result("run", object())
    result = object()
    monkeypatch.setattr(aggregate, "query_aggregate_metrics", lambda *args: result)
    assert service.get_aggregate_result("run", object()) is result
