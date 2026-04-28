"""
BaseModelClient token 记账辅助模块

说明: 从 base.py 中拆出 token 使用量估算、补记与 novel_id 解析逻辑
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.utils.token_counter import count_messages_tokens, count_tokens


def resolve_token_usage_novel_id(client: Any, call_type: str) -> str | None:
    """
    解析 token 记账使用的 novel_id
    """
    novel_id = getattr(client, "_novel_id", None)
    if novel_id:
        return novel_id
    logger.warning(
        "skip token usage recording because novel_id is missing: task_type={} call_type={}",
        client._task_type,
        call_type,
    )
    return None


def extract_reasoning_tokens(response: Any) -> int | None:
    """
    从响应对象中提取 reasoning token 数
    """

    def _read_attr_or_key(obj: Any, name: str) -> Any:
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)

    usage = _read_attr_or_key(response, "usage")
    completion_details = _read_attr_or_key(usage, "completion_tokens_details")
    reasoning_tokens = _read_attr_or_key(completion_details, "reasoning_tokens")
    if reasoning_tokens is None:
        return None
    try:
        normalized = int(reasoning_tokens)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 0 else None


def record_token_usage(client: Any, response: Any, call_type: str, chunk_id: int | None = None) -> None:
    """
    记录 provider 返回的 token 用量
    """
    resolved_novel_id = resolve_token_usage_novel_id(client, call_type)
    if resolved_novel_id is None:
        return
    if client._token_usage_callback and hasattr(response, "usage") and response.usage:
        client._token_usage_callback(
            resolved_novel_id,
            client._task_type,
            call_type,
            client._config.model or "unknown",
            response.usage.prompt_tokens,
            response.usage.total_tokens,
            response.usage.completion_tokens,
            chunk_id,
        )


def record_token_usage_estimated(
    client: Any,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    call_type: str,
    chunk_id: int | None = None,
) -> None:
    """
    写入估算 token 用量
    """
    resolved_novel_id = resolve_token_usage_novel_id(client, call_type)
    if resolved_novel_id is None:
        return
    if client._token_usage_callback:
        client._token_usage_callback(
            resolved_novel_id,
            client._task_type,
            call_type,
            client._config.model or "unknown",
            prompt_tokens,
            total_tokens,
            completion_tokens,
            chunk_id,
        )


def record_estimated_token_usage_from_messages(
    client: Any,
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
    """
    if not client._token_usage_callback:
        return
    resolved_novel_id = resolve_token_usage_novel_id(client, call_type)
    if resolved_novel_id is None:
        return

    resolved_model = model_name or client._config.model
    if not resolved_model:
        logger.warning(
            "skip estimated token usage because model name is missing: task_type={} call_type={}",
            task_type,
            call_type,
        )
        return

    prompt_tokens = count_messages_tokens(messages, resolved_model)
    completion_tokens = count_tokens(response_text or "", resolved_model)
    total_tokens = prompt_tokens + completion_tokens

    # 这里显式传 model/task_type，避免共享 callback 再偷用 annotation client
    # 的模型名，把 disambiguation / fallback / embedding 的账混写到同一个 model 维度
    client._token_usage_callback(
        resolved_novel_id,
        task_type or client._task_type,
        call_type,
        resolved_model,
        prompt_tokens,
        total_tokens,
        completion_tokens,
        chunk_id,
    )


def extract_response_text_for_token_usage(client: Any, response: Any) -> str:
    """
    从响应对象中提取可用于 token 估算的文本
    """
    if response is None or not hasattr(response, "choices") or not response.choices:
        return ""

    message = response.choices[0].message
    try:
        content_clean, _thinking_content = client._extract_response_content(message)
        return content_clean or ""
    except Exception:
        raw_content = getattr(message, "content", None)
        return raw_content if isinstance(raw_content, str) else ""


def record_estimated_token_usage_from_response(
    client: Any,
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
    """
    response_text = extract_response_text_for_token_usage(client, response)
    record_estimated_token_usage_from_messages(
        client,
        messages,
        response_text,
        call_type,
        chunk_id,
        task_type=task_type,
        model_name=model_name,
    )
