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
"""

from __future__ import annotations

import os
from collections.abc import Callable

import numpy as np
from loguru import logger
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, BadRequestError

from src.config import settings

TokenUsageCallback = Callable[[str, str, str, int, int, int | None, int | None], None]


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

        if self._embedding_dim <= 0:
            raise ValueError(f"embedding dimension must be positive, got {self._embedding_dim}")

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
            response = await self._client.embeddings.create(
                model=self._model,
                input=text,
                encoding_format="float",
            )

            embedding = response.data[0].embedding
            self._validate_embedding_dimension(embedding)

            if self._token_usage_callback and response.usage:
                self._token_usage_callback(
                    self._novel_id or "unknown",
                    "embedding",
                    "local",
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
        except BadRequestError as e:
            self._log(
                "error",
                "get_embedding API错误: status={} base_url={} error={}",
                "api status error: status={} base_url={} error={}",
                e.status_code if hasattr(e, "status_code") else "unknown",
                self._base_url,
                str(e),
            )
            raise RuntimeError(f"embedding 服务错误: {e}") from e
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

        response = await self._client.embeddings.create(
            model=self._model,
            input=probe_text,
            encoding_format="float",
        )
        embedding = response.data[0].embedding
        return len(embedding)

    def _validate_embedding_dimension(self, embedding: list[float]) -> None:
        actual_dim = len(embedding)
        if actual_dim != self._embedding_dim:
            raise ValueError(
                f"embedding dimension mismatch: expected {self._embedding_dim}, got {actual_dim} (model={self._model})"
            )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        批量获取文本的embedding向量

        创建时间: 2026-03-18
        创建者: TraeAI
        任务: 支持语义分块的批量embedding

        修改时间: 2026-04-09
        修改者: TraeAI
        任务: 重构 EmbeddingClient 使用 AsyncOpenAI
        修改内容: 将 embed_texts 改为异步方法

        Args:
            texts: 文本列表

        Returns:
            embedding向量列表
        """
        embeddings = []
        for text in texts:
            embedding = await self.get_embedding(text)
            embeddings.append(embedding)
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
