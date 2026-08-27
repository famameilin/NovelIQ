"""SSE 三层端到端集成测试

覆盖 EventBus → event_manager → sse_endpoint 全链路（不 patch event_manager）：
- 事件透传：action → SSE event type、字段（stage/sub_stage/sub_percent/percent）完整
- seq 单调递增、缓冲回放与实时推送衔接
- 重连增量：last_seq 只回放之后的缓冲
- 终止类事件（task_complete）直接经 event_manager.send 下发

2026-08-13 创建，补齐此前三层各自单测（EventBus patch send / 路由 patch manager）之间的链路缺口。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.models.events import AnalysisEventBus, StreamEvent
from src.api.routes.sse import sse_endpoint
from src.api.services.event_manager import event_manager
from src.api.services.task_manager import TaskManager


@pytest.fixture(autouse=True)
def _allow_existing_task(monkeypatch):
    """2026-08-14 P2-11：任务存在性校验默认放行（e2e 使用虚构 task_id）"""

    monkeypatch.setattr("src.api.routes.sse._task_run_exists", lambda task_id: True)


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

    # 无连接时先 emit 两个事件（进缓冲）
    await bus.emit(StreamEvent(action="start", stage="preprocess", message="预处理开始", percent=0.0))
    await bus.emit(
        StreamEvent(
            action="progress",
            stage="preprocess",
            sub_stage="paragraph_embedding",
            current=5,
            total=10,
            sub_percent=50.0,
        )
    )

    response = await sse_endpoint(task_id, _make_request(disconnect_after=4))
    # 连接建立后（缓冲回放 2 条）再实时 emit 2 条
    await bus.emit(
        StreamEvent(
            action="output",
            stage="preprocess",
            stream_id="preprocess-output",
            content="流式正文片段",
        )
    )
    await bus.emit_task_complete()

    chunks = await _drain(response, event_count=4)

    assert [chunk["event"] for chunk in chunks] == [
        "stage_start",
        "stage_progress",
        "llm_output",
        "task_complete",
    ]
    assert [chunk["id"] for chunk in chunks] == ["1", "2", "3", "4"]

    data0 = json.loads(chunks[0]["data"])
    assert data0["stage"] == "preprocess"
    assert data0["message"] == "预处理开始"
    assert data0["percent"] == 0.0

    data1 = json.loads(chunks[1]["data"])
    # sub_stage/sub_percent 贯穿 EventBus → manager → SSE 路由
    assert data1["sub_stage"] == "paragraph_embedding"
    assert data1["sub_percent"] == 50.0
    assert data1["current"] == 5
    assert data1["total"] == 10
    # 全局 percent 由 current/total 按 preprocess 区间 0-10 计算
    assert data1["percent"] == pytest.approx(5.0)

    data2 = json.loads(chunks[2]["data"])
    assert data2["content"] == "流式正文片段"
    assert data2["stream_id"] == "preprocess-output"

    data3 = json.loads(chunks[3]["data"])
    assert data3["stage"] == "completed"
    assert data3["percent"] == 100.0


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
            sub_stage="chapter_agent",
            stream_id="chapter-agent-1",
            content="write_relations",
            status="started",
        )
    )
    await bus.emit(
        StreamEvent(
            action="tool_call",
            stage="annotate",
            sub_stage="chapter_agent",
            stream_id="chapter-agent-1",
            content="write_relations",
            status="success",
            message="写入 3 条关系",
        )
    )

    response = await sse_endpoint(task_id, _make_request(disconnect_after=2))
    chunks = await _drain(response, event_count=2)

    assert [chunk["event"] for chunk in chunks] == ["tool_call", "tool_call"]
    data0 = json.loads(chunks[0]["data"])
    assert data0["status"] == "started"
    data1 = json.loads(chunks[1]["data"])
    assert data1["status"] == "success"
    assert data1["message"] == "写入 3 条关系"
    # 上下文补全：stage/sub_stage 来自总线
    assert data1["stage"] == "annotate"
    assert data1["sub_stage"] == "chapter_agent"


@pytest.mark.asyncio
async def test_sse_e2e_reconnect_replays_incremental_only() -> None:
    """断线重连（last_seq）只回放之后的缓冲，已消费事件不重复"""
    event_manager.reset_for_testing()
    task_id = "e2e-reconnect"
    bus = AnalysisEventBus(task_id, TaskManager())

    await bus.emit(StreamEvent(action="start", stage="preprocess", message="第一轮"))
    await bus.emit(StreamEvent(action="progress", stage="preprocess", current=1, total=10, sub_percent=10.0))

    # 第一次连接：last_seq=None → 回放全部（seq 1,2）
    response1 = await sse_endpoint(task_id, _make_request(disconnect_after=2))
    chunks1 = await _drain(response1, event_count=2)
    assert [chunk["id"] for chunk in chunks1] == ["1", "2"]

    # 断开后新事件继续进缓冲（seq 3）
    await bus.emit(StreamEvent(action="progress", stage="preprocess", current=2, total=10, sub_percent=20.0))

    # 第二次连接：last_seq=2 → 只回放 seq 3
    request2 = _make_request(disconnect_after=1)
    request2.query_params = {"last_seq": "2"}
    response2 = await sse_endpoint(task_id, request2)
    chunks2 = await _drain(response2, event_count=1)
    assert [chunk["id"] for chunk in chunks2] == ["3"]
    data = json.loads(chunks2[0]["data"])
    assert data["current"] == 2
    assert data["sub_percent"] == 20.0


@pytest.mark.asyncio
async def test_sse_e2e_last_event_id_header_as_fallback() -> None:
    """浏览器原生重连的 Last-Event-ID 头作为 last_seq 兜底（sse.py 契约）"""
    event_manager.reset_for_testing()
    task_id = "e2e-header"
    bus = AnalysisEventBus(task_id, TaskManager())

    await bus.emit(StreamEvent(action="start", stage="aggregate", message="聚合开始"))
    await bus.emit(StreamEvent(action="complete", stage="aggregate", percent=90.0))

    request = _make_request(disconnect_after=1)
    request.query_params = {}
    request.headers = {"last-event-id": "1"}
    response = await sse_endpoint(task_id, request)
    chunks = await _drain(response, event_count=1)

    assert [chunk["id"] for chunk in chunks] == ["2"]
    assert json.loads(chunks[0]["data"])["stage"] == "aggregate"
