"""
BaseModelClient 契约测试。

创建时间: 2026-04-23
任务: P0-base-model-client-safety-net
说明: 覆盖结构化解析、流式响应拼装、OpenAI SDK 异常映射，支撑后续拆分重构。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, BadRequestError
from pydantic import BaseModel

from src.config import TaskModelConfig
from src.models.local.base import BaseModelClient


class _ParsedPayload(BaseModel):
    """结构化解析测试模型。"""

    name: str
    score: int


class _AsyncChunkStream:
    """模拟 OpenAI SDK 返回的异步流。"""

    def __init__(self, chunks: list[object]) -> None:
        self._chunks = chunks

    def __aiter__(self):
        """返回异步迭代器自身。"""
        self._index = 0
        return self

    async def __anext__(self):
        """逐个返回模拟 chunk。"""
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk


def _make_response(content: object) -> SimpleNamespace:
    """构造结构化解析所需的响应对象。"""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _make_client(fake_sdk_client: object | None = None) -> BaseModelClient:
    """构造不访问真实网络的 BaseModelClient。"""
    default_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock()),
        )
    )
    return BaseModelClient(
        task_type="annotation",
        config=TaskModelConfig(base_url="http://127.0.0.1:8000/v1", model="test-model", api_key="test-key"),
        client=fake_sdk_client or default_client,
    )


def _make_stream_chunk(content: str | None = None, reasoning: str | None = None, usage: object | None = None):
    """构造流式 chunk。"""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=content,
                    reasoning_content=reasoning,
                )
            )
        ],
        usage=usage,
    )


def test_parse_structured_response_validates_json_payload() -> None:
    """结构化解析应把 JSON 响应校验成指定 Pydantic 模型。"""
    client = _make_client()

    parsed = client._parse_structured_response(_make_response('{"name": "白芷", "score": 7}'), _ParsedPayload)

    assert parsed == _ParsedPayload(name="白芷", score=7)


def test_parse_structured_response_rejects_invalid_payload() -> None:
    """结构化解析遇到非 JSON 文本时应明确抛出 ValueError。"""
    client = _make_client()

    with pytest.raises(ValueError, match="Failed to parse JSON"):
        client._parse_structured_response(_make_response("not-json"), _ParsedPayload)


@pytest.mark.asyncio
async def test_call_api_stream_builds_response_and_emits_buffers() -> None:
    """流式调用应合并输出/思考内容，并通过 emitter 发送残余缓冲。"""
    usage = SimpleNamespace(total_tokens=12)
    stream = _AsyncChunkStream(
        [
            _make_stream_chunk(content="你", reasoning="思"),
            _make_stream_chunk(content="好", reasoning="考", usage=usage),
        ]
    )
    fake_sdk_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=stream)),
        )
    )
    client = _make_client(fake_sdk_client)
    emitted = []

    async def _capture_event(event):
        """收集流式 emitter 事件。"""
        emitted.append(event)

    response = await client._call_api_stream({"model": "test-model", "messages": []}, emitter=_capture_event)

    assert response.choices[0].message.content == "你好"
    assert response.choices[0].message.reasoning_content == "思考"
    assert response.usage is usage
    output_text = "".join(event.content for event in emitted if event.action == "output")
    thinking_text = "".join(event.content for event in emitted if event.action == "thinking")
    assert output_text == "你好"
    assert thinking_text == "思考"


def test_api_timeout_error_maps_to_timeout_error() -> None:
    """OpenAI APITimeoutError 应映射为内置 TimeoutError。"""
    client = _make_client()
    request = httpx.Request("POST", "http://127.0.0.1/v1/chat/completions")

    with pytest.raises(TimeoutError, match="模型服务请求超时"):
        client._handle_api_timeout(APITimeoutError(request))


def test_api_connection_error_maps_to_connection_error() -> None:
    """OpenAI APIConnectionError 应映射为内置 ConnectionError。"""
    client = _make_client()
    request = httpx.Request("POST", "http://127.0.0.1/v1/chat/completions")

    with pytest.raises(ConnectionError, match="无法连接到模型服务"):
        client._handle_api_connection_error(APIConnectionError(request=request))


def test_bad_request_error_maps_to_runtime_error() -> None:
    """OpenAI BadRequestError 应映射为 RuntimeError。"""
    client = _make_client()
    request = httpx.Request("POST", "http://127.0.0.1/v1/chat/completions")
    response = httpx.Response(400, request=request, json={"error": "bad schema"})

    with pytest.raises(RuntimeError, match="模型服务错误"):
        client._handle_api_status_error(BadRequestError("bad schema", response=response, body=None))
