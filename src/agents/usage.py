"""Agent 模型调用 Token 记账"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.utils.token_counter import count_tokens

if TYPE_CHECKING:
    from src.models.local.embedding import TokenUsageCallback


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
    """
    2026-08-04 用于从不同 OpenAI 兼容响应字段稳定读取非负 Token 数
    """
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
    """
    2026-08-10 用于读取可选的非负整数值，缺失或非法时返回 None
    """
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
    """
    2026-08-10 用于从嵌套字典读取可选整数值
    """
    nested = payload.get(outer_key)
    if not isinstance(nested, Mapping):
        return None
    return _read_optional_int(nested, (inner_key,))


def _read_cost(payload: Mapping[str, Any]) -> float | None:
    """
    2026-08-10 用于读取网关返回的费用，字符串转 float，失败时返回 None
    """
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
    """
    2026-08-04 用于从 LangChain AIMessage 提取可信的 Provider Token 用量
    """
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


def estimate_agent_token_usage(messages: list[Any]) -> list[AgentTokenUsage]:
    """
    2026-08-10 用于在 Provider 未返回用量时为每个 AI 响应按消息文本估算 Token 数

    估算口径: prompt 用 tiktoken 计数（中文 cl100k_base 按 2 字符/token 兜底），
    completion 按响应文本计数，缓存命中记 0（无缓存证据 = 全量计费），费用留 NULL
    """
    prompt_parts = [
        str(getattr(message, "content", "") or "")
        for message in messages
        if getattr(message, "type", None) != "ai"
    ]
    prompt_tokens = count_tokens("\n\n".join(prompt_parts))
    estimated: list[AgentTokenUsage] = []
    for message in messages:
        if getattr(message, "type", None) != "ai":
            continue
        completion_tokens = count_tokens(str(getattr(message, "content", "") or ""))
        estimated.append(
            AgentTokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                cache_read_tokens=0,
                cost=None,
                estimated=True,
            )
        )
    return estimated


def build_token_usage_callback(*, session: Any, run_id: str) -> TokenUsageCallback:
    """
    2026-08-10 用于构造 EmbeddingClient 可用的 token 用量回调，逐笔落入 token_usage
    """
    from src.storage.repositories import StatsRepository

    stats_repo = StatsRepository(session)

    def callback(
        novel_id: str,
        task_type: str,
        call_type: str,
        model: str,
        prompt_tokens: int,
        total_tokens: int,
        completion_tokens: int | None,
        chunk_id: int | None,
    ) -> None:
        try:
            stats_repo.insert_token_usage(
                run_id=run_id,
                novel_id=novel_id,
                task_type=task_type,
                call_type=call_type,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                chunk_id=chunk_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to record embedding token usage: {}", exc)

    return callback
