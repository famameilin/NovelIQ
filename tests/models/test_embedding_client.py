from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, BadRequestError, InternalServerError

from src.embedding import EmbeddingClient, EmbeddingServiceError


def _build_httpx_response(status_code: int) -> httpx.Response:
    """
    创建时间: 2026-04-28
    任务: fix-embedding-transient-502
    说明: OpenAI SDK 的 APIStatusError 需要携带真实 httpx.Response；
          测试里统一用这个 helper 生成最小可用响应，避免每个用例重复拼装 request/response。
    """
    request = httpx.Request("POST", "http://embedding.test/v1/embeddings")
    return httpx.Response(status_code=status_code, request=request)


@pytest.mark.asyncio
async def test_embed_texts_retries_retryable_502_and_recovers() -> None:
    """
    创建时间: 2026-04-28
    任务: fix-embedding-transient-502
    说明: 瞬时 502 属于 provider/gateway 常见抖动；batch embedding 应有限重试，而不是首次失败就终止整条 preprocess。
    """
    client = EmbeddingClient(
        base_url="http://localhost:9999/v1",
        model="test-embedding",
        api_key="test-key",
        timeout_s=1.0,
    )
    success_response = SimpleNamespace(
        data=[
            SimpleNamespace(index=0, embedding=[0.1, 0.2]),
            SimpleNamespace(index=1, embedding=[0.3, 0.4]),
        ],
        usage=None,
    )
    create_mock = AsyncMock(
        side_effect=[
            InternalServerError("bad gateway", response=_build_httpx_response(502), body=None),
            success_response,
        ]
    )
    client._client = SimpleNamespace(embeddings=SimpleNamespace(create=create_mock))

    with patch("src.embedding.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        embeddings = await client.embed_texts(["第一段", "第二段"])

    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert create_mock.await_count == 2
    sleep_mock.assert_awaited_once_with(0.5)


@pytest.mark.asyncio
async def test_embed_texts_does_not_retry_bad_request() -> None:
    """
    创建时间: 2026-04-28
    任务: fix-embedding-transient-502
    说明: 4xx 参数错误不属于瞬时故障，必须继续 fail fast，避免无意义重试把真实配置问题掩盖掉。
    """
    client = EmbeddingClient(
        base_url="http://localhost:9999/v1",
        model="test-embedding",
        api_key="test-key",
        timeout_s=1.0,
    )
    create_mock = AsyncMock(
        side_effect=BadRequestError("bad request", response=_build_httpx_response(400), body={"error": "invalid"})
    )
    client._client = SimpleNamespace(embeddings=SimpleNamespace(create=create_mock))

    with patch("src.embedding.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        with pytest.raises(EmbeddingServiceError):
            await client.embed_texts(["第一段"])

    assert create_mock.await_count == 1
    sleep_mock.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_embedding", "embed_texts"])
@pytest.mark.parametrize("timeout", [False, True])
async def test_embedding_transport_failure_has_dependency_and_builtin_types(method: str, timeout: bool) -> None:
    """2026-10-16 用户裁定连接级重试：连接及超时批内最多重试 3 次，耗尽仍保留原有异常语义"""
    from src.embedding import EMBEDDING_CONNECTION_MAX_RETRIES

    request = httpx.Request("POST", "http://embedding.test/v1/embeddings")
    failure = APITimeoutError(request=request) if timeout else APIConnectionError(request=request)
    client = EmbeddingClient(base_url="http://embedding.test/v1", model="test", api_key="test", timeout_s=1)
    with patch.object(client._client.embeddings, "create", new=AsyncMock(side_effect=failure)) as create:
        with patch("src.embedding.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            with pytest.raises(EmbeddingServiceError) as error:
                await getattr(client, method)(["正文"] if method == "embed_texts" else "正文")
    assert isinstance(error.value, TimeoutError if timeout else ConnectionError)
    assert error.value.__cause__ is failure
    assert create.await_count == 1 + EMBEDDING_CONNECTION_MAX_RETRIES
    assert sleep_mock.await_count == EMBEDDING_CONNECTION_MAX_RETRIES
    await client._client.close()


@pytest.mark.asyncio
async def test_exhausted_embedding_http_retries_are_dependency_failure() -> None:
    """传输层有限重试耗尽后明确失败，不转成模型可修正的参数错误"""
    client = EmbeddingClient(base_url="http://embedding.test/v1", model="test", api_key="test", timeout_s=1)
    failure = InternalServerError("service unavailable", response=_build_httpx_response(503), body=None)
    with (
        patch.object(client._client.embeddings, "create", new=AsyncMock(side_effect=failure)) as create,
        patch("src.embedding.asyncio.sleep", new=AsyncMock()),
        pytest.raises(EmbeddingServiceError),
    ):
        await client.get_embedding("正文")
    assert create.await_count == 3
    await client._client.close()
