"""
章节标注 Agent 逐 chunk 运行入口与三次重试

审计: 每次尝试开启 agent_invocations 行，模型回合与工具调用通过
AgentTurnObserver 写入独立短事务；失败尝试同样保留完整审计记录。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from .errors import (
    AnnotationAgentError,
    AnnotationAuthorizationError,
    AnnotationConfigurationError,
    AnnotationInputError,
    AnnotationInvariantError,
    AnnotationRetryableError,
)
from .fact_graph import FactGraph
from .graph import build_annotation_graph
from .prompts import build_chunk_message, build_system_prompt
from .schema import AgentRunAudit, AgentRunResult, BoundChapterAnnotation
from .tools import AnnotationQueryService, AnnotationToolLedger, build_annotation_tools

if TYPE_CHECKING:
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.audit.recorder import AgentAuditRecorder
    from src.agents.stream import AgentStream


class AnnotationAgentRunError(AnnotationRetryableError):
    """2026-08-05 用于表示同一模型三次章节尝试均未成功"""


def _validate_chapter_identity(
    *,
    chapter_id: int,
    current_chunks: list[tuple[int, str]],
) -> None:
    """2026-08-07 用于在模型调用前校验章节身份和唯一真实 chunk 输入"""
    if chapter_id <= 0:
        raise AnnotationInputError("chapter_id 必须是真实非空正整数")
    if len(current_chunks) != 1:
        raise AnnotationInputError("章节 Agent 每章必须恰好一个 chunk（分组恒为 1 个）")
    chunk_id, chunk_text = current_chunks[0]
    if chunk_id < 0:
        raise AnnotationInputError("current chunk_id 不允许为负数")
    if not chunk_text:
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


def _model_provider(llm: Any) -> str:
    """2026-08-05 用于从模型地址稳定区分本地与云端审计来源"""
    raw_base_url = getattr(llm, "base_url", "") or getattr(llm, "openai_api_base", "") or ""
    base_url = str(raw_base_url)
    if base_url and "localhost" not in base_url and "127.0.0.1" not in base_url:
        return "cloud"
    return "local"


def _model_name(llm: Any) -> str | None:
    """2026-08-10 用于从模型对象稳定读取审计用模型名"""
    return str(getattr(llm, "model_name", None) or getattr(llm, "model", "") or None) or None


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
    from src.config import settings

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
    stream: AgentStream | None = None,
    graph_state: FactGraph | None = None,
    observer: AgentTurnObserver | None = None,
) -> AgentRunResult:
    """2026-08-10 用于以全新账本执行一次逐 chunk 章节 Agent 尝试"""
    from src.config import settings

    _set_session_read_only(session)
    query_service = query_service_factory(session)
    first_chunk_id, first_chunk_text = current_chunks[0]
    initial_cases, rotation_case_ids = query_service.find_initial_case_candidates(
        first_chunk_text,
        semantic_limit=50,
        rotation_limit=50,
    )
    allow_future_context = settings.models.annotation.allow_future_context
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=chapter_id,
        current_chunk_id=first_chunk_id,
        current_chunk_text=first_chunk_text,
        allow_future_context=allow_future_context,
        graph=graph_state,
    )
    ledger.register_initial_cases(initial_cases, rotation_case_ids)
    tools = build_annotation_tools(query_service, ledger)
    total_iteration_limit = max(1, settings.models.annotation.max_iterations) + 5
    graph = build_annotation_graph(
        llm,
        tools,
        ledger=ledger,
        max_iterations=total_iteration_limit,
        stream=stream,
        observer=observer,
    )
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
                chunk_total=1,
                chunk_text=first_chunk_text,
                candidates=ledger.dialogue_candidates,
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
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=ledger.annotation,
        resolved_cases=list(ledger.resolved_cases),
        pushed_cases=list(ledger.pushed_cases),
        audit=AgentRunAudit(
            allow_future_context=allow_future_context,
            write_revisions=list(ledger.write_revisions),
            rotation_case_ids=ledger.rotation_case_ids,
            authorized_text_chunk_ids=sorted(ledger.authorized_text_chunk_ids),
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
    novel_id: str = "default",
    llm: Any | None = None,
    stream: AgentStream | None = None,
    graph_state: FactGraph | None = None,
    audit_recorder: AgentAuditRecorder | None = None,
) -> AgentRunResult:
    """2026-08-10 用于按同一模型最多三次运行逐 chunk 章节 Agent，每次尝试独立审计"""
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.audit.recorder import AgentAuditRecorder
    from src.config import settings

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

    recorder = audit_recorder or AgentAuditRecorder(session_factory)
    model_name = _model_name(llm)
    model_provider = _model_provider(llm)
    if graph_state is not None:
        graph_state.begin_chapter()
    baseline_snapshot = graph_state.snapshot() if graph_state is not None else None
    failures: list[str] = []
    for attempt_number in range(1, configured_attempts + 1):
        read_session = session_factory()
        invocation_id = recorder.start_invocation(
            run_id=run_id,
            task_type="annotation",
            chapter_id=chapter_id,
            attempt_number=attempt_number,
            model_name=model_name,
            model_provider=model_provider,
        )
        observer = AgentTurnObserver(
            recorder,
            invocation_id=invocation_id,
            run_id=run_id,
            novel_id=novel_id,
            task_type="annotation",
            call_type="agent",
            model_name=model_name or "unknown",
            model_provider=model_provider,
        )
        if stream is not None:
            await stream.thinking(f"章节 {chapter_id} 标注尝试 {attempt_number}/{configured_attempts} 开始")
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
                stream=stream,
                graph_state=graph_state,
                observer=observer,
            )
        except (
            AnnotationInputError,
            AnnotationAuthorizationError,
            AnnotationConfigurationError,
            AnnotationInvariantError,
        ) as exc:
            if baseline_snapshot is not None:
                graph_state.restore(baseline_snapshot)  # type: ignore[union-attr]
            _close_read_session(read_session)
            recorder.finish_invocation(invocation_id, status="error", final_error=str(exc))
            raise
        except Exception as exc:  # noqa: BLE001
            if baseline_snapshot is not None:
                graph_state.restore(baseline_snapshot)  # type: ignore[union-attr]
            _close_read_session(read_session)
            failures.append(str(exc))
            recorder.finish_invocation(invocation_id, status="error", final_error=str(exc))
            if stream is not None:
                await stream.tool_call_failed("章节标注", str(exc))
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
        recorder.finish_invocation(invocation_id, status="success")
        if stream is not None:
            await stream.output(f"章节 {chapter_id} 标注完成（第 {attempt_number} 次尝试）")
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
