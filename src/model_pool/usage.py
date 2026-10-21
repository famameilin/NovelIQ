"""Agent 模型调用 Token 记账"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.utils.token_counter import count_tokens

if TYPE_CHECKING:
    from src.embedding import TokenUsageCallback


@dataclass(frozen=True, slots=True)
class AgentTokenUsage:
    """Agent 单次模型响应的统一 Token 用量"""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cache_read_tokens: int | None = None
    cost: float | None = None
    estimated: bool = False
    reasoning_tokens: int | None = None


def _read_usage_count(payload: Mapping[str, Any], keys: tuple[str, ...]) -> int:
    """从不同 OpenAI 兼容响应字段稳定读取非负 Token 数"""
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0


def _read_optional_int(payload: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
    """读取可选的非负整数值，缺失或非法时返回 None"""
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            return parsed
    return None


def _read_nested_int(payload: Mapping[str, Any], outer_key: str, inner_key: str) -> int | None:
    """从嵌套字典读取可选整数值"""
    nested = payload.get(outer_key)
    if not isinstance(nested, Mapping):
        return None
    return _read_optional_int(nested, (inner_key,))


def _read_cost(payload: Mapping[str, Any]) -> float | None:
    """读取网关返回的费用，字符串转 float，失败时返回 None"""
    for key in ("cost", "total_cost"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def extract_agent_token_usage(message: Any) -> AgentTokenUsage | None:
    """从 LangChain AIMessage 提取可信的 Provider Token 用量"""
    payload = getattr(message, "usage_metadata", None)
    if not isinstance(payload, Mapping):
        response_metadata = getattr(message, "response_metadata", None)
        payload = response_metadata.get("token_usage") if isinstance(response_metadata, Mapping) else None
    if not isinstance(payload, Mapping):
        return None

    prompt_tokens = _read_usage_count(payload, ("input_tokens", "prompt_tokens"))
    completion_tokens = _read_usage_count(payload, ("output_tokens", "completion_tokens"))
    total_tokens = _read_usage_count(payload, ("total_tokens",))
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens
    if total_tokens <= 0:
        return None

    cache_read_tokens = _read_nested_int(payload, "input_token_details", "cache_read")
    if cache_read_tokens is None:
        cache_read_tokens = _read_optional_int(payload, ("prompt_cache_hit_tokens",))
    if cache_read_tokens is None:
        cache_read_tokens = _read_nested_int(payload, "prompt_tokens_details", "cached_tokens")
    reasoning_tokens = _read_nested_int(payload, "output_token_details", "reasoning")
    return AgentTokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cache_read_tokens=cache_read_tokens,
        cost=_read_cost(payload),
        reasoning_tokens=reasoning_tokens,
    )


def estimate_agent_token_usage(messages: list[Any], *, tool_schema_tokens: int = 0) -> list[AgentTokenUsage]:
    """按每次响应之前的完整消息、工具目录与实际响应估算，缓存和费用保持未知"""
    history_tokens = max(0, tool_schema_tokens)
    estimated: list[AgentTokenUsage] = []
    for message in messages:
        content = getattr(message, "content", "") or ""
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        additional = getattr(message, "additional_kwargs", None) or {}
        calls = getattr(message, "tool_calls", None) or additional.get("tool_calls")
        parts = [text]
        if calls:
            parts.append(json.dumps(calls, ensure_ascii=False, separators=(",", ":"), default=str))
        reasoning = additional.get("reasoning_content")
        if reasoning:
            parts.append(str(reasoning))
        message_tokens = count_tokens("\n".join(parts))
        if getattr(message, "type", None) == "ai":
            estimated.append(
                AgentTokenUsage(
                    prompt_tokens=history_tokens,
                    completion_tokens=message_tokens,
                    total_tokens=history_tokens + message_tokens,
                    estimated=True,
                )
            )
        routing = {key: value for key in ("type", "name", "tool_call_id")
                   if (value := getattr(message, key, None)) is not None}
        history_tokens += message_tokens + count_tokens(json.dumps(routing, separators=(",", ":")))
    return estimated


def build_token_usage_callback(*, bus: Any, run_id: str) -> TokenUsageCallback:
    """非 Agent 调用只发送实际 usage，由统计审计模块独立保存"""
    from src.event_bus import Message
    from src.storage import new_id

    agent_id = new_id()
    sequence = 0

    def callback(
        task_type: str,
        model: str,
        prompt_tokens: int,
        total_tokens: int,
        completion_tokens: int | None,
        chunk_id: int | None,
    ) -> None:
        nonlocal sequence
        sequence += 1
        bus.publish(
            Message(
                topic=f"audit:{run_id}",
                source="preprocess",
                target=f"audit:{run_id}",
                run_id=run_id,
                invocation_id=agent_id,
                message_id=f"{agent_id}:usage:{sequence}",
                payload={
                    "method": "nonagent_usage",
                    "local_id": sequence,
                    "kwargs": {
                        "run_id": run_id,
                        "task_type": task_type,
                        "call_type": task_type,
                        "model": model,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                        "chapter_id": chunk_id,
                        "accounting_source": "reported",
                    },
                },
            )
        )

    return callback
