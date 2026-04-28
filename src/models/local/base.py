"""
本模块包含模型客户端的基础类和公共接口，供标注客户端和消歧客户端继承使用
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple, TypeVar

from loguru import logger
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, BadRequestError
from pydantic import BaseModel

from src.config import TaskModelConfig, TaskType, load_task_config
from src.config.analysis_logger import AnalysisLogger
from src.models.local.base_stream_emitter import build_stream_response
from src.models.local.base_structured_parser import (
    extract_response_content,
    parse_response,
    parse_structured_response,
)
from src.models.local.base_token_usage import (
    extract_reasoning_tokens,
    record_estimated_token_usage_from_messages,
    record_estimated_token_usage_from_response,
    record_token_usage,
    record_token_usage_estimated,
    resolve_token_usage_novel_id,
)
from src.models.local.base_transport import call_api, call_api_stream

if TYPE_CHECKING:
    from src.api.models.events import StreamEvent

T = TypeVar("T", bound=BaseModel)


def _ensure_strict_json_schema(node: Any) -> None:
    """
    递归收紧 JSON Schema，满足 strict structured output 的对象约束

    说明: 仅为声明了 properties 的对象补充 additionalProperties=false，
    避免把 dict[str, T] 这类映射 schema 误改成不允许任何键
    """
    if isinstance(node, dict):
        # 只有真正的对象模型才补 false 和完整 required；
        # 映射类型会以 additionalProperties: {...} 表示值 schema，不能把它误改成封闭对象
        if node.get("type") == "object" and "properties" in node and isinstance(node["properties"], dict):
            node.setdefault("additionalProperties", False)
            node["required"] = list(node["properties"].keys())

        for key in ("properties", "$defs"):
            child = node.get(key)
            if isinstance(child, dict):
                for value in child.values():
                    _ensure_strict_json_schema(value)

        for key in ("items", "additionalProperties", "contains", "if", "then", "else", "not"):
            child = node.get(key)
            if child is not None:
                _ensure_strict_json_schema(child)

        for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
            child = node.get(key)
            if isinstance(child, list):
                for item in child:
                    _ensure_strict_json_schema(item)
        return

    if isinstance(node, list):
        for item in node:
            _ensure_strict_json_schema(item)


def _strip_internal_schema_properties(node: Any) -> None:
    """
    递归移除仅供运行时内部使用的 schema 字段

    说明: `_thinking_content` 这类内部字段并不要求模型通过 JSON 输出返回，
    而是由流式响应中的 reasoning_content 单独提取，因此不应进入 strict response_format
    """
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node and isinstance(node["properties"], dict):
            internal_keys = [key for key in node["properties"].keys() if isinstance(key, str) and key.startswith("_")]
            for key in internal_keys:
                node["properties"].pop(key, None)
            if "required" in node and isinstance(node["required"], list):
                node["required"] = [key for key in node["required"] if key not in internal_keys]

        for key in ("properties", "$defs"):
            child = node.get(key)
            if isinstance(child, dict):
                for value in child.values():
                    _strip_internal_schema_properties(value)

        for key in ("items", "additionalProperties", "contains", "if", "then", "else", "not"):
            child = node.get(key)
            if child is not None:
                _strip_internal_schema_properties(child)

        for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
            child = node.get(key)
            if isinstance(child, list):
                for item in child:
                    _strip_internal_schema_properties(item)
        return

    if isinstance(node, list):
        for item in node:
            _strip_internal_schema_properties(item)


class TokenUsage(NamedTuple):
    """Token使用量记录"""

    novel_id: str
    task_type: str
    call_type: str
    model: str
    prompt_tokens: int
    total_tokens: int
    completion_tokens: int | None
    chunk_id: int | None


TokenUsageCallback = Callable[[str, str, str, str, int, int, int | None, int | None], None]


class BaseModelClient:
    """
    模型客户端基类

    提供公共的配置管理、客户端初始化、API调用等功能
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
        """设置数据库会话（用于保存模型交互记录）"""
        self._session = session

    def set_runtime_context(self, novel_id: str | None, token_usage_callback: Any) -> None:
        """设置运行时上下文（novel_id 和 token 回调）"""
        self._novel_id = novel_id
        self._token_usage_callback = token_usage_callback

    def is_cloud_api(self) -> bool:
        """
        判断是否为云端API（云端API不支持top_k参数）
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
        """
        记录 token 使用量
        """
        record_token_usage(self, response, call_type, chunk_id)

    def _resolve_token_usage_novel_id(self, call_type: str) -> str | None:
        """
        解析 token_usage 记录要落库的 novel_id

        说明: token 记账现在已经受 novel 外键保护；
              若运行时上下文没有提供 novel_id，不能再写入 `unknown` 这种脏值
        """
        return resolve_token_usage_novel_id(self, call_type)

    def _extract_reasoning_tokens(self, response: Any) -> int | None:
        """
        从响应对象中提取 reasoning token 数

        说明: 优先读取 usage.completion_tokens_details.reasoning_tokens
              对非标准对象和 dict 结构都做兼容，拿不到时返回 None
        """
        return extract_reasoning_tokens(response)

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

        说明: 使用tiktoken估算的token数量，用于流式API场景
        """
        record_token_usage_estimated(
            self,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            call_type,
            chunk_id,
        )

    def _record_estimated_token_usage_from_messages(
        self,
        messages: list[dict[str, Any]],
        response_text: str,
        call_type: str,
        chunk_id: int | None = None,
        *,
        task_type: str | None = None,
        model_name: str | None = None,
    ) -> None:
        """
        基于 prompt/response 文本统一记录估算 token

        说明: token_usage 对外统一收敛为“估算消耗”口径
              各条调用链都应走这一入口，避免 provider 实报、局部估算、
              以及漏记混成多套账本
        """
        record_estimated_token_usage_from_messages(
            self,
            messages,
            response_text,
            call_type,
            chunk_id,
            task_type=task_type,
            model_name=model_name,
        )

    def _extract_response_text_for_token_usage(self, response: Any) -> str:
        """
        从响应对象中提取可用于 token 估算的文本

        说明: 当请求已经返回，但后续结构化解析或业务校验失败时，
              仍应尽量按真实响应文本补记 token；若提取失败则保守回退为空字符串
        """
        from src.models.local.base_token_usage import extract_response_text_for_token_usage

        return extract_response_text_for_token_usage(self, response)

    def _record_estimated_token_usage_from_response(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        call_type: str,
        chunk_id: int | None = None,
        *,
        task_type: str | None = None,
        model_name: str | None = None,
    ) -> None:
        """
        基于响应对象补记统一估算 token

        说明: 主要用于“模型调用已完成，但解析/校验失败”的路径；
              此时至少应把 prompt 算上，若还能提取出响应文本，则连 completion 一并估算
        """
        record_estimated_token_usage_from_response(
            self,
            messages,
            response,
            call_type,
            chunk_id,
            task_type=task_type,
            model_name=model_name,
        )

    def _build_json_schema(self, response_model: type[T]) -> dict[str, Any]:
        """
        构建 JSON Schema 用于结构化输出

        说明: 使用 Pydantic 的 model_json_schema() 方法生成 JSON Schema
        """
        schema = response_model.model_json_schema()
        _strip_internal_schema_properties(schema)
        _ensure_strict_json_schema(schema)
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
        Build thinking parameters for cloud/local providers
        """
        if enable_thinking:
            return "medium", {"think": True}
        return "", {}

    async def _call_api(
        self,
        messages: list[dict],
        enable_thinking: bool = False,
        response_model: type[T] | None = None,
        raw_response_format: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """
        非流式API调用

        说明: 统一的非流式API调用方法
        """
        return await call_api(
            self,
            messages,
            enable_thinking=enable_thinking,
            response_model=response_model,
            raw_response_format=raw_response_format,
            timeout=timeout,
        )

    async def _call_api_stream(
        self,
        request_params: dict[str, Any],
        is_cloud: bool = False,
        emitter: Callable[[StreamEvent], Any] | None = None,
    ) -> Any:
        """
        流式API调用

        说明: 统一的流式API调用方法，支持实时控制台输出（仅云端API）
        """
        return await call_api_stream(
            self,
            request_params,
            is_cloud=is_cloud,
            emitter=emitter,
        )

    def _build_stream_response(self, content: str, reasoning_content: str | None, usage: Any = None) -> Any:
        """
        构建流式响应的模拟响应对象

        说明: 将流式收集的内容构建为标准响应格式
        """
        return build_stream_response(self._config.model, content, reasoning_content, usage=usage)

    def _log_model_call(
        self,
        operation: str,
        is_cloud: bool,
        extra_fields: dict[str, Any] | None = None,
    ) -> None:
        """
        统一的模型调用日志记录

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

        说明: 从响应中提取 JSON 并解析为 Pydantic 模型
        """
        return parse_structured_response(response, response_model)

    def _build_request_params(self, messages: list[dict], enable_thinking: bool = False) -> dict[str, Any]:
        """
        构建请求参数（统一方法）

        说明: 统一云端和本地的请求参数构建逻辑
        """
        if not self._config.model:
            raise ValueError("model is required")

        request_params: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
        }

        # 关闭 thinking 时统一保持请求体最小化，避免不同 provider 对显式 false 的兼容差异
        if enable_thinking:
            request_params["reasoning_effort"] = "medium"
            request_params["extra_body"] = {"think": True}
        return request_params

    def _extract_response_content(self, message) -> tuple[str, str | None]:
        """
        提取响应内容（统一方法）

        说明: 统一云端和本地的响应内容提取逻辑，支持多种思考内容格式
        """
        return extract_response_content(message)

    def _parse_response(self, content: str) -> dict[str, Any] | None:
        """
        解析JSON响应（统一方法）

        说明: 支持处理 markdown 代码块包裹的 JSON，兼容云端和本地响应格式
        """
        return parse_response(content)
