"""阶段内取消工具：取消信号到达即中断长等待，不等被等待的操作自然结束"""

from __future__ import annotations

import asyncio

import pytest

from src.utils.cancellation import check_cancelled, run_cancellable


def test_check_cancelled_allows_absent_and_false_signal() -> None:
    check_cancelled(None)
    check_cancelled(lambda: False)


def test_check_cancelled_raises_on_signal() -> None:
    with pytest.raises(asyncio.CancelledError):
        check_cancelled(lambda: True)


@pytest.mark.asyncio()
async def test_run_cancellable_returns_result_while_not_cancelled() -> None:
    async def work() -> str:
        await asyncio.sleep(0)
        return "done"

    assert await run_cancellable(work(), lambda: False, poll_seconds=0.001) == "done"


@pytest.mark.asyncio()
async def test_run_cancellable_interrupts_long_wait() -> None:
    interrupted = asyncio.Event()

    async def long_running() -> None:
        try:
            await asyncio.sleep(30)
        finally:
            interrupted.set()

    signal = {"cancelled": False}
    task = asyncio.create_task(run_cancellable(long_running(), lambda: signal["cancelled"], poll_seconds=0.01))
    await asyncio.sleep(0.05)
    signal["cancelled"] = True

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)

    assert interrupted.is_set()


@pytest.mark.asyncio()
async def test_run_cancellable_propagates_original_failure() -> None:
    async def failing() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await run_cancellable(failing(), lambda: False, poll_seconds=0.001)
