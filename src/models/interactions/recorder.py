"""
模型交互记录器

说明: 提供统一的 record_model_interaction 函数，替代各处重复的 _save_interaction 实现
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _normalize_reasoning_tokens(reasoning_tokens: int | None) -> int | None:
    """
    归一化 reasoning token 计数

    说明: 统一处理 None / 非法值 / 负数，避免把坏值直接写进数据库
    """
    if reasoning_tokens is None:
        return None
    try:
        normalized = int(reasoning_tokens)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 0 else None


def _derive_thinking_state(
    *,
    thinking_content: str | None,
    reasoning_tokens: int | None,
    requested_thinking: bool | None,
) -> str:
    """
    计算 thinking 可见性状态

    说明: 区分“有文本 think”“只有 reasoning token”“明确没有 think”
          与“当前链路拿不到足够证据”的 unknown，避免把未知静默记成 none
    """
    if thinking_content and thinking_content.strip():
        return "text"
    if reasoning_tokens is not None and reasoning_tokens > 0:
        return "tokens_only"
    if reasoning_tokens == 0 or requested_thinking is False:
        return "none"
    return "unknown"


def record_model_interaction(
    *,
    run_id: str | None,
    chunk_id: int | None,
    interaction_type: str,
    phase: str,
    attempt_number: int,
    messages: list[dict],
    response_text: str,
    thinking_content: str | None,
    reasoning_tokens: int | None = None,
    requested_thinking: bool | None = None,
    duration_ms: int,
    model_name: str | None,
    model_provider: str,
    status: str = "success",
    error_message: str | None = None,
    session: Session | None = None,
) -> None:
    """
    保存模型交互记录

    说明: 统一的模型交互记录保存函数，支持可选 session 参数

    Args:
        run_id: 运行ID，如果为 None 则直接返回
        chunk_id: Chunk ID，可为 None
        interaction_type: 交互类型（annotate/diagnose/disambiguate/dialogue_attribution）
        phase: 阶段名称（phase1/phase2/phase3/diagnose 等）
        attempt_number: 尝试次数
        messages: 消息列表
        response_text: 响应文本
        thinking_content: 思考内容，可为 None
        reasoning_tokens: reasoning token 数，可为 None
        requested_thinking: 本次调用是否显式请求 think，可为 None
        duration_ms: 耗时（毫秒）
        model_name: 模型名称，可为 None
        model_provider: 模型提供者（local/cloud）
        status: 交互状态（success/error）
        error_message: 错误信息，可为 None
        session: 可选的数据库 session，如果提供则使用，否则创建新 session
    """
    if not run_id:
        return

    try:
        from src.storage.repositories.model_interaction_repository import ModelInteractionRepository

        prompt_text = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])
        normalized_reasoning_tokens = _normalize_reasoning_tokens(reasoning_tokens)
        thinking_state = _derive_thinking_state(
            thinking_content=thinking_content,
            reasoning_tokens=normalized_reasoning_tokens,
            requested_thinking=requested_thinking,
        )

        if session is not None:
            repo = ModelInteractionRepository(session)
            repo.save_interaction(
                run_id=run_id,
                chunk_id=chunk_id,
                interaction_type=interaction_type,
                phase=phase,
                attempt_number=attempt_number,
                model_name=model_name,
                model_provider=model_provider,
                prompt=prompt_text,
                response=response_text,
                thinking=thinking_content,
                response_chars=len(response_text),
                thinking_chars=len(thinking_content) if thinking_content else 0,
                has_thinking=bool(thinking_content and thinking_content.strip()),
                reasoning_tokens=normalized_reasoning_tokens,
                thinking_state=thinking_state,
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
            )
        else:
            from src.storage.db import get_session_factory

            Session = get_session_factory()
            new_session = Session()
            try:
                repo = ModelInteractionRepository(new_session)
                repo.save_interaction(
                    run_id=run_id,
                    chunk_id=chunk_id,
                    interaction_type=interaction_type,
                    phase=phase,
                    attempt_number=attempt_number,
                    model_name=model_name,
                    model_provider=model_provider,
                    prompt=prompt_text,
                    response=response_text,
                    thinking=thinking_content,
                    response_chars=len(response_text),
                    thinking_chars=len(thinking_content) if thinking_content else 0,
                    has_thinking=bool(thinking_content and thinking_content.strip()),
                    reasoning_tokens=normalized_reasoning_tokens,
                    thinking_state=thinking_state,
                    status=status,
                    error_message=error_message,
                    duration_ms=duration_ms,
                )
            finally:
                new_session.close()
    except Exception as e:
        error_str = str(e).lower()
        if "foreignkeyviolation" in error_str or "外键约束" in error_str or "foreign key" in error_str:
            logger.debug(f"Skipping model interaction save due to foreign key constraint: {interaction_type}/{phase}")
        else:
            logger.warning(f"Failed to save model interaction ({interaction_type}/{phase}): {e}")


__all__ = ["record_model_interaction"]
