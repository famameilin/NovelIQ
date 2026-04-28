"""
项目级结构化输出适配层。

说明: 统一 json_schema / json_object 的调用、解析与响应元信息提取。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from src.models.structured_output.modes import (
    JSON_OBJECT_MODE,
    JSON_SCHEMA_MODE,
    StructuredOutputMode,
)
from src.models.structured_output.provider_capabilities import resolve_structured_output_mode


@dataclass(frozen=True)
class StructuredOutputRequest[T: BaseModel]:
    """
    单次结构化输出请求。
    """

    messages: list[dict[str, Any]]
    response_model: type[T]
    call_type: str
    enable_thinking: bool
    timeout: float | None = None
    json_output_prompt_hint: str | None = None
    stream: bool = False
    stream_emitter: Any | None = None


@dataclass(frozen=True)
class StructuredOutputResult[T: BaseModel]:
    """
    单次结构化输出结果。
    """

    parsed: T
    raw_response: Any
    response_text: str
    thinking_content: str | None
    reasoning_tokens: int | None
    mode: StructuredOutputMode


class StructuredOutputError(ValueError):
    """
    结构化输出调用或解析失败。
    """

    def __init__(
        self,
        message: str,
        *,
        raw_response: Any | None = None,
        response_text: str = "",
        thinking_content: str | None = None,
        reasoning_tokens: int | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_response = raw_response
        self.response_text = response_text
        self.thinking_content = thinking_content
        self.reasoning_tokens = reasoning_tokens


def build_response_format[T: BaseModel](
    client: Any,
    response_model: type[T],
    mode: StructuredOutputMode,
) -> dict[str, Any] | None:
    """
    构建 provider 原生 response_format。
    """
    if mode == JSON_SCHEMA_MODE:
        return client._build_json_schema(response_model)
    if mode == JSON_OBJECT_MODE:
        return {"type": "json_object"}
    raise ValueError(f"unsupported structured output mode: {mode}")


async def call_structured_output[T: BaseModel](
    client: Any,
    request: StructuredOutputRequest[T],
) -> StructuredOutputResult[T]:
    """
    执行一次结构化模型调用。
    """
    mode = resolve_structured_output_mode(client, request.call_type)
    if mode == JSON_OBJECT_MODE:
        _validate_json_output_prompt_contract(request.messages)

    return await _call_openai_compatible(client, request, mode)


async def _call_openai_compatible[T: BaseModel](
    client: Any,
    request: StructuredOutputRequest[T],
    mode: StructuredOutputMode,
) -> StructuredOutputResult[T]:
    """
    调用 OpenAI-compatible transport 并执行本地 Pydantic 校验。
    """
    raw_response_format = build_response_format(client, request.response_model, mode)
    raw_response: Any | None = None
    try:
        if request.stream:
            request_params = client._build_request_params(request.messages, enable_thinking=request.enable_thinking)
            if raw_response_format is not None:
                request_params["response_format"] = raw_response_format
            if request.timeout is not None:
                request_params["timeout"] = request.timeout
            raw_response = await client._call_api_stream(
                request_params,
                is_cloud=client.is_cloud_api(),
                emitter=request.stream_emitter,
            )
        else:
            raw_response = await client._call_api(
                request.messages,
                enable_thinking=request.enable_thinking,
                response_model=request.response_model,
                raw_response_format=raw_response_format,
                timeout=request.timeout,
            )
        return _parse_openai_compatible_response(client, request.response_model, raw_response, mode)
    except StructuredOutputError:
        raise
    except Exception as exc:
        if raw_response is None:
            raise
        response_text, thinking_content, reasoning_tokens = _extract_response_metadata(client, raw_response)
        raise StructuredOutputError(
            str(exc),
            raw_response=raw_response,
            response_text=response_text,
            thinking_content=thinking_content,
            reasoning_tokens=reasoning_tokens,
        ) from exc


def _parse_openai_compatible_response[T: BaseModel](
    client: Any,
    response_model: type[T],
    raw_response: Any,
    mode: StructuredOutputMode,
) -> StructuredOutputResult[T]:
    """
    解析 OpenAI-compatible raw response。
    """
    if isinstance(raw_response, response_model):
        parsed = raw_response
        response_text = _dump_parsed_result(parsed)
        response_text_from_raw, thinking_content, reasoning_tokens = _extract_response_metadata(client, raw_response)
        return StructuredOutputResult(
            parsed=parsed,
            raw_response=raw_response,
            response_text=response_text_from_raw or response_text,
            thinking_content=thinking_content,
            reasoning_tokens=reasoning_tokens,
            mode=mode,
        )

    response_text, thinking_content, reasoning_tokens = _extract_response_metadata(client, raw_response)
    try:
        parsed = client._parse_structured_response(raw_response, response_model)
    except Exception as exc:
        raise StructuredOutputError(
            str(exc),
            raw_response=raw_response,
            response_text=response_text,
            thinking_content=thinking_content,
            reasoning_tokens=reasoning_tokens,
        ) from exc

    return StructuredOutputResult(
        parsed=parsed,
        raw_response=raw_response,
        response_text=response_text or _dump_parsed_result(parsed),
        thinking_content=thinking_content,
        reasoning_tokens=reasoning_tokens,
        mode=mode,
    )


def _extract_response_metadata(client: Any, response: Any) -> tuple[str, str | None, int | None]:
    """
    从 raw response 中提取审计和 token 账本需要的元信息。
    """
    response_text = ""
    thinking_content: str | None = None

    if response is not None and hasattr(response, "choices") and response.choices:
        message = response.choices[0].message
        extract_response_content = getattr(client, "_extract_response_content", None)
        if callable(extract_response_content):
            response_text, thinking_content = extract_response_content(message)
        else:
            content = getattr(message, "content", None)
            response_text = content if isinstance(content, str) else ""

    extract_reasoning_tokens = getattr(client, "_extract_reasoning_tokens", None)
    reasoning_tokens = extract_reasoning_tokens(response) if callable(extract_reasoning_tokens) else None
    return response_text or "", thinking_content, reasoning_tokens


def _dump_parsed_result(parsed: BaseModel) -> str:
    """
    将 Pydantic 响应转换为稳定文本。
    """
    try:
        return parsed.model_dump_json(ensure_ascii=False)
    except TypeError:
        return str(parsed.model_dump())


def _validate_json_output_prompt_contract(messages: list[dict[str, Any]]) -> None:
    """
    校验 JSON Output prompt 的最低合同。
    """
    joined = "\n".join(str(message.get("content", "")) for message in messages)
    if "json" not in joined.lower():
        raise StructuredOutputError("json_object mode requires prompt content to mention json")
