"""只验证 ID 算法，不使用数据库或运行模型"""

from concurrent.futures import ThreadPoolExecutor
from uuid import RFC_4122, UUID

from src.storage import ids


def test_uuid7_version_timestamp_and_order(monkeypatch):
    monkeypatch.setattr(ids, "_last_ms", -1)
    monkeypatch.setattr(ids.time, "time_ns", lambda: 1_800_000_000_123_000_000)
    values = [ids.new_id() for _ in range(1000)]
    assert values == sorted(set(values))
    for value in values:
        parsed = UUID(value)
        assert parsed.version == 7
        assert parsed.variant == RFC_4122
        assert parsed.int >> 80 == 1_800_000_000_123


def test_clock_rollback_does_not_reuse_or_decrease_ids(monkeypatch):
    monkeypatch.setattr(ids, "_last_ms", -1)
    times = iter([2_000_000, 1_000_000, 3_000_000])
    monkeypatch.setattr(ids.time, "time_ns", lambda: next(times))
    values = [ids.new_id() for _ in range(3)]
    assert values == sorted(set(values))
    assert [UUID(value).int >> 80 for value in values] == [2, 2, 3]


def test_counter_overflow_advances_timestamp(monkeypatch):
    monkeypatch.setattr(ids, "_last_ms", 100)
    monkeypatch.setattr(ids, "_random", (1 << 74) - 1)
    monkeypatch.setattr(ids.time, "time_ns", lambda: 100_000_000)
    assert UUID(ids.new_id()).int >> 80 == 101


def test_concurrent_callers_do_not_reuse_ids():
    with ThreadPoolExecutor(max_workers=4) as workers:
        values = list(workers.map(lambda _: ids.new_id(), range(4000)))
    assert len(set(values)) == len(values)
