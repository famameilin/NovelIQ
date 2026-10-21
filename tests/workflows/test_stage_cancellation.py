"""阶段内取消工具：取消信号到达即中断长等待，不等被等待的操作自然结束"""

from __future__ import annotations

import asyncio

import pytest

from src.utils.cancellation import check_cancelled, finish_thread_step, run_cancellable


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


@pytest.mark.asyncio
async def test_repeated_cancel_waits_for_real_thread_unit_to_finish():
    import threading

    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release, saved = threading.Event(), threading.Event()

    def processing():
        loop.call_soon_threadsafe(started.set)
        assert release.wait(2)
        saved.set()
        return "saved"

    task = asyncio.create_task(finish_thread_step(asyncio.to_thread(processing)))
    try:
        await asyncio.wait_for(started.wait(), 2)
        for _ in range(2):
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done() and not saved.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert saved.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_thread_step_returns_actual_result_and_failure():
    assert await finish_thread_step(asyncio.to_thread(lambda: "done")) == "done"

    def failing():
        raise ValueError("真实处理失败")

    with pytest.raises(ValueError, match="真实处理失败"):
        await finish_thread_step(asyncio.to_thread(failing))
