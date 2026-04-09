"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 拆分基础客户端类
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

修改时间: 2026-03-24
修改者: TraeAI
任务: Phase 2 - 统一客户端基类
修改内容:
1. 添加 _build_request_params 方法（统一请求参数构建）
2. 添加 _extract_response_content 方法（提取响应内容）
3. 添加 _parse_response 方法（解析JSON响应）
4. 统一 reasoning_effort 处理逻辑

修改时间: 2026-03-29
修改者: TraeAI
修改内容: extra_body 只包含 think 参数（云端模型不支持 thinking 字段）

修改时间: 2026-04-07
修改者: TraeAI
任务: code-review-fix
修改内容: 移除 _call_api_stream 中发送剩余 buffer 时的冗余条件判断

本模块包含模型客户端的基础类和公共接口，供标注客户端和消歧客户端继承使用。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, NamedTuple, TypeVar

from loguru import logger
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, BadRequestError
from pydantic import BaseModel

from src.config import TaskModelConfig, TaskType, load_task_config
from src.config.analysis_logger import AnalysisLogger
from src.models.local.parser.thinking import extract_thinking_unified

# StreamEvent 仅在 _call_api_stream 内部使用（lazy import 避免循环依赖）
# from src.api.models.events import StreamEvent

T = TypeVar("T", bound=BaseModel)


class TokenUsage(NamedTuple):
    """Token使用量记录"""

    novel_id: str
    task_type: str
    call_type: str
    prompt_tokens: int
    total_tokens: int
    completion_tokens: int | None
    chunk_id: int | None


TokenUsageCallback = Callable[[str, str, str, int, int, int | None, int | None], None]


