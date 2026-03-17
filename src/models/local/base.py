"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 unified_client.py 拆分基础客户端类
修改时间: 2026-03-16
修改者: TraeAI
修改内容:
1. 将 OpenAI SDK 替换为 LiteLLM，适配异常处理
2. 使用共享的 get_model_with_provider 函数

修改时间: 2026-03-17
修改者: TraeAI
任务: code-quality-refactor - 提取API调用基类
修改内容:
1. 添加 _call_api 方法（非流式API调用）
2. 添加 _call_api_stream 方法（流式API调用）
3. 添加 _build_json_schema 方法
4. 添加 _build_stream_response 方法
5. 添加 _log_model_call 统一日志方法
6. 添加 _parse_structured_response 方法

本模块包含模型客户端的基础类和公共接口，供标注客户端和消歧客户端继承使用。
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Type, TypeVar

import litellm
from litellm.exceptions import APIConnectionError, Timeout, BadRequestError
from loguru import logger

from src.config import TaskModelConfig, TaskType, load_task_config
from src.config.analysis_logger import AnalysisLogger
from src.models.local.litellm_utils import get_model_with_provider

T = TypeVar("T")

TokenUsageCallback = Callable[[str, str, str, int, int, Optional[int], Optional[int]], None]


class _LiteLLMCompletionsWrapper:
    """
    LiteLLM Completions 包装器
    提供与 OpenAI SDK 类似的 chat.completions.create() 接口

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容:
    1. 支持 provider 前缀自动添加
    2. 使用共享的 get_model_with_provider 函数
    """

    def __init__(self, config: "TaskModelConfig") -> None:
        self._config = config

    def create(self, **kwargs) -> Any:
        """
        调用 LiteLLM completion API

        LiteLLM 会根据 model 参数自动路由到正确的提供商

        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 修复测试耗时异常
        修改内容: 添加 num_retries 参数支持，默认禁用 LiteLLM 内部重试
        """
        # 处理 model 参数，添加 provider 前缀
        model = kwargs.get("model")
        if model:
            kwargs["model"] = get_model_with_provider(model, self._config)

        # 如果没有显式传递 num_retries，则禁用 LiteLLM 内部重试
        if "num_retries" not in kwargs:
            kwargs["num_retries"] = 0

        return litellm.completion(api_base=self._config.base_url, api_key=self._config.api_key, **kwargs)


class _LiteLLMChatWrapper:
    """LiteLLM Chat API 包装器"""

    def __init__(self, config: "TaskModelConfig") -> None:
        self._config = config
        self.completions = _LiteLLMCompletionsWrapper(config)


