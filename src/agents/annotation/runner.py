"""
章节标注 Agent 逐 chunk 运行入口与三次重试
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.agents.usage import extract_agent_token_usage
from src.config import settings

from .errors import (
    AnnotationAgentError,
    AnnotationAuthorizationError,
    AnnotationConfigurationError,
    AnnotationInputError,
    AnnotationRetryableError,
)
from .graph import build_annotation_graph
from .prompts import build_chunk_message, build_system_prompt
from .schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    SuccessAudit,
    TokenUsageRecord,
)
from .tools import AnnotationQueryService, AnnotationToolLedger, build_annotation_tools


class AnnotationAgentRunError(AnnotationRetryableError):
    """2026-08-05 用于表示同一模型三次章节尝试均未成功"""


def _validate_chapter_identity(
    *,
    chapter_id: int,
    current_chunks: list[tuple[int, str]],
) -> None:
    """2026-08-07 用于在模型调用前校验章节身份和真实 chunk 输入"""
    if chapter_id <= 0:
        raise AnnotationInputError("chapter_id 必须是真实非空正整数")
    if not current_chunks:
        raise AnnotationInputError("current 必须包含完整章节 chunk")
    chunk_ids = [chunk_id for chunk_id, _text in current_chunks]
    if len(set(chunk_ids)) != len(chunk_ids):
        raise AnnotationInputError("current chunk_id 不允许重复")
    if any(chunk_id < 0 for chunk_id in chunk_ids):
        raise AnnotationInputError("current chunk_id 不允许为负数")
    if any(not chunk_text for _chunk_id, chunk_text in current_chunks):
        raise AnnotationInputError("current chunk 原文不能为空")


def validate_bound_annotation(
    annotation: BoundChapterAnnotation,
    *,
    chapter_id: int,
    current_chunks: list[tuple[int, str]],
) -> None:
    """2026-08-07 用于复核系统绑定标注完整覆盖真实 chunk 和对话原文"""
    if chapter_id <= 0:
        raise AnnotationInputError("chapter_id 必须为正整数")
    expected_ids = [chunk_id for chunk_id, _text in current_chunks]
    actual_ids = [chunk.chunk_id for chunk in annotation.chunks]
    if actual_ids != expected_ids:
        raise ValueError(
            "系统绑定 chunks 必须按原文顺序精确覆盖 current: "
            f"expected={expected_ids} actual={actual_ids}"
        )
    text_by_id = dict(current_chunks)
    for chunk in annotation.chunks:
        chunk_text = text_by_id[chunk.chunk_id]
        for dialogue in chunk.dialogues:
            if dialogue.end > len(chunk_text):
                raise ValueError(
                    f"系统对话位置超出原文: chunk_id={chunk.chunk_id}"
                )
            actual = chunk_text[dialogue.start : dialogue.end]
            if actual != dialogue.content:
                raise ValueError(
                    f"系统对话原文绑定不一致: chunk_id={chunk.chunk_id}"
                )


def _serialize_agent_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """2026-08-05 用于把完整模型与工具消息链转换为成功审计结构"""
    serialized: list[dict[str, Any]] = []
    for message in messages:
        payload: dict[str, Any] = {
            "role": str(getattr(message, "type", "unknown")),
            "content": getattr(message, "content", ""),
        }
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            payload["tool_calls"] = tool_calls
        tool_call_id = getattr(message, "tool_call_id", None)
        if tool_call_id:
            payload["tool_call_id"] = tool_call_id
        tool_name = getattr(message, "name", None)
        if tool_name:
            payload["tool_name"] = tool_name
        serialized.append(payload)
    return serialized


def _extract_token_usage_records(messages: list[Any], llm: Any) -> list[TokenUsageRecord]:
    """2026-08-05 用于收集成功尝试中每个模型响应的可信 Token 用量"""
    records: list[TokenUsageRecord] = []
    for message in messages:
        if getattr(message, "type", None) != "ai":
            continue
        usage = extract_agent_token_usage(message)
        if usage is None:
            continue
        response_metadata = getattr(message, "response_metadata", None)
        response_model = (
            response_metadata.get("model_name")
            if isinstance(response_metadata, dict)
            else None
        )
        records.append(
            TokenUsageRecord(
                model=str(
                    response_model
                    or getattr(llm, "model_name", None)
                    or getattr(llm, "model", "unknown")
                ),
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            )
        )
    return records


def _model_provider(llm: Any) -> str:
    """2026-08-05 用于从模型地址稳定区分本地与云端审计来源"""
    raw_base_url = getattr(llm, "base_url", "") or getattr(llm, "openai_api_base", "") or ""
    base_url = str(raw_base_url)
    if base_url and "localhost" not in base_url and "127.0.0.1" not in base_url:
        return "cloud"
    return "local"


def _set_session_read_only(session: Session) -> None:
    """2026-08-05 用于在 PostgreSQL Agent 查询会话中显式禁止写入"""
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        session.execute(text("SET TRANSACTION READ ONLY"))


def _close_read_session(session: Session) -> None:
    """2026-08-05 用于在返回 AgentRunResult 前结束只读事务并关闭连接"""
    try:
        session.rollback()
    finally:
        session.close()


def _retry_backoff_seconds(attempt_index: int) -> float:
    """2026-08-05 用于读取三次章节尝试之间固定的退避时间"""
    del attempt_index
    return max(0.0, settings.models.annotation.retry_backoff_ms / 1000.0)


async def _run_single_attempt(
    *,
    run_id: str,
    chapter_id: int,
    attempt_number: int,
    current_chunks: list[tuple[int, str]],
    novel_title: str | None,
    llm: Any,
    session: Session,
    query_service_factory: Callable[[Session], AnnotationQueryService],
) -> AgentRunResult:
    """2026-08-07 用于以全新账本执行一次逐 chunk 章节 Agent 尝试"""
    started_at = time.perf_counter()
    _set_session_read_only(session)
    query_service = query_service_factory(session)
    initial_cases, rotation_case_ids = query_service.find_initial_case_candidates(
        "\n".join(chunk_text for _chunk_id, chunk_text in current_chunks),
        semantic_limit=50,
        rotation_limit=50,
    )
    allow_future_context = settings.models.annotation.allow_future_context
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=chapter_id,
        current_chunks=list(current_chunks),
        allow_future_context=allow_future_context,
    )
    ledger.register_initial_cases(initial_cases, rotation_case_ids)
    tools = build_annotation_tools(query_service, ledger)
    total_iteration_limit = (
        max(1, settings.models.annotation.max_iterations)
        * max(1, len(current_chunks))
        + 5
    )
    graph = build_annotation_graph(
        llm,
        tools,
        ledger=ledger,
        max_iterations=total_iteration_limit,
    )
    first_chunk_id, first_chunk_text = current_chunks[0]
    initial_messages = [
        SystemMessage(
            content=build_system_prompt(
                novel_title=novel_title,
                initial_cases=ledger.initial_case_views(),
                allow_future_context=allow_future_context,
            )
        ),
        HumanMessage(
            content=build_chunk_message(
                chunk_index=1,
                chunk_total=len(current_chunks),
                chunk_text=first_chunk_text,
                candidates=ledger.dialogue_candidates[first_chunk_id],
            )
        ),
    ]
    result_state = await graph.ainvoke(
        {
            "messages": initial_messages,
            "phase": "chunk_open",
            "iterations": 0,
            "error": None,
        }
    )
    error = result_state.get("error")
    if error:
        raise AnnotationRetryableError(str(error))
    if result_state.get("phase") != "completed" or ledger.annotation is None:
        raise AnnotationRetryableError("annotation LangGraph 未正常完成章节")

    validate_bound_annotation(
        ledger.annotation,
        chapter_id=chapter_id,
        current_chunks=current_chunks,
    )
    messages = list(result_state.get("messages") or initial_messages)
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=ledger.annotation,
        resolved_cases=list(ledger.resolved_cases),
        pending_cases=list(ledger.pending_cases),
        audit=AgentRunAudit(
            allow_future_context=allow_future_context,
            write_revisions=list(ledger.write_revisions),
            rotation_case_ids=ledger.rotation_case_ids,
            authorized_text_chunk_ids=sorted(ledger.authorized_text_chunk_ids),
            success=SuccessAudit(
                attempt_number=attempt_number,
                messages=_serialize_agent_messages(messages),
                tool_calls=ledger.audit_payload(),
                model_name=(
                    str(getattr(llm, "model_name", None) or getattr(llm, "model", ""))
                    or None
                ),
                model_provider=_model_provider(llm),
                duration_ms=elapsed_ms,
            ),
            token_usage=_extract_token_usage_records(messages, llm),
        ),
    )


async def run_annotation_agent(
    *,
    run_id: str,
    chapter_id: int,
    current_chunks: list[tuple[int, str]],
    query_service_factory: Callable[[Session], AnnotationQueryService],
    session_factory: Callable[[], Session],
    novel_title: str | None = None,
    llm: Any | None = None,
) -> AgentRunResult:
    """2026-08-07 用于按同一模型最多三次运行逐 chunk 章节 Agent"""
    _validate_chapter_identity(
        chapter_id=chapter_id,
        current_chunks=current_chunks,
    )
    configured_attempts = settings.models.annotation.total_attempts
    if configured_attempts != 3:
        raise AnnotationConfigurationError("章节 Agent total_attempts 必须固定为 3")
    if int(settings.models.annotation.retry_backoff_ms) != 5000:
        raise AnnotationConfigurationError(
            "章节 Agent retry_backoff_seconds 必须固定为 5000（毫秒）"
        )
    if llm is None:
        from src.agents.llm import build_chat_model

        llm = build_chat_model("annotation")

    failures: list[str] = []
    for attempt_number in range(1, configured_attempts + 1):
        read_session = session_factory()
        try:
            result = await _run_single_attempt(
                run_id=run_id,
                chapter_id=chapter_id,
                attempt_number=attempt_number,
                current_chunks=current_chunks,
                novel_title=novel_title,
                llm=llm,
                session=read_session,
                query_service_factory=query_service_factory,
            )
        except (AnnotationInputError, AnnotationAuthorizationError, AnnotationConfigurationError):
            _close_read_session(read_session)
            raise
        except Exception as exc:  # noqa: BLE001
            _close_read_session(read_session)
            failures.append(str(exc))
            logger.warning(
                "annotation chapter attempt failed run_id={} chapter_id={} attempt={}/{} error={}",
                run_id,
                chapter_id,
                attempt_number,
                configured_attempts,
                exc,
            )
            if attempt_number >= configured_attempts:
                break
            await asyncio.sleep(_retry_backoff_seconds(attempt_number - 1))
            continue
        _close_read_session(read_session)
        return result

    raise AnnotationAgentRunError(
        f"章节 Agent 连续 {configured_attempts} 次失败: "
        + json.dumps(failures, ensure_ascii=False)
    )


__all__ = [
    "AnnotationAgentError",
    "AnnotationAgentRunError",
    "AgentRunResult",
    "run_annotation_agent",
    "validate_bound_annotation",
]
