"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 unified_client.py 拆分基础客户端类

本模块包含模型客户端的基础类和公共接口，供标注客户端和消歧客户端继承使用。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import openai
from loguru import logger

from src.config import TaskModelConfig, TaskType, load_task_config
from src.config.analysis_logger import AnalysisLogger

TokenUsageCallback = Callable[[str, str, str, int, int, Optional[int], Optional[int]], None]


class BaseModelClient:
    """
    模型客户端基类

    提供公共的配置管理、客户端初始化、API调用等功能。
    """

    def __init__(
        self,
        task_type: TaskType,
        config: TaskModelConfig | None = None,
        client: Any | None = None,
        analysis_logger: AnalysisLogger | None = None,
        token_usage_callback: Optional[TokenUsageCallback] = None,
        novel_id: Optional[str] = None,
    ) -> None:
        self._task_type = task_type
        loaded_config = config or load_task_config(task_type)
        loaded_config.validate()
        self._config = loaded_config
        self._client = client or openai.OpenAI(
            base_url=self._config.base_url,
            api_key=self._config.api_key,
            timeout=self._config.timeout_s,
            max_retries=self._config.max_retries,
        )
        self._analysis_logger = analysis_logger
        self._token_usage_callback = token_usage_callback
        self._novel_id = novel_id
        logger.debug(
            "model client initialized: task_type={} base_url={} model={} timeout={}s",
            task_type,
            self._config.base_url,
            self._config.model,
            self._config.timeout_s,
        )

    def _is_cloud_api(self) -> bool:
        """判断是否为云端API（云端API不支持top_k参数）"""
        base_url = self._config.base_url or ""
        is_cloud = not base_url.startswith("http://127.0.0.1") and not base_url.startswith("http://localhost")
        if is_cloud:
            logger.info(
                "[云端模型] 检测到云端API: base_url={}",
                base_url,
            )
        return is_cloud

    def _build_extra_body(self, enable_thinking: bool) -> dict[str, Any]:
        """构建extra_body参数，云端API不包含top_k"""
        extra_body: dict[str, Any] = {
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
            "thinking": {"type": "enabled"} if enable_thinking else None,
        }
        if not self._is_cloud_api():
            extra_body["top_k"] = self._config.top_k
        return extra_body

    def _handle_api_timeout(self, error: openai.APITimeoutError) -> None:
        """处理API超时错误"""
        logger.error(
            "timeout error: base_url={} timeout={}s error={}",
            self._config.base_url,
            self._config.timeout_s,
            str(error),
        )
        raise TimeoutError(f"模型服务请求超时 ({self._config.timeout_s}s)，请检查服务响应") from error

    def _handle_api_connection_error(self, error: openai.APIConnectionError) -> None:
        """处理API连接错误"""
        logger.error(
            "connection error to model service: base_url={} error={}",
            self._config.base_url,
            str(error),
        )
        raise ConnectionError(f"无法连接到模型服务 ({self._config.base_url})，请检查服务是否启动") from error

    def _handle_api_status_error(self, error: openai.APIStatusError) -> None:
        """处理API状态错误"""
        logger.error(
            "api status error: status={} base_url={} error={}",
            error.status_code,
            self._config.base_url,
            str(error),
        )
        raise RuntimeError(f"模型服务错误 (状态码 {error.status_code}): {error.message}") from error

    def _record_token_usage(
        self,
        response: Any,
        call_type: str,
        chunk_id: Optional[int] = None,
    ) -> None:
        """记录token使用量"""
        if self._token_usage_callback and hasattr(response, "usage") and response.usage:
            self._token_usage_callback(
                self._novel_id or "unknown",
                self._task_type,
                call_type,
                response.usage.prompt_tokens,
                response.usage.total_tokens,
                response.usage.completion_tokens,
                chunk_id,
            )
