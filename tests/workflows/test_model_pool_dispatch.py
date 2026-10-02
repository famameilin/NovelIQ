"""模型池容量位分发：并发位跟 agent 生命周期、容量感知选举、子代理按位拉起"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.agents.model_capacity import ModelCapacity
from src.config.model_assignment import select_annotation_model
from src.config.schemas.model import WeightedModelSettings
from src.workflows.annotate_helpers import block_codeact


def _pool() -> list[WeightedModelSettings]:
    return [
        WeightedModelSettings("a", "https://x.example/v1", "k-a", max_in_flight=1),
        WeightedModelSettings("b", "https://x.example/v1", "k-b", max_in_flight=2),
        WeightedModelSettings("z", "https://x.example/v1", "k-z", weight=0, max_in_flight=9),
    ]


# ---- 容量位账本 ----


async def test_slots_track_used_and_snapshot() -> None:
    capacity = ModelCapacity()
    slots = capacity.slots("m", 2)
    await slots.acquire()
    await slots.acquire()
    await slots.release()
    assert capacity.snapshot() == {"m": 1}


async def test_acquire_waits_until_release() -> None:
    slots = ModelCapacity().slots("m", 1)
    await slots.acquire()
    waiter = asyncio.ensure_future(slots.acquire())
    await asyncio.sleep(0.01)
    assert not waiter.done()
    await slots.release()
    await asyncio.wait_for(waiter, 1)
    assert slots.used == 1


async def test_slots_capacity_hot_update() -> None:
    capacity = ModelCapacity()
    slots = capacity.slots("m", 1)
    capacity.slots("m", 3)
    assert slots.capacity == 3


# ---- 容量感知选举 ----


def test_election_skips_saturated_model() -> None:
    pool = _pool()
    for key in ("k1", "k2", "k3"):
        # a 满位、z 零权重永不入选 → 只能选 b
        assert select_annotation_model(key, pool, in_flight={"a": 1}) == "b"


def test_election_returns_none_when_all_saturated() -> None:
    pool = _pool()
    for key in ("k1", "k2", "k3"):
        assert select_annotation_model(key, pool, in_flight={"a": 1, "b": 2}) is None


def test_election_still_raises_without_positive_weight() -> None:
    pool = [WeightedModelSettings("z", "https://x.example/v1", "k-z", weight=0)]
    with pytest.raises(ValueError):
        select_annotation_model("k", pool, in_flight={})


def test_election_without_in_flight_keeps_pure_weighted_behavior() -> None:
    pool = _pool()
    selected = {select_annotation_model(key, pool) for key in ("x", "y", "w")}
    assert selected <= {"a", "b"}


# ---- 子代理按容量位拉起 ----


def _chapter_kwargs() -> dict:
    return {
        "run_id": "run", "chapter_id": 1, "chapter_text": "正文",
        "paragraph_info": MagicMock(), "llm": MagicMock(), "sql_session_factory": MagicMock(),
        "query_service_factory": MagicMock(), "graph_state": None, "stream": None, "novel_id": "novel",
    }


async def test_subagents_serialize_under_capacity_one() -> None:
    slots = ModelCapacity().slots("m", 1)
    active = 0
    peak = 0
    roles: list[str] = []

    async def fake_run(**kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        roles.append(kwargs["role"])
        await asyncio.sleep(0.02)
        active -= 1

    async def fake_finish(**kwargs):
        return "chapter-result"

    with patch.object(block_codeact, "run_subagent_agent", side_effect=fake_run), patch.object(
        block_codeact, "_finish_chapter", new=fake_finish,
    ):
        result = await block_codeact.run_chapter_subagents(**_chapter_kwargs(), capacity=slots)
    assert result == "chapter-result"
    assert roles == list(block_codeact.SUBAGENT_ROLES)
    assert peak == 1
    assert slots.used == 0


async def test_subagents_run_concurrent_when_capacity_allows() -> None:
    slots = ModelCapacity().slots("m", 3)
    active = 0
    peak = 0
    all_started = asyncio.Event()

    async def fake_run(**kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 3:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=2)
        active -= 1

    async def fake_finish(**kwargs):
        return "chapter-result"

    with patch.object(block_codeact, "run_subagent_agent", side_effect=fake_run), patch.object(
        block_codeact, "_finish_chapter", new=fake_finish,
    ):
        await block_codeact.run_chapter_subagents(**_chapter_kwargs(), capacity=slots)
    assert peak == 3
    assert slots.used == 0


async def test_subagent_failure_releases_all_slots_and_skips_finish() -> None:
    slots = ModelCapacity().slots("m", 3)
    started: list[str] = []

    async def fake_run(**kwargs):
        started.append(kwargs["role"])
        if kwargs["role"] == block_codeact.SUBAGENT_ROLES[0]:
            await asyncio.sleep(0.01)
            raise RuntimeError("首个子代理失败")
        await asyncio.sleep(0.5)

    finish = MagicMock()
    with patch.object(block_codeact, "run_subagent_agent", side_effect=fake_run), patch.object(
        block_codeact, "_finish_chapter", new=finish,
    ), pytest.raises(RuntimeError):
        await block_codeact.run_chapter_subagents(**_chapter_kwargs(), capacity=slots)
    # 首个子代理失败后停止派发：第三个角色（evidence）从未启动，在飞的 event 被取消
    assert started == list(block_codeact.SUBAGENT_ROLES[:2])
    finish.assert_not_called()
    assert slots.used == 0
