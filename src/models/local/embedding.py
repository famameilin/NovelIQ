from __future__ import annotations

from typing import Callable, List, Optional

import numpy as np
import openai
from loguru import logger

from src.config import settings

TokenUsageCallback = Callable[[str, str, str, int, int, Optional[int], Optional[int]], None]


class EmbeddingClient:
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
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_s: float | None = None,
        max_retries: int | None = None,
        token_usage_callback: Optional[TokenUsageCallback] = None,
        novel_id: Optional[str] = None,
    ) -> None:
        if base_url is None or model is None:
            semantic_config = settings.models.semantic_chunking
            self._base_url = base_url or semantic_config.base_url
            self._model = model or semantic_config.model
            self._api_key = api_key or semantic_config.api_key or "sk-no-key-required"
            self._timeout_s = timeout_s if timeout_s is not None else semantic_config.timeout_s
            self._max_retries = max_retries if max_retries is not None else semantic_config.max_retries
        else:
            self._base_url = base_url
            self._model = model
            self._api_key = api_key or "sk-no-key-required"
            self._timeout_s = timeout_s
            self._max_retries = max_retries if max_retries is not None else 2

        self._client = openai.OpenAI(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout=self._timeout_s,
            max_retries=self._max_retries,
        )
        self._token_usage_callback = token_usage_callback
        self._novel_id = novel_id
        self._is_cloud = self._check_is_cloud()
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

    def get_embedding(self, text: str, chunk_id: Optional[int] = None) -> List[float]:
        """
        修改时间: 2026-03-13
        修改者: TraeAI
        修改内容: 使用 _log 方法统一处理日志记录，减少重复代码
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
            response = self._client.embeddings.create(
                model=self._model,
                input=text,
            )
            embedding = response.data[0].embedding

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
        except openai.APIConnectionError as e:
            self._log(
                "info" if self._is_cloud else "error",
                "get_embedding 连接错误: base_url={} error={}",
                "connection error to embedding service: base_url={} error={}",
                self._base_url,
                str(e),
            )
            raise ConnectionError(f"无法连接到 embedding 服务 ({self._base_url})，请检查服务是否启动") from e
        except openai.APITimeoutError as e:
            self._log(
                "info" if self._is_cloud else "error",
                "get_embedding 超时错误: base_url={} error={}",
                "timeout error: base_url={} error={}",
                self._base_url,
                str(e),
            )
            raise TimeoutError("embedding 服务请求超时，请检查服务响应") from e
        except openai.APIStatusError as e:
            self._log(
                "info" if self._is_cloud else "error",
                "get_embedding API错误: status={} base_url={} error={}",
                "api status error: status={} base_url={} error={}",
                e.status_code,
                self._base_url,
                str(e),
            )
            raise RuntimeError(f"embedding 服务错误 (状态码 {e.status_code}): {e.message}") from e
        except Exception as e:
            self._log(
                "info" if self._is_cloud else "error",
                "get_embedding 未知错误: {}",
                "get_embedding unexpected error: {}",
                str(e),
            )
            raise

    @staticmethod
    def compute_similarity(vec1: List[float], vec2: List[float]) -> float:
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
