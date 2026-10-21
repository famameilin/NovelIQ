"""阶段事件使用普通 Storage 入口，持久化事务由 Storage 完整操作结束"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.sse.events import StreamEvent
from src.workflows.analysis.stage_orchestrator import StageOrchestratorMixin


@pytest.mark.asyncio
async def test_stage_emitter_preserves_delivery_failure_without_database_controls():
    failure = RuntimeError("event delivery failed")

    async def emit(event):
        raise failure

    emitter = StageOrchestratorMixin._make_stage_emitter(SimpleNamespace(emit=emit), "diagnose")
    with pytest.raises(RuntimeError) as caught:
        await emitter(StreamEvent(action="progress"))
    assert caught.value is failure


@pytest.mark.asyncio
async def test_stage_emitter_fills_context_and_preserves_existing_stage():
    received = []

    async def emit(event):
        received.append(event)

    emitter = StageOrchestratorMixin._make_stage_emitter(SimpleNamespace(emit=emit), "aggregate")
    missing_stage = StreamEvent(action="complete", current=1, total=1, percent=90.0)
    explicit_stage = StreamEvent(action="progress", stage="diagnose", percent=95.0)
    await emitter(missing_stage)
    await emitter(explicit_stage)
    assert received[0].stage == "aggregate"
    assert received[0].percent == 90.0
    assert received[1] is explicit_stage
    assert missing_stage.stage == ""
