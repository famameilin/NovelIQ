"""
创建时间: 2025-03-11
创建者: TraeAI
任务: Embedding客户端

修改时间: 2026-03-11
修改者: TraeAI
修改内容: 将云端embedding相关日志提升为info等级，添加请求和返回内容的控制台打印

修改时间: 2026-03-13
修改者: TraeAI
修改内容: 提取 _log 方法统一处理日志记录，减少 get_embedding 方法中的重复代码

修改时间: 2026-03-16
修改者: TraeAI
修改内容: 将 OpenAI SDK 替换为 LiteLLM，移除 _client 对象，改用 litellm.embedding() 函数调用

修改时间: 2026-03-21
修改者: TraeAI
任务: migrate-litellm-to-openai-sdk
修改内容: 使用 OpenAI SDK 替代 LiteLLM

修改时间: 2026-03-22
修改者: TraeAI
任务: code-quality-review
修改内容:
1. 移除 API 密钥硬编码默认值，改为从环境变量读取
2. 修复云端 API 错误降级为 info 级别的问题，统一使用 error 级别

修改时间: 2026-04-20
修改者: Codex
任务: 清理无效模型配置项
修改内容: 删除未生效的 max_retries 参数和缓存字段，避免 EmbeddingClient 暴露伪配置

修改时间: 2026-04-20
修改者: Codex (GPT-5)
任务: batch-embedding-requests
修改内容: 将语义分块 embedding 从逐条请求改为批量请求，降低本地 embedding 服务的请求往返开销

修改时间: 2026-04-22
修改者: Codex
任务: fix-embedding-token-callback-signature
修改内容: 将 EmbeddingClient 的 token callback 签名对齐到统一契约，补上 model 参数

修改时间: 2026-04-24
修改者: Codex
任务: semantic-chunking-embedding-sse-progress
修改内容: 为批量 embedding 增加可选批次进度回调，供语义分块/预处理把批量请求进度映射到 SSE。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable

import numpy as np
from loguru import logger
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, BadRequestError

from src.config import settings

TokenUsageCallback = Callable[[str, str, str, str, int, int, int | None, int | None], None]
BatchProgressCallback = Callable[[int, int, int], Awaitable[None] | None]
RETRYABLE_EMBEDDING_STATUS_CODES = {429, 500, 502, 503, 504}
EMBEDDING_MAX_RETRIES = 2
EMBEDDING_RETRY_BASE_DELAY_S = 0.5


class EmbeddingClient:
    """
    Embedding客户端

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: migrate-litellm-to-openai-sdk
    修改内容: 使用 OpenAI SDK 替代 LiteLLM
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_s: float | None = None,
        embedding_dim: int | None = None,
        token_usage_callback: TokenUsageCallback | None = None,
        novel_id: str | None = None,
    ) -> None:
        if base_url is None or model is None:
            semantic_config = settings.models.semantic_chunking
            self._base_url = base_url or semantic_config.base_url
            self._model = model or semantic_config.model
            self._api_key = api_key or semantic_config.api_key or os.environ.get("OPENAI_API_KEY", "")
            if not self._api_key:
                raise ValueError(
                    "API key is required: provide api_key parameter or set OPENAI_API_KEY environment variable"
                )
            self._timeout_s = timeout_s if timeout_s is not None else semantic_config.timeout_s
            self._embedding_dim = embedding_dim if embedding_dim is not None else semantic_config.embedding_dim
            self._batch_size = semantic_config.batch_size
        else:
            self._base_url = base_url
            self._model = model
            self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
            if not self._api_key:
                raise ValueError(
                    "API key is required: provide api_key parameter or set OPENAI_API_KEY environment variable"
                )
            self._timeout_s = timeout_s
            self._embedding_dim = (
                embedding_dim if embedding_dim is not None else settings.models.semantic_chunking.embedding_dim
            )
            self._batch_size = settings.models.semantic_chunking.batch_size

        if self._embedding_dim <= 0:
            raise ValueError(f"embedding dimension must be positive, got {self._embedding_dim}")
        if self._batch_size <= 0:
            raise ValueError(f"embedding batch size must be positive, got {self._batch_size}")

        self._token_usage_callback = token_usage_callback
        self._novel_id = novel_id
        self._is_cloud = self._check_is_cloud()

        self._client = AsyncOpenAI(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout=self._timeout_s,
        )

        if self._is_cloud:
            logger.info(
                "[云端模型] Embedding客户端初始化: base_url={} model={}",
                self._base_url,
                self._model,
            )
        else:
            logger.debug(
                "embedding client initialized: base_url={} model={}",
                self._base_url,
                self._model,
            )

    def _check_is_cloud(self) -> bool:
        """判断是否为云端API"""
        base_url = self._base_url or ""
        return not base_url.startswith("http://127.0.0.1") and not base_url.startswith("http://localhost")

    def _log(
        self,
        level: str,
        cloud_msg: str,
        local_msg: str,
        *args,
    ) -> None:
        """
        创建时间: 2026-03-13
        创建者: TraeAI
        任务: 审查并优化 embedding.py

        统一处理日志记录，根据是否为云端API选择不同的日志级别和消息格式。

        Args:
            level: 日志级别 ("info", "debug", "error", "warning")
            cloud_msg: 云端API使用的消息模板（带 "[云端模型]" 前缀）
            local_msg: 本地API使用的消息模板
            *args: 日志消息的参数

        修改时间: 2026-03-14
        修改者: TraeAI
        修改内容: 修复本地API时INFO日志未降级为DEBUG的问题
        """
        if self._is_cloud:
            msg = f"[云端模型] {cloud_msg}"
            log_func = getattr(logger, level, logger.info)
        else:
            msg = local_msg
            if level == "info":
                log_func = logger.debug
            else:
                log_func = getattr(logger, level, logger.debug)
        log_func(msg, *args)

    def _is_retryable_embedding_status_error(self, error: APIStatusError) -> bool:
        """
        创建时间: 2026-04-28
        创建者: Codex
        任务: fix-embedding-transient-502
        新建原因: embedding 服务偶发 429/5xx 属于典型瞬时错误；
        这里统一收口重试判定，避免 batch/single 两条链路各自散落一套条件。
        """
        status_code = getattr(error, "status_code", None)
        if not isinstance(status_code, int):
            return False
        return status_code in RETRYABLE_EMBEDDING_STATUS_CODES

    async def _create_embeddings_with_retry(self, text_input: str | list[str]):
        """
        创建时间: 2026-04-28
        创建者: Codex
        任务: fix-embedding-transient-502
        新建原因: 上游 embedding provider 的瞬时 429/5xx 不应立即把整条分析链打死；
        这里对可恢复状态做有限次退避重试，其余错误仍保持 fail fast。
        """
        for attempt in range(1, EMBEDDING_MAX_RETRIES + 2):
            try:
                return await self._client.embeddings.create(
                    model=self._model,
                    input=text_input,
                    encoding_format="float",
                )
            except BadRequestError as e:
                self._log(
                    "error",
                    "embedding API错误: status={} base_url={} error={}",
                    "embedding api status error: status={} base_url={} error={}",
                    e.status_code if hasattr(e, "status_code") else "unknown",
                    self._base_url,
                    str(e),
                )
                raise RuntimeError(f"embedding 服务错误: {e}") from e
            except APIStatusError as e:
                status_code = getattr(e, "status_code", "unknown")
                should_retry = self._is_retryable_embedding_status_error(e) and attempt <= EMBEDDING_MAX_RETRIES
                self._log(
                    "warning" if should_retry else "error",
                    "embedding API状态错误: status={} attempt={}/{} base_url={} retry={} error={}",
                    "embedding api status error: status={} attempt={}/{} base_url={} retry={} error={}",
                    status_code,
                    attempt,
                    EMBEDDING_MAX_RETRIES + 1,
                    self._base_url,
                    should_retry,
                    str(e),
                )
                if not should_retry:
                    raise RuntimeError(f"embedding 服务错误: {e}") from e
                await asyncio.sleep(EMBEDDING_RETRY_BASE_DELAY_S * attempt)

    async def get_embedding(self, text: str, chunk_id: int | None = None) -> list[float]:
        """
        获取文本的embedding向量

        修改时间: 2026-03-13
        修改者: TraeAI
        修改内容: 使用 _log 方法统一处理日志记录，减少重复代码

        修改时间: 2026-03-21
        修改者: TraeAI
        任务: migrate-litellm-to-openai-sdk
        修改内容: 使用 OpenAI SDK 替代 LiteLLM

        修改时间: 2026-04-09
        修改者: TraeAI
        任务: 重构 EmbeddingClient 使用 AsyncOpenAI
        修改内容: 将 get_embedding 改为异步方法，使用 await 调用 embeddings.create

        修改时间: 2026-04-22
        修改者: Codex
        任务: clarify-token-accounting-semantics
        修改内容: 补充 token 口径注释，说明 embedding 在 provider 可稳定返回 usage 时优先记录实报值
        """
        if not self._model:
            raise ValueError("embedding model is required")
        if not text or not text.strip():
            logger.warning("empty text provided for embedding")
            return []

        self._log(
            "info",
            "get_embedding 开始: model={} text_len={} chunk_id={}",
            "get_embedding start model={} text_len={}",
            self._model,
            len(text),
            chunk_id,
        )
        try:
            response = await self._create_embeddings_with_retry(text)

            embedding = response.data[0].embedding
            self._validate_embedding_dimension(embedding)

            if self._token_usage_callback and response.usage:
                # 中文注释：embedding 接口通常能稳定返回 provider usage，
                # 这里优先保留实报值；汇总层对外仍标 estimated，是因为整条分析链路整体只承诺近似统计，
                # 而不是要求每一笔都必须退化成本地估算。
                self._token_usage_callback(
                    self._novel_id or "unknown",
                    "embedding",
                    "local",
                    self._model or "unknown",
                    response.usage.prompt_tokens,
                    response.usage.total_tokens,
                    None,
                    chunk_id,
                )

            self._log(
                "info",
                "get_embedding 完成: dim={} prompt_tokens={} total_tokens={}",
                "get_embedding complete dim={}",
                len(embedding),
                response.usage.prompt_tokens if response.usage else 0,
                response.usage.total_tokens if response.usage else 0,
            )
            return embedding
        except APIConnectionError as e:
            self._log(
                "error",
                "get_embedding 连接错误: base_url={} error={}",
                "connection error to embedding service: base_url={} error={}",
                self._base_url,
                str(e),
            )
            raise ConnectionError(f"无法连接到 embedding 服务 ({self._base_url})，请检查服务是否启动") from e
        except APITimeoutError as e:
            self._log(
                "error",
                "get_embedding 超时错误: base_url={} error={}",
                "timeout error: base_url={} error={}",
                self._base_url,
                str(e),
            )
            raise TimeoutError("embedding 服务请求超时，请检查服务响应") from e
        except Exception as e:
            self._log(
                "error",
                "get_embedding 未知错误: {}",
                "get_embedding unexpected error: {}",
                str(e),
            )
            raise

    async def detect_embedding_dimension(self, probe_text: str = "dimension probe") -> int:
        if not self._model:
            raise ValueError("embedding model is required")

        response = await self._create_embeddings_with_retry(probe_text)
        embedding = response.data[0].embedding
        return len(embedding)

    def _validate_embedding_dimension(self, embedding: list[float]) -> None:
        actual_dim = len(embedding)
        if actual_dim != self._embedding_dim:
            raise ValueError(
                f"embedding dimension mismatch: expected {self._embedding_dim}, got {actual_dim} (model={self._model})"
            )

    async def embed_texts(
        self,
        texts: list[str],
        *,
        progress_callback: BatchProgressCallback | None = None,
    ) -> list[list[float]]:
        """
        批量获取文本的embedding向量

        创建时间: 2026-03-18
        创建者: TraeAI
        任务: 支持语义分块的批量embedding

        修改时间: 2026-04-09
        修改者: TraeAI
        任务: 重构 EmbeddingClient 使用 AsyncOpenAI
        修改内容: 将 embed_texts 改为异步方法

        修改时间: 2026-04-20
        修改者: Codex (GPT-5)
        任务: batch-embedding-requests
        修改内容: 改为按配置批量请求 embedding API，默认每批 8 条，减少语义分块时的连续单条请求开销

        修改时间: 2026-04-22
        修改者: Codex
        任务: clarify-token-accounting-semantics
        修改内容: 补充批量 embedding 记账注释，明确 provider usage 仍可直接复用

        修改时间: 2026-04-24
        修改者: Codex
        任务: semantic-chunking-embedding-sse-progress
        修改内容: 支持在每个 batch 完成后回调进度，避免上层只能在整批 paragraphs 全部完成后才更新 UI。

        Args:
            texts: 文本列表

        Returns:
            embedding向量列表
        """
        if not self._model:
            raise ValueError("embedding model is required")
        if not texts:
            return []

        embeddings: list[list[float]] = [[] for _ in texts]
        valid_items = [(idx, text) for idx, text in enumerate(texts) if text and text.strip()]
        total_batches = (len(valid_items) + self._batch_size - 1) // self._batch_size if valid_items else 0

        for batch_index, batch_start in enumerate(range(0, len(valid_items), self._batch_size), start=1):
            batch_items = valid_items[batch_start : batch_start + self._batch_size]
            batch_texts = [text for _, text in batch_items]

            self._log(
                "info",
                "embed_texts 批处理开始: model={} batch_size={} batch_start={}",
                "embed_texts batch start model={} batch_size={} batch_start={}",
                self._model,
                len(batch_texts),
                batch_start,
            )

            try:
                response = await self._create_embeddings_with_retry(batch_texts)
            except APIConnectionError as e:
                self._log(
                    "error",
                    "embed_texts 连接错误: base_url={} error={}",
                    "embed_texts connection error: base_url={} error={}",
                    self._base_url,
                    str(e),
                )
                raise ConnectionError(f"无法连接到 embedding 服务 ({self._base_url})，请检查服务是否启动") from e
            except APITimeoutError as e:
                self._log(
                    "error",
                    "embed_texts 超时错误: base_url={} error={}",
                    "embed_texts timeout error: base_url={} error={}",
                    self._base_url,
                    str(e),
                )
                raise TimeoutError("embedding 服务请求超时，请检查服务响应") from e
            except Exception as e:
                self._log(
                    "error",
                    "embed_texts 未知错误: {}",
                    "embed_texts unexpected error: {}",
                    str(e),
                )
                raise

            response_items = sorted(response.data, key=lambda item: getattr(item, "index", 0))
            if len(response_items) != len(batch_items):
                raise RuntimeError(
                    f"embedding batch result count mismatch: expected {len(batch_items)}, got {len(response_items)}"
                )

            # 中文注释：批量接口返回后仍按 index 回填到原始位置，避免上层语义分块逻辑感知到请求模式变化。
            for (original_idx, _), item in zip(batch_items, response_items, strict=True):
                embedding = item.embedding
                self._validate_embedding_dimension(embedding)
                embeddings[original_idx] = embedding

            if self._token_usage_callback and response.usage:
                # 中文注释：批量 embedding 与单条 embedding 口径一致，
                # provider 已返回 usage 时直接记实报，避免额外估算把更好的原始数据抹平。
                self._token_usage_callback(
                    self._novel_id or "unknown",
                    "embedding",
                    "local",
                    self._model or "unknown",
                    response.usage.prompt_tokens,
                    response.usage.total_tokens,
                    None,
                    None,
                )

            self._log(
                "info",
                "embed_texts 批处理完成: batch_size={} prompt_tokens={} total_tokens={}",
                "embed_texts batch complete batch_size={} prompt_tokens={} total_tokens={}",
                len(batch_texts),
                response.usage.prompt_tokens if response.usage else 0,
                response.usage.total_tokens if response.usage else 0,
            )
            if progress_callback is not None:
                progress_result = progress_callback(batch_index, total_batches, len(valid_items))
                if progress_result is not None:
                    await progress_result

        for text in texts:
            if text and text.strip():
                continue
            logger.warning("empty text provided for embedding")

        return embeddings

    @staticmethod
    def compute_similarity(vec1: list[float], vec2: list[float]) -> float:
        if not vec1 or not vec2:
            logger.warning("empty vector provided for similarity computation")
            return 0.0
        if len(vec1) != len(vec2):
            logger.warning(
                "vector dimension mismatch: len1={} len2={}",
                len(vec1),
                len(vec2),
            )
            return 0.0
        arr1 = np.array(vec1)
        arr2 = np.array(vec2)
        dot_product = np.dot(arr1, arr2)
        norm1 = np.linalg.norm(arr1)
        norm2 = np.linalg.norm(arr2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        similarity = dot_product / (norm1 * norm2)
        return float(similarity)