class BaseModelClient:
    """
    模型客户端基类

    提供公共的配置管理、客户端初始化、API调用等功能。

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 支持传入 session 用于保存模型交互记录
    修改内容: 添加 _session 属性，用于在同一个 session 中保存模型交互记录

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: migrate-litellm-to-openai-sdk
    修改内容: 使用 OpenAI SDK 替代 LiteLLM
    """

    def __init__(
        self,
        task_type: TaskType,
        config: TaskModelConfig | None = None,
        client: Any | None = None,
        analysis_logger: AnalysisLogger | None = None,
        token_usage_callback: TokenUsageCallback | None = None,
        novel_id: str | None = None,
        session: Any | None = None,
    ) -> None:
        self._task_type = task_type
        loaded_config = config or load_task_config(task_type)
        loaded_config.validate()
        self._config = loaded_config
        if client is not None:
            self._client = client
        else:
            self._client = AsyncOpenAI(
                base_url=self._config.base_url,
                api_key=self._config.api_key,
                timeout=self._config.timeout_s,
            )
        self._analysis_logger = analysis_logger
        self._token_usage_callback = token_usage_callback
        self._novel_id = novel_id
        self._session = session
        logger.debug(
            "model client initialized: task_type={} base_url={} model={} timeout={}s",
            task_type,
            self._config.base_url,
            self._config.model,
            self._config.timeout_s,
        )

    def set_session(self, session: Any) -> None:
        """设置数据库会话（用于保存模型交互记录）。"""
        self._session = session

    def set_runtime_context(self, novel_id: str | None, token_usage_callback: Any) -> None:
        """设置运行时上下文（novel_id 和 token 回调）。"""
        self._novel_id = novel_id
        self._token_usage_callback = token_usage_callback

    def is_cloud_api(self) -> bool:
        """
        判断是否为云端API（云端API不支持top_k参数）

        创建时间: 2026-03-20
        创建者: TraeAI
        任务: 修复 incremental_disambiguation 被错误标记为 local 的问题
        修改内容: 将 _is_cloud_api 改为公共方法 is_cloud_api
        """
        base_url = self._config.base_url or ""
        if not base_url:
            return False
        is_cloud = not base_url.startswith("http://127.0.0.1") and not base_url.startswith("http://localhost")
        if is_cloud:
            logger.info(
                "[云端模型] 检测到云端API: base_url={}",
                base_url,
            )
        return is_cloud

    def _is_cloud_api(self) -> bool:
        """向后兼容的内部方法，委托给 is_cloud_api"""
        return self.is_cloud_api()

    def _handle_api_timeout(self, error: APITimeoutError) -> None:
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
            error.status_code if hasattr(error, "status_code") else "unknown",
            self._config.base_url,
            str(error),
        )
        raise RuntimeError(f"模型服务错误: {error}") from error

    def _record_token_usage(
        self,
        response: Any,
        call_type: str,
        chunk_id: int | None = None,
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
        chunk_id: int | None = None,
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

    def _build_json_schema(self, response_model: type[T]) -> dict[str, Any]:
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
            },
        }

    def _build_thinking_params(self, enable_thinking: bool) -> tuple[str, dict[str, bool]]:
        """
        Build thinking parameters for cloud/local providers.

        修改时间: 2026-03-29
        修改者: TraeAI
        修改内容: extra_body 只包含 think 参数（云端模型不支持 thinking 字段）
        """
        if enable_thinking:
            return "medium", {"think": True}
        return "none", {"think": False}

    async def _call_api(
        self,
        messages: list[dict],
        enable_thinking: bool = False,
        response_model: type[T] | None = None,
    ) -> Any:
        """
        非流式API调用

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取API调用基类
        说明: 统一的非流式API调用方法

        修改时间: 2026-04-09
        修改者: TraeAI
        任务: 重构 BaseModelClient 使用 AsyncOpenAI
        修改内容: 改为 async def，使用 await 调用
        """
        if not self._config.model:
            raise ValueError("model is required")

        request_params: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
        }

        if enable_thinking:
            request_params["reasoning_effort"] = "medium"
            request_params["extra_body"] = {"think": True}
        else:
            request_params["reasoning_effort"] = "none"
            request_params["extra_body"] = {"think": False}

        if response_model is not None:
            request_params["response_format"] = self._build_json_schema(response_model)

        return await self._client.chat.completions.create(**request_params)

    async def _call_api_stream(
        self,
        request_params: dict[str, Any],
        is_cloud: bool = False,
        emitter: Callable[[StreamEvent], Any] | None = None,
    ) -> Any:
        """
        流式API调用

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取API调用基类
        说明: 统一的流式API调用方法，支持实时控制台输出（仅云端API）

        修改时间: 2026-04-07
        修改者: TraeAI
        任务: websocket-streaming-progress
        修改内容: 添加 stream_callback 参数，支持流式输出回调，添加节流机制

        修改时间: 2026-04-09
        修改者: TraeAI
        任务: 重构 BaseModelClient 使用 AsyncOpenAI
        修改内容: 改为 async def，使用 async for 迭代流，使用 await 调用 stream_callback

        修改时间: 2026-04-09
        修改者: GLM-5
        任务: refactor/sse-unified-event-bus
        修改内容: stream_callback → emitter (StreamEvent 统一回调)
        """
        import time

        from src.api.models.events import StreamEvent

        request_params["stream"] = True

        logger.debug("Using streaming mode for API call")

        content_chunks: list[str] = []
        reasoning_chunks: list[str] = []
        chunk_count = 0

        last_output_broadcast_time = 0.0
        output_buffer = ""
        output_char_count = 0

        last_thinking_broadcast_time = 0.0
        thinking_buffer = ""
        thinking_char_count = 0

        if is_cloud:
            print(f"[Stream] Starting API call with model={request_params.get('model', 'unknown')}", flush=True)

        stream = await self._client.chat.completions.create(**request_params)
        async for chunk in stream:
            chunk_count += 1
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta.content:
                    content_chunks.append(delta.content)
                    output_buffer += delta.content
                    output_char_count += len(delta.content)

                    if is_cloud:
                        print(delta.content, end="", flush=True)

                    current_time = time.time()
                    should_broadcast = current_time - last_output_broadcast_time >= 0.1 or output_char_count >= 50
                    if emitter and should_broadcast:
                        await emitter(StreamEvent(action="output", content=output_buffer))
                        output_buffer = ""
                        output_char_count = 0
                        last_output_broadcast_time = current_time

                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    reasoning_chunks.append(delta.reasoning_content)
                    thinking_buffer += delta.reasoning_content
                    thinking_char_count += len(delta.reasoning_content)

                    if is_cloud:
                        print(f"\033[90m{delta.reasoning_content}\033[0m", end="", flush=True)

                    current_time = time.time()
                    should_broadcast = current_time - last_thinking_broadcast_time >= 0.1 or thinking_char_count >= 50
                    if emitter and should_broadcast:
                        await emitter(StreamEvent(action="thinking", content=thinking_buffer))
                        thinking_buffer = ""
                        thinking_char_count = 0
                        last_thinking_broadcast_time = current_time

        if is_cloud:
            print(f"\n[Stream] Completed: received {chunk_count} chunks", flush=True)

        if emitter and output_buffer:
            await emitter(StreamEvent(action="output", content=output_buffer))
        if emitter and thinking_buffer:
            await emitter(StreamEvent(action="thinking", content=thinking_buffer))

        full_content = "".join(content_chunks)
        full_reasoning = "".join(reasoning_chunks) if reasoning_chunks else None

        if not full_content and full_reasoning:
            full_content = full_reasoning
            full_reasoning = None

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

    def _parse_structured_response(self, response: Any, response_model: type[T]) -> T:
        """
        解析结构化响应

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: code-quality-refactor - 提取API调用基类
        说明: 从响应中提取 JSON 并解析为 Pydantic 模型

        修改时间: 2026-04-09
        修改者: TraeAI
        任务: fix-phase3-validation-error-logging
        修改内容: 在 ValidationError 发生前记录原始 JSON 数据，便于调试
        """
        from src.models.local.parser import try_parse_json

        if not response.choices:
            raise ValueError("Empty response from API")

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty content in response")

        if not isinstance(content, str):
            raise ValueError(f"Content must be a string, got {type(content).__name__}")

        json_data = try_parse_json(content)
        if json_data is None:
            raise ValueError(f"Failed to parse JSON from response: {content[:200]}")

        try:
            return response_model.model_validate(json_data)
        except Exception as e:
            logger.error(
                "Structured response validation failed: model={}, error={}, "
                "json_data={}, raw_content={}",
                response_model.__name__,
                str(e),
                json_data,
                content,
            )
            raise

    def _build_request_params(self, messages: list[dict], enable_thinking: bool = False) -> dict[str, Any]:
        """
        构建请求参数（统一方法）

        创建时间: 2026-03-24
        创建者: TraeAI
        任务: Phase 2 - 统一客户端基类
        说明: 统一云端和本地的请求参数构建逻辑

        修改时间: 2026-03-24
        修改者: TraeAI
        任务: Phase 2 - 统一客户端基类
        修改内容: 统一 reasoning_effort 处理，本地使用 extra_body={"think": true/false}
        """
        if not self._config.model:
            raise ValueError("model is required")

        request_params: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
        }

        # Ollama 本地API支持 reasoning_effort 参数
        if enable_thinking:
            request_params["reasoning_effort"] = "medium"
            request_params["extra_body"] = {"think": True}
        else:
            request_params["reasoning_effort"] = "none"
            request_params["extra_body"] = {"think": False}
        return request_params

    def _extract_response_content(self, message) -> tuple[str, str | None]:
        """
        提取响应内容（统一方法）

        创建时间: 2026-03-24
        创建者: TraeAI
        任务: Phase 2 - 统一客户端基类
        说明: 统一云端和本地的响应内容提取逻辑，支持多种思考内容格式
        """
        content = message.content or ""
        extraction = extract_thinking_unified(
            content=content,
            reasoning_content=getattr(message, "reasoning_content", None),
            support_reasoning_content=True,
            support_think_tags=True,
        )
        return extraction.content_without_thinking, extraction.thinking_content

    def _parse_response(self, content: str) -> dict[str, Any] | None:
        """
        解析JSON响应（统一方法）

        创建时间: 2026-03-24
        创建者: TraeAI
        任务: Phase 2 - 统一客户端基类
        说明: 支持处理 markdown 代码块包裹的 JSON，兼容云端和本地响应格式
        """
        content_to_parse = content.strip()

        if not content_to_parse:
            return None

        # 尝试直接解析
        try:
            data = json.loads(content_to_parse)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown 代码块中提取 JSON
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content_to_parse)
        if json_match:
            extracted = json_match.group(1).strip()
            try:
                data = json.loads(extracted)
                if isinstance(data, dict):
                    logger.info("[模型] JSON从markdown代码块中提取成功")
                    return data
            except json.JSONDecodeError:
                pass

        # 尝试从混合内容中提取 JSON 对象
        json_match = re.search(r"\{[\s\S]*\}", content_to_parse)
        if json_match:
            extracted = json_match.group(0)
            try:
                data = json.loads(extracted)
                if isinstance(data, dict):
                    logger.info("[模型] JSON从混合内容中提取成功")
                    return data
            except json.JSONDecodeError:
                pass

        return None