class _LiteLLMClientWrapper:
    """
    LiteLLM 客户端包装器
    提供与 OpenAI SDK 类似的 client.chat.completions.create() 接口
    """

    def __init__(self, config: "TaskModelConfig") -> None:
        self._config = config
        self.chat = _LiteLLMChatWrapper(config)


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
        if client is not None:
            self._client = client
        else:
            self._client = _LiteLLMClientWrapper(self._config)
            if self._config.api_key:
                litellm.api_key = self._config.api_key
            if self._config.base_url:
                litellm.api_base = self._config.base_url
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
        # 空字符串或未配置视为本地API
        if not base_url:
            return False
        is_cloud = not base_url.startswith("http://127.0.0.1") and not base_url.startswith("http://localhost")
        if is_cloud:
            logger.info(
                "[云端模型] 检测到云端API: base_url={}",
                base_url,
            )
        return is_cloud

    def _build_extra_body(self, enable_thinking: bool) -> dict[str, Any]:
        """
        构建extra_body参数，仅包含本地模型需要的参数

        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 修复thinking参数传递方式
        修改内容: 将thinking参数移到顶级参数，extra_body仅包含本地模型参数
        """
        extra_body: dict[str, Any] = {}
        if not self._is_cloud_api():
            extra_body["top_k"] = self._config.top_k
            extra_body["chat_template_kwargs"] = {"enable_thinking": enable_thinking}
        return extra_body

    def _get_thinking_params(self, enable_thinking: bool) -> dict[str, Any]:
        """
        获取thinking相关参数（顶级参数）

        创建时间: 2026-03-16
        创建者: TraeAI
        任务: 修复thinking参数传递方式
        说明: 根据LiteLLM文档，thinking应作为顶级参数传递，而非放在extra_body中

        返回: 包含thinking或reasoning_effort参数的字典
        """
        if not enable_thinking:
            return {}

        model_name = (self._config.model or "").lower()

        if "claude" in model_name or "anthropic" in model_name:
            budget = self._config.thinking_budget_tokens
            if budget:
                return {"thinking": {"type": "enabled", "budget_tokens": budget}}
            return {"thinking": {"type": "enabled"}}
        elif "deepseek" in model_name:
            return {"thinking": {"type": "enabled"}}
        else:
            return {"reasoning_effort": "medium"}

    def _handle_api_timeout(self, error: Timeout) -> None:
        """处理API超时错误"""
        logger.error(
            "timeout error: base_url={} timeout={}s error={}",
            self._config.base_url,
            self._config.timeout_s,
            str(error),
        )
        raise TimeoutError(f"模型服务请求超时 ({self._config.timeout_s}s)，请检查服务响应") from error

    def _handle_api_connection_error(self, error: APIConnectionError) -> None:
        """处理API连接错误"""
        logger.error(
            "connection error to model service: base_url={} error={}",
            self._config.base_url,
            str(error),
        )
        raise ConnectionError(f"无法连接到模型服务 ({self._config.base_url})，请检查服务是否启动") from error

    def _handle_api_status_error(self, error: BadRequestError) -> None:
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

    def _record_token_usage_estimated(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        call_type: str,
        chunk_id: Optional[int] = None,
    ) -> None:
        """
        记录估算的token使用量

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: 为流式API提供token使用估算记录
        说明: 使用tiktoken估算的token数量，用于流式API场景
        """
        if self._token_usage_callback:
            self._token_usage_callback(
                self._novel_id or "unknown",
                self._task_type,
                call_type,
                prompt_tokens,
                total_tokens,
                completion_tokens,
                chunk_id,
            )

    def _build_json_schema(self, response_model: Type[T]) -> dict[str, Any]:
        """
        构建 JSON Schema 用于结构化输出

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取API调用基类
        说明: 使用 Pydantic 的 model_json_schema() 方法生成 JSON Schema
        """
        schema = response_model.model_json_schema()
        return {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__,
                "schema": schema,
                "strict": True,
            }
        }

    def _call_api(
        self,
        messages: List[dict],
        enable_thinking: bool = False,
        response_model: Type[T] | None = None,
    ) -> Any:
        """
        非流式API调用

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取API调用基类
        说明: 统一的非流式API调用方法
        """
        if not self._config.model:
            raise ValueError("model is required")

        model_name = get_model_with_provider(self._config.model, self._config)
        thinking_params = self._get_thinking_params(enable_thinking)
        extra_body = self._build_extra_body(enable_thinking)

        if self._client is None:
            raise ValueError("client is required")

        request_params: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
            "presence_penalty": self._config.presence_penalty,
            "extra_body": extra_body,
        }

        if response_model is not None:
            request_params["response_format"] = self._build_json_schema(response_model)

        request_params.update(thinking_params)

        return self._client.chat.completions.create(**request_params)

    def _call_api_stream(
        self,
        request_params: dict[str, Any],
        is_cloud: bool = False,
    ) -> Any:
        """
        流式API调用

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取API调用基类
        说明: 统一的流式API调用方法，支持实时控制台输出（仅云端API）
        """
        if self._client is None:
            raise ValueError("client is required")

        request_params["stream"] = True

        logger.debug("Using streaming mode for API call")

        content_chunks: list[str] = []
        reasoning_chunks: list[str] = []
        chunk_count = 0

        # 只在云端API时输出到控制台
        if is_cloud:
            print(f"[Stream] Starting API call with model={request_params.get('model', 'unknown')}", flush=True)

        for chunk in self._client.chat.completions.create(**request_params):
            chunk_count += 1
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta.content:
                    content_chunks.append(delta.content)
                    # 只在云端API时实时输出到控制台
                    if is_cloud:
                        print(delta.content, end="", flush=True)
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    reasoning_chunks.append(delta.reasoning_content)
                    # 只在云端API时实时输出 reasoning 到控制台（使用不同颜色）
                    if is_cloud:
                        print(f"\033[90m{delta.reasoning_content}\033[0m", end="", flush=True)

        if is_cloud:
            print(f"\n[Stream] Completed: received {chunk_count} chunks", flush=True)

        full_content = "".join(content_chunks)
        full_reasoning = "".join(reasoning_chunks) if reasoning_chunks else None

        return self._build_stream_response(full_content, full_reasoning)

    def _build_stream_response(self, content: str, reasoning_content: str | None) -> Any:
        """
        构建流式响应的模拟响应对象

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取API调用基类
        说明: 将流式收集的内容构建为标准响应格式
        """
        from types import SimpleNamespace

        message = SimpleNamespace(
            content=content,
            reasoning_content=reasoning_content,
            role="assistant",
        )
        choice = SimpleNamespace(
            message=message,
            finish_reason="stop",
            index=0,
        )
        response = SimpleNamespace(
            choices=[choice],
            model=self._config.model,
        )
        return response

    def _log_model_call(
        self,
        operation: str,
        is_cloud: bool,
        extra_fields: dict[str, Any] | None = None,
    ) -> None:
        """
        统一的模型调用日志记录

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取API调用基类
        说明: 统一记录云端/本地模型调用日志，区分格式
        """
        base_fields = {
            "novel_id": self._novel_id,
            "task_type": self._task_type,
            "model": self._config.model,
        }
        if extra_fields:
            base_fields.update(extra_fields)

        if is_cloud:
            logger.info("[云端模型] {} 开始: {}", operation, base_fields)
        else:
            logger.debug("{} start: {}", operation, base_fields)

    def _parse_structured_response(self, response: Any, response_model: Type[T]) -> T:
        """
        解析结构化响应

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取API调用基类
        说明: 从响应中提取 JSON 并解析为 Pydantic 模型
        """
        from src.models.local.parser import try_parse_json

        if not response.choices:
            raise ValueError("Empty response from API")

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty content in response")

        # 确保 content 是字符串类型
        if not isinstance(content, str):
            raise ValueError(f"Content must be a string, got {type(content).__name__}")

        json_data = try_parse_json(content)
        if json_data is None:
            raise ValueError(f"Failed to parse JSON from response: {content[:200]}")

        return response_model.model_validate(json_data)
