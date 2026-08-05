"""Agent 模型调用 Token 记账"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass(frozen=True, slots=True)
class AgentTokenUsage:
    """Agent 单次模型响应的统一 Token 用量"""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


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
    return AgentTokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def record_agent_token_usage(
    *,
    session: Any,
    run_id: str | None,
    novel_id: str,
    task_type: str,
    call_type: str,
    chunk_id: int | None,
    llm: Any,
    messages: list[Any],
) -> None:
    """
    2026-08-04 用于将每次有可信用量的 Agent 模型响应写入 token_usage
    """
    if session is None or not run_id:
        return

    from src.storage.repositories import StatsRepository

    stats_repo = StatsRepository(session)
    for message in messages:
        if getattr(message, "type", None) != "ai":
            continue
        usage = extract_agent_token_usage(message)
        if usage is None:
            continue
        response_metadata = getattr(message, "response_metadata", None)
        response_model = response_metadata.get("model_name") if isinstance(response_metadata, Mapping) else None
        model_name = str(response_model or getattr(llm, "model_name", None) or getattr(llm, "model", "unknown"))
        try:
            stats_repo.insert_token_usage(
                run_id=run_id,
                novel_id=novel_id,
                task_type=task_type,
                call_type=call_type,
                model=model_name,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                chunk_id=chunk_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to record agent token usage: {}", exc)
