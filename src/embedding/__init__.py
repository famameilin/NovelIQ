"""嵌入客户端：文本向量化（本地 llama-server，OpenAI 兼容接口）与查询侧的 instruct 前缀包装。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from loguru import logger
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, BadRequestError

from src.config import settings

TokenUsageCallback = Callable[[str, str, int, int, int | None, int | None], None]
BatchProgressCallback = Callable[[int, int, int], Awaitable[None] | None]
RETRYABLE_EMBEDDING_STATUS_CODES = {429, 500, 502, 503, 504}
EMBEDDING_MAX_RETRIES = 2
EMBEDDING_RETRY_BASE_DELAY_S = 0.5
# 连接建立失败/超时类错误批内重试最多 3 次、指数退避；
# 状态码路径预算不变；嵌入请求只读幂等，重发无数据副作用
EMBEDDING_CONNECTION_MAX_RETRIES = 3
EMBEDDING_CONNECTION_RETRY_DELAY_S = 0.5

# 查询侧嵌入按 Qwen3-Embedding 官方非对称检索配方加 instruct 前缀：
# 检索文档侧（embed_texts）必须直发原文不加前缀，只有查询侧走 format_query_instruct；
# 指令按官方建议写英文；换成对称嵌入模型时须移除前缀，否则相似度失真。
QUERY_INSTRUCT_TASK = "Given a query about a novel, retrieve original novel passages relevant to the query"


class EmbeddingServiceError(RuntimeError):
    """嵌入依赖故障，由调用方终止任务，不交给模型修正"""


class EmbeddingConnectionError(EmbeddingServiceError, ConnectionError):
    """保留连接异常语义，同时标明故障来自嵌入服务"""


class EmbeddingTimeoutError(EmbeddingServiceError, TimeoutError):
    """保留超时语义，同时标明故障来自嵌入服务"""


def format_query_instruct(query: str) -> str:
    """按模型卡官方模板包装查询文本（Instruct: {task}\nQuery:{query}）"""
    return f"Instruct: {QUERY_INSTRUCT_TASK}\nQuery:{query}"


class EmbeddingClient:
    """Embedding 客户端"""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_s: float | None = None,
        token_usage_callback: TokenUsageCallback | None = None,
        novel_id: str | None = None,
    ) -> None:
        semantic_config = settings.models.paragraph_embedding
        if base_url is None or model is None:
            self._base_url = base_url or semantic_config.base_url
            self._model = model or semantic_config.model
            self._timeout_s = timeout_s if timeout_s is not None else semantic_config.timeout_s
            self._batch_size = semantic_config.batch_size
        else:
            self._base_url = base_url
            self._model = model
            self._timeout_s = timeout_s
            self._batch_size = settings.models.paragraph_embedding.batch_size

        self._api_key = api_key if api_key is not None else semantic_config.api_key
        if not self._api_key:
            raise ValueError("EMBEDDING_MODEL_KEY 不能为空")
        if self._batch_size <= 0:
            raise ValueError(f"embedding batch size must be positive, got {self._batch_size}")
        # 维度不是配置：以嵌入服务实测输出为准，detect_embedding_dimension 探测后锁定；
        # 锁定前逐条校验跳过（表级维度由 pgvector 列约束兜底）
        self._embedding_dim: int | None = None

        self._token_usage_callback = token_usage_callback
        self._novel_id = novel_id

        self._client = AsyncOpenAI(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout=self._timeout_s,
            max_retries=0,
        )

        logger.debug(
            "embedding client initialized: base_url={} model={}",
            self._base_url,
            self._model,
        )

    async def aclose(self) -> None:
        """释放当前检索调用持有的 HTTP 连接，取消时同样执行"""
        await self._client.close()

    def _log(self, level: str, msg: str, *args) -> None:
        """逐条/分批的 info 日志压到 debug（错误与警告按原级别），避免逐条刷屏"""
        if level == "info":
            logger.debug(msg, *args)
            return
        getattr(logger, level, logger.debug)(msg, *args)

    def _is_retryable_embedding_status_error(self, error: APIStatusError) -> bool:
        status_code = getattr(error, "status_code", None)
        if not isinstance(status_code, int):
            return False
        return status_code in RETRYABLE_EMBEDDING_STATUS_CODES

    def _require_model_name(self) -> str:
        """返回必填的嵌入模型名称并收窄类型"""
        if not self._model:
            raise ValueError("embedding model is required")
        return self._model

    async def _connection_retry(self, error: APIConnectionError, attempt: int) -> None:
        """记录一次连接级重试并按指数退避等待；APITimeoutError 是其子类同走该路径"""
        delay = EMBEDDING_CONNECTION_RETRY_DELAY_S * (2 ** (attempt - 1))
        self._log(
            "warning",
            "embedding 连接级重试: base_url={} attempt={}/{} delay_s={} error={}",
            self._base_url,
            attempt,
            EMBEDDING_CONNECTION_MAX_RETRIES,
            delay,
            str(error),
        )
        await asyncio.sleep(delay)

    async def _create_embeddings_with_retry(self, text_input: str | list[str]):
        """连接/超时类错误批内重试最多 3 次；状态码路径保持原预算；耗尽后原样抛出保留下游分类"""
        model_name = self._require_model_name()
        connection_attempts = 0
        status_attempts = 0
        while True:
            try:
                response = await self._client.embeddings.create(
                    model=model_name, input=text_input, encoding_format="float",
                )
                return response
            except APITimeoutError as e:
                connection_attempts += 1
                if connection_attempts > EMBEDDING_CONNECTION_MAX_RETRIES:
                    self._log(
                        "error",
                        "embedding 连接重试耗尽: base_url={} attempts={} error={}",
                        self._base_url,
                        connection_attempts - 1,
                        str(e),
                    )
                    raise
                await self._connection_retry(e, connection_attempts)
            except APIConnectionError as e:
                connection_attempts += 1
                if connection_attempts > EMBEDDING_CONNECTION_MAX_RETRIES:
                    self._log(
                        "error",
                        "embedding 连接重试耗尽: base_url={} attempts={} error={}",
                        self._base_url,
                        connection_attempts - 1,
                        str(e),
                    )
                    raise
                await self._connection_retry(e, connection_attempts)
            except BadRequestError as e:
                self._log(
                    "error",
                    "embedding API错误: status={} base_url={} error={}",
                    e.status_code if hasattr(e, "status_code") else "unknown",
                    self._base_url,
                    str(e),
                )
                raise EmbeddingServiceError(f"embedding 服务错误: {e}") from e
            except APIStatusError as e:
                status_attempts += 1
                should_retry = self._is_retryable_embedding_status_error(e) and status_attempts <= EMBEDDING_MAX_RETRIES
                self._log(
                    "warning" if should_retry else "error",
                    "embedding API状态错误: status={} attempt={}/{} base_url={} retry={} error={}",
                    getattr(e, "status_code", "unknown"),
                    status_attempts,
                    EMBEDDING_MAX_RETRIES + 1,
                    self._base_url,
                    should_retry,
                    str(e),
                )
                if not should_retry:
                    raise EmbeddingServiceError(f"embedding 服务错误: {e}") from e
                await asyncio.sleep(EMBEDDING_RETRY_BASE_DELAY_S * status_attempts)

    async def get_embedding(self, text: str, chunk_id: int | None = None) -> list[float]:
        """获取文本的 embedding 向量"""
        if not self._model:
            raise ValueError("embedding model is required")
        if not text or not text.strip():
            logger.warning("empty text provided for embedding")
            return []

        self._log(
            "info",
            "get_embedding 开始: model={} text_len={} chunk_id={}",
            self._model,
            len(text),
            chunk_id,
        )
        try:
            response = await self._create_embeddings_with_retry(text)

            embedding = response.data[0].embedding
            self._validate_embedding_dimension(embedding)

            if self._token_usage_callback and response.usage:
                # 优先保留 provider 实报 usage；汇总层对外仍标 estimated（整条链路只承诺近似统计）
                self._token_usage_callback(
                    "embedding",
                    self._model or "unknown",
                    response.usage.prompt_tokens,
                    response.usage.total_tokens,
                    None,
                    chunk_id,
                )

            self._log(
                "info",
                "get_embedding 完成: dim={} prompt_tokens={} total_tokens={}",
                len(embedding),
                response.usage.prompt_tokens if response.usage else 0,
                response.usage.total_tokens if response.usage else 0,
            )
            return embedding
        except APITimeoutError as e:
            # SDK 超时继承连接异常，必须先匹配才能保留超时分类
            self._log(
                "error",
                "get_embedding 超时错误: base_url={} error={}",
                self._base_url,
                str(e),
            )
            raise EmbeddingTimeoutError("embedding 服务请求超时，请检查服务响应") from e
        except APIConnectionError as e:
            self._log(
                "error",
                "get_embedding 连接错误: base_url={} error={}",
                self._base_url,
                str(e),
            )
            raise EmbeddingConnectionError(f"无法连接到 embedding 服务 ({self._base_url})，请检查服务是否启动") from e
        except Exception as e:
            self._log(
                "error",
                "get_embedding 未知错误: {}",
                str(e),
            )
            raise

    async def detect_embedding_dimension(self, probe_text: str = "dimension probe") -> int:
        """探测嵌入模型实测输出维度，并锁定为后续逐条校验的基准"""
        if not self._model:
            raise ValueError("embedding model is required")

        response = await self._create_embeddings_with_retry(probe_text)
        embedding = response.data[0].embedding
        self._embedding_dim = len(embedding)
        return self._embedding_dim

    def _validate_embedding_dimension(self, embedding: list[float]) -> None:
        if self._embedding_dim is None:
            return
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
                self._model,
                len(batch_texts),
                batch_start,
            )

            try:
                response = await self._create_embeddings_with_retry(batch_texts)
            except APITimeoutError as e:
                self._log(
                    "error",
                    "embed_texts 超时错误: base_url={} error={}",
                    self._base_url,
                    str(e),
                )
                raise EmbeddingTimeoutError("embedding 服务请求超时，请检查服务响应") from e
            except APIConnectionError as e:
                self._log(
                    "error",
                    "embed_texts 连接错误: base_url={} error={}",
                    self._base_url,
                    str(e),
                )
                raise EmbeddingConnectionError(
                    f"无法连接到 embedding 服务 ({self._base_url})，请检查服务是否启动"
                ) from e
            except Exception as e:
                self._log(
                    "error",
                    "embed_texts 未知错误: {}",
                    str(e),
                )
                raise

            response_items = sorted(response.data, key=lambda item: getattr(item, "index", 0))
            if len(response_items) != len(batch_items):
                raise RuntimeError(
                    f"embedding batch result count mismatch: expected {len(batch_items)}, got {len(response_items)}"
                )

            # 按 index 回填到原始位置（调用方无需感知批量请求模式）
            for (original_idx, _), item in zip(batch_items, response_items, strict=True):
                embedding = item.embedding
                self._validate_embedding_dimension(embedding)
                embeddings[original_idx] = embedding

            if self._token_usage_callback and response.usage:
                # provider 已返回 usage 时直接记实报（与单条 embedding 口径一致）
                self._token_usage_callback(
                    "embedding",
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
