"""SSE 三层端到端集成测试

覆盖 EventBus → event_manager → sse_endpoint 全链路（不 patch event_manager）：
- 事件透传：action → SSE event type、字段（stage/sub_stage/sub_percent/percent）完整
- seq 单调递增、缓冲回放与实时推送衔接
- 重连增量：last_seq 只回放之后的缓冲
- 终止类事件（task_complete）直接经 event_manager.send 下发
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.routes.sse import sse_endpoint
from src.sse.events import StreamEvent
from src.sse.manager import event_manager
from src.work.task_manager import TaskManager
from src.workflows.progress import AnalysisEventBus
from tests.support.storage_fixtures import fixture_id


@pytest.fixture(autouse=True)
def _allow_existing_task(monkeypatch):
    """任务存在性校验默认放行（e2e 使用虚构 task_id）"""

    monkeypatch.setattr("src.api.routes.sse._task_run_belongs_to_novel", lambda task_id, novel_id: True)
    monkeypatch.setattr(event_manager, "_outbox", None)


def _make_request(disconnect_after: int) -> MagicMock:
    """构造请求 mock：前 disconnect_after 次 is_disconnected 返回 False，之后恒 True"""
    request = MagicMock()
    request.is_disconnected = AsyncMock(side_effect=[False] * disconnect_after + [True])
    request.query_params = {}
    request.headers = {}
    return request


async def _drain(response, event_count: int) -> list[dict]:
    """迭代 EventSourceResponse 直到收满 event_count 条事件"""
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
        if len(chunks) >= event_count:
            break
    return chunks


@pytest.mark.asyncio
async def test_sse_e2e_eventbus_to_stream_full_chain() -> None:
    """EventBus.emit → 真实 event_manager → sse_endpoint 全链路事件透传"""
    event_manager.reset_for_testing()
    task_id = "e2e-chain"
    bus = AnalysisEventBus(task_id, TaskManager())

    await bus.emit(
        StreamEvent(
            action="output",
            sub_stage="event",
            stream_id="stream",
            invocation_id="agent",
            content="首段",
        )
    )
    response = await sse_endpoint(fixture_id(__name__, "novel-1"), task_id, _make_request(disconnect_after=3))
    await bus.emit(
        StreamEvent(
            action="output",
            sub_stage="event",
            stream_id="stream",
            invocation_id="agent",
            content="后段",
        )
    )
    await bus.emit_task_complete()
    chunks = await _drain(response, event_count=3)
    assert [chunk["event"] for chunk in chunks] == ["llm_output", "llm_output", "task_complete"]
    assert [chunk["id"] for chunk in chunks] == ["1", "2", "3"]
    data = json.loads(chunks[0]["data"])
    assert data["invocation_id"] == "agent" and data["agent_type"] == "event"
    assert not {"stage", "sub_stage", "percent", "sub_percent", "current", "total"} & data.keys()
    assert json.loads(chunks[2]["data"])["status"] == "completed"



@pytest.mark.asyncio
async def test_sse_e2e_tool_call_status_passthrough() -> None:
    """tool_call 事件 status 三态（started/success）贯穿链路"""
    event_manager.reset_for_testing()
    task_id = "e2e-tool"
    bus = AnalysisEventBus(task_id, TaskManager())

    await bus.emit(
        StreamEvent(
            action="tool_call",
            stage="annotate",
            sub_stage="annotation",
            stream_id="invocation-1",
            content="write_relations",
            status="started",
        )
    )
    await bus.emit(
        StreamEvent(
            action="tool_call",
            stage="annotate",
            sub_stage="annotation",
            stream_id="invocation-1",
            content="write_relations",
            status="success",
            message="写入 3 条关系",
        )
    )

    response = await sse_endpoint(fixture_id(__name__, "novel-1"), task_id, _make_request(disconnect_after=2))
    chunks = await _drain(response, event_count=2)

    assert [chunk["event"] for chunk in chunks] == ["tool_call", "tool_call"]
    data0 = json.loads(chunks[0]["data"])
    assert data0["status"] == "started"
    data1 = json.loads(chunks[1]["data"])
    assert data1["status"] == "success"
    assert data1["message"] == "写入 3 条关系"
    # 上下文补全：stage/sub_stage 来自总线
    assert data1["agent_type"] == "annotation"
    assert "stage" not in data1


@pytest.mark.asyncio
async def test_sse_e2e_reconnect_replays_incremental_only() -> None:
    """断线重连（last_seq）只回放之后的缓冲，已消费事件不重复"""
    event_manager.reset_for_testing()
    task_id = "e2e-reconnect"
    bus = AnalysisEventBus(task_id, TaskManager())

    await bus.emit(StreamEvent(action="output", stream_id="stream", content="第一轮"))
    await bus.emit(StreamEvent(action="output", stream_id="stream", content="第二轮"))

    # 第一次连接：last_seq=None → 回放全部（seq 1,2）
    response1 = await sse_endpoint(fixture_id(__name__, "novel-1"), task_id, _make_request(disconnect_after=2))
    chunks1 = await _drain(response1, event_count=2)
    assert [chunk["id"] for chunk in chunks1] == ["1", "2"]

    # 断开后新事件继续进缓冲（seq 3）
    await bus.emit(StreamEvent(action="output", stream_id="stream", content="第三轮"))

    # 第二次连接：last_seq=2 → 只回放 seq 3
    request2 = _make_request(disconnect_after=1)
    request2.query_params = {"last_seq": "2"}
    response2 = await sse_endpoint(fixture_id(__name__, "novel-1"), task_id, request2)
    chunks2 = await _drain(response2, event_count=1)
    assert [chunk["id"] for chunk in chunks2] == ["3"]
    data = json.loads(chunks2[0]["data"])
    assert data["content"] == "第三轮"


@pytest.mark.asyncio
async def test_sse_e2e_last_event_id_header_as_fallback() -> None:
    """浏览器原生重连的 Last-Event-ID 头作为 last_seq 兜底（sse.py 契约）"""
    event_manager.reset_for_testing()
    task_id = "e2e-header"
    bus = AnalysisEventBus(task_id, TaskManager())

    await bus.emit(StreamEvent(action="output", stream_id="stream", content="首段"))
    await bus.emit(StreamEvent(action="output", stream_id="stream", content="后段"))

    request = _make_request(disconnect_after=1)
    request.query_params = {}
    request.headers = {"last-event-id": "1"}
    response = await sse_endpoint(fixture_id(__name__, "novel-1"), task_id, request)
    chunks = await _drain(response, event_count=1)

    assert [chunk["id"] for chunk in chunks] == ["2"]
    assert json.loads(chunks[0]["data"])["content"] == "后段"
