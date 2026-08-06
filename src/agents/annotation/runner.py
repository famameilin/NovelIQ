"""
章节标注 Agent 运行入口与三次重试
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Iterator
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
from .prompts import build_system_prompt
from .schema import (
    AgentRunResult,
    ChapterAnnotation,
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
    """2026-08-06 用于在模型调用前校验章节身份与 current chunk 锚点"""
    if chapter_id <= 0:
        raise AnnotationInputError("chapter_id 必须是真实非空正整数")
    if not current_chunks:
        raise AnnotationInputError("current 必须包含完整章节 chunk")
    chunk_ids = [chunk_id for chunk_id, _text in current_chunks]
    if len(set(chunk_ids)) != len(chunk_ids):
        raise AnnotationInputError("current chunk_id 不允许重复")
    if any(chunk_id < 0 for chunk_id in chunk_ids):
        raise AnnotationInputError("current chunk_id 不允许为负数")
    if any(not text for _chunk_id, text in current_chunks):
        raise AnnotationInputError("current chunk 原文不能为空")


def _iter_annotation_evidence(annotation: ChapterAnnotation):
    """2026-08-05 用于按固定章节事实字段遍历唯一 Evidence"""
    for field_name in ("characters", "locations", "dialogues", "events", "relations", "states"):
        for fact in getattr(annotation, field_name):
            yield fact.evidence


def _iter_representative_node_ids(annotation: ChapterAnnotation) -> Iterator[str]:
    """2026-08-06 用于遍历正式关系标注引用的既有图实体节点 ID"""
    for relation in annotation.relations:
        selector = relation.representative_node
        if selector is not None and selector.node_id is not None:
            yield selector.node_id


def validate_chapter_annotation(
    annotation: ChapterAnnotation,
    *,
    chapter_id: int,
    current_chunks: list[tuple[int, str]],
    allowed_evidence_chapter_ids: set[int],
    visible_graph_entity_node_ids: set[str],
) -> None:
    """2026-08-05 用于完整校验章节 chunk 覆盖事实锚点原文与 Evidence 可见性"""
    expected_chunk_ids = [chunk_id for chunk_id, _text in current_chunks]
    actual_chunk_ids = [segment.chunk_id for segment in annotation.segments]
    if actual_chunk_ids != expected_chunk_ids:
        raise ValueError(
            f"segments 必须按原文顺序精确覆盖 current chunks: expected={expected_chunk_ids} actual={actual_chunk_ids}"
        )

    chunk_text_by_id = dict(current_chunks)
    for field_name in ("characters", "locations", "dialogues", "events", "relations", "states"):
        for fact in getattr(annotation, field_name):
            if fact.chunk_id not in chunk_text_by_id:
                raise ValueError(f"{field_name} 事实锚定了非 current chunk: {fact.chunk_id}")

    for dialogue in annotation.dialogues:
        if dialogue.content not in chunk_text_by_id[dialogue.chunk_id]:
            raise ValueError(f"dialogue.content 未逐字出现在锚定 current chunk: {dialogue.content!r}")

    for evidence in _iter_annotation_evidence(annotation):
        if evidence.chapterid not in allowed_evidence_chapter_ids:
            raise AnnotationAuthorizationError(
                f"Evidence chapterid 不在当前阶段可见范围: {evidence.chapterid}"
            )
    for node_id in _iter_representative_node_ids(annotation):
        if node_id not in visible_graph_entity_node_ids:
            raise AnnotationAuthorizationError(
                f"representative_node.node_id 未由本轮图 search 返回: {node_id}"
            )
    if chapter_id not in allowed_evidence_chapter_ids:
        raise AnnotationAuthorizationError("当前章节不在 Evidence 可见范围")


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
    """2026-08-05 用于收集本次成功尝试中每个模型响应的可信 Token 用量"""
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


def _build_current_message(current_chunks: list[tuple[int, str]]) -> str:
    """2026-08-05 用于把完整 current 章节按持久化 chunk 顺序送入同一次模型调用"""
    blocks = [
        f"<CurrentChunk chapter_chunk_id=\"{chunk_id}\">\n{chunk_text}\n</CurrentChunk>"
        for chunk_id, chunk_text in current_chunks
    ]
    return "<CurrentChapter>\n" + "\n\n".join(blocks) + "\n</CurrentChapter>"


def _retry_backoff_seconds(attempt_index: int) -> float:
    """2026-08-05 用于读取三次章节尝试之间固定的 1 秒与 2 秒退避"""
    backoffs = settings.analysis.agents.annotation.retry_backoff_seconds
    if attempt_index < len(backoffs):
        return max(0.0, float(backoffs[attempt_index]))
    return 0.0


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
    """2026-08-05 用于以全新图账本和只读查询服务执行一次章节 Agent 尝试"""
    started_at = time.perf_counter()
    _set_session_read_only(session)
    query_service = query_service_factory(session)
    initial_cases, rotation_case_ids = query_service.find_initial_case_candidates(
        "\n".join(chunk_text for _chunk_id, chunk_text in current_chunks),
        semantic_limit=50,
        rotation_limit=50,
    )
    ledger = AnnotationToolLedger(
        current_chapter_id=chapter_id,
        current_chunk_ids=tuple(chunk_id for chunk_id, _text in current_chunks),
    )
    ledger.register_initial_cases(initial_cases, rotation_case_ids)
    tools = build_annotation_tools(query_service, ledger)

    def initial_validator(annotation: ChapterAnnotation, allowed_chapters: set[int]) -> None:
        """2026-08-05 用于校验 after 不可读时的完整初始章节候选"""
        validate_chapter_annotation(
            annotation,
            chapter_id=chapter_id,
            current_chunks=current_chunks,
            allowed_evidence_chapter_ids=allowed_chapters,
            visible_graph_entity_node_ids=ledger.visible_graph_entity_node_ids,
        )

    def post_after_validator(annotation: ChapterAnnotation, allowed_chapters: set[int]) -> None:
        """2026-08-05 用于校验后文检索后仍只描述 current 的最终候选"""
        validate_chapter_annotation(
            annotation,
            chapter_id=chapter_id,
            current_chunks=current_chunks,
            allowed_evidence_chapter_ids=allowed_chapters,
            visible_graph_entity_node_ids=ledger.visible_graph_entity_node_ids,
        )

    graph = build_annotation_graph(
        llm,
        tools,
        ledger=ledger,
        max_iterations=max(1, settings.analysis.agents.annotation.max_iterations),
        initial_validator=initial_validator,
        post_after_validator=post_after_validator,
    )
    initial_messages = [
        SystemMessage(
            content=build_system_prompt(
                novel_title=novel_title,
                chapter_id=chapter_id,
                chunk_ids=[chunk_id for chunk_id, _text in current_chunks],
                initial_cases=initial_cases,
            )
        ),
        HumanMessage(content=_build_current_message(current_chunks)),
    ]
    initial_state = {
        "messages": initial_messages,
        "phase": "running_current",
        "iterations": 0,
        "candidate": None,
        "initial_finish": None,
        "final_annotation": None,
        "revision_payload": {},
        "error": None,
    }
    result_state = await graph.ainvoke(initial_state)
    error = result_state.get("error")
    if error:
        raise AnnotationRetryableError(str(error))
    if result_state.get("phase") != "completed":
        raise AnnotationRetryableError("annotation LangGraph 未正常到达 END")
    initial_finish_payload = result_state.get("initial_finish")
    final_annotation_payload = result_state.get("final_annotation")
    if initial_finish_payload is None or final_annotation_payload is None:
        raise AnnotationRetryableError("annotation LangGraph 缺少完整初始或最终章节标注")

    messages = list(result_state.get("messages") or initial_messages)
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    initial_finish = ChapterAnnotation.model_validate(initial_finish_payload)
    final_annotation = ChapterAnnotation.model_validate(final_annotation_payload)
    ledger.validate_staged_outputs()
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        final_annotation=final_annotation,
        initial_finish=initial_finish,
        revision_payload=dict(result_state.get("revision_payload") or {}),
        initial_case_candidate_ids=list(ledger.initial_cases),
        rotation_case_ids=ledger.rotation_case_ids,
        pulled_case_ids=ledger.pulled_case_ids,
        staged_outputs=ledger.staged_outputs,
        success_audit=SuccessAudit(
            attempt_number=attempt_number,
            messages=_serialize_agent_messages(messages),
            tool_calls=ledger.audit_payload(),
            model_name=str(getattr(llm, "model_name", None) or getattr(llm, "model", "")) or None,
            model_provider=_model_provider(llm),
            duration_ms=elapsed_ms,
        ),
        token_usage=_extract_token_usage_records(messages, llm),
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
    """2026-08-05 用于按同一模型最多三次运行完整章节 Agent 并在第三次失败后终止"""
    _validate_chapter_identity(
        chapter_id=chapter_id,
        current_chunks=current_chunks,
    )
    configured_attempts = settings.analysis.agents.annotation.total_attempts
    if configured_attempts != 3:
        raise AnnotationConfigurationError("章节 Agent total_attempts 必须固定为 3")
    if tuple(settings.analysis.agents.annotation.retry_backoff_seconds) != (1.0, 2.0):
        raise AnnotationConfigurationError("章节 Agent retry_backoff_seconds 必须固定为 [1, 2]")
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
    "validate_chapter_annotation",
]
