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
    AgentRunAudit,
    AgentRunResult,
    ChapterFinish,
    EntityType,
    Evidence,
    GraphEvidence,
    PushedCase,
    SuccessAudit,
    TextEvidence,
    TokenUsageRecord,
)
from .tools import AnnotationQueryService, AnnotationToolLedger, build_annotation_tools

_ENTITY_FIELDS: tuple[tuple[str, EntityType], ...] = (
    ("characters", "character"),
    ("locations", "location"),
    ("objects", "object"),
    ("organizations", "organization"),
)
_FACT_FIELDS = (
    "character_observations",
    "location_observations",
    "dialogues",
    "events",
    "relations",
    "states",
    "foreshadowings",
)
_LOCATION_TARGET_RELATION_TYPES = {
    "located_at",
    "entered",
    "enter",
    "arrived_at",
    "inside",
    "at",
    "left",
    "departed_from",
}


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
    if any(not chunk_text for _chunk_id, chunk_text in current_chunks):
        raise AnnotationInputError("current chunk 原文不能为空")


def _iter_finish_evidence(finish: ChapterFinish) -> Iterator[Evidence]:
    """2026-08-07 用于遍历实体目录和逐 chunk 标注项的全部 Evidence"""
    for field_name, _entity_type in _ENTITY_FIELDS:
        for entity in getattr(finish.entities, field_name):
            yield from entity.evidence
    for chunk in finish.chunks:
        for field_name in _FACT_FIELDS:
            for fact in getattr(chunk, field_name):
                yield from fact.evidence


def _validate_text_span(
    *,
    chunk_text_by_id: dict[int, str],
    chunk_id: int,
    start: int,
    end: int,
    expected_text: str,
    label: str,
) -> None:
    """2026-08-07 用于校验 current 原文中的稳定字符区间与逐字内容"""
    chunk_text = chunk_text_by_id.get(chunk_id)
    if chunk_text is None:
        raise ValueError(f"{label} 锚定了非 current chunk: {chunk_id}")
    if end > len(chunk_text):
        raise ValueError(f"{label} 的 end 超出 current 原文长度: {end}")
    actual_text = chunk_text[start:end]
    if actual_text != expected_text:
        raise ValueError(
            f"{label} 原文区间不匹配: expected={expected_text!r} actual={actual_text!r}"
        )


def _entity_type_for_endpoint(
    *,
    ref: str | None,
    existing_entity_id: int | None,
    entity_types_by_ref: dict[str, EntityType],
    visible_graph_entities: dict[int, EntityType],
    label: str,
) -> EntityType | None:
    """2026-08-07 用于解析并校验 finish 端点的实体类型和搜索授权"""
    if ref is not None:
        entity_type = entity_types_by_ref.get(ref)
        if entity_type is None:
            raise ValueError(f"{label} 引用了 entities 中不存在的 ref: {ref}")
        return entity_type
    if existing_entity_id is not None:
        entity_type = visible_graph_entities.get(existing_entity_id)
        if entity_type is None:
            raise AnnotationAuthorizationError(
                f"{label} 的 existing_entity_id 未由本轮 search_graph 返回: "
                f"{existing_entity_id}"
            )
        return entity_type
    return None


def _require_entity_type(
    actual_type: EntityType | None,
    expected_type: EntityType,
    *,
    label: str,
) -> None:
    """2026-08-07 用于拒绝人物地点等强类型端点引用错误节点"""
    if actual_type != expected_type:
        raise ValueError(
            f"{label} 必须引用 {expected_type} 节点，实际为 {actual_type}"
        )


def _validate_entities(
    finish: ChapterFinish,
    *,
    chunk_text_by_id: dict[int, str],
    visible_graph_entities: dict[int, EntityType],
) -> dict[str, EntityType]:
    """2026-08-07 用于校验实体目录类型既有节点授权和 current mention"""
    entity_types_by_ref: dict[str, EntityType] = {}
    for field_name, expected_type in _ENTITY_FIELDS:
        for entity in getattr(finish.entities, field_name):
            entity_types_by_ref[entity.ref] = expected_type
            if entity.existing_entity_id is not None:
                visible_type = visible_graph_entities.get(entity.existing_entity_id)
                if visible_type is None:
                    raise AnnotationAuthorizationError(
                        "entities.existing_entity_id 未由本轮 search_graph 返回: "
                        f"{entity.existing_entity_id}"
                    )
                if visible_type != expected_type:
                    raise ValueError(
                        f"实体 {entity.ref} 声明为 {expected_type}，"
                        f"但 existing_entity_id 类型为 {visible_type}"
                    )
            for mention in entity.mentions:
                _validate_text_span(
                    chunk_text_by_id=chunk_text_by_id,
                    chunk_id=mention.chunk_id,
                    start=mention.start,
                    end=mention.end,
                    expected_text=mention.text,
                    label=f"entity {entity.ref} mention",
                )
    return entity_types_by_ref


def _validate_chunk_facts(
    finish: ChapterFinish,
    *,
    chunk_text_by_id: dict[int, str],
    entity_types_by_ref: dict[str, EntityType],
    visible_graph_entities: dict[int, EntityType],
    visible_graph_relation_ids: set[str],
    visible_setup_ids: set[str],
) -> None:
    """2026-08-07 用于校验逐 chunk 事实锚点端点类型和历史引用授权"""

    def endpoint_type(
        *,
        ref: str | None,
        existing_entity_id: int | None,
        label: str,
    ) -> EntityType | None:
        """2026-08-07 用于在当前事实校验中解析实体端点"""
        return _entity_type_for_endpoint(
            ref=ref,
            existing_entity_id=existing_entity_id,
            entity_types_by_ref=entity_types_by_ref,
            visible_graph_entities=visible_graph_entities,
            label=label,
        )

    for chunk in finish.chunks:
        chunk_text = chunk_text_by_id[chunk.chunk_id]
        for character_observation in chunk.character_observations:
            actual_type = endpoint_type(
                ref=character_observation.entity_ref,
                existing_entity_id=character_observation.entity_existing_entity_id,
                label=f"character_observation {character_observation.ref}",
            )
            _require_entity_type(actual_type, "character", label=character_observation.ref)

        for location_observation in chunk.location_observations:
            actual_type = endpoint_type(
                ref=location_observation.location_ref,
                existing_entity_id=location_observation.location_existing_entity_id,
                label=f"location_observation {location_observation.ref}",
            )
            _require_entity_type(actual_type, "location", label=location_observation.ref)

        for dialogue in chunk.dialogues:
            _validate_text_span(
                chunk_text_by_id=chunk_text_by_id,
                chunk_id=chunk.chunk_id,
                start=dialogue.start,
                end=dialogue.end,
                expected_text=dialogue.content,
                label=f"dialogue {dialogue.ref}",
            )
            speaker_type = endpoint_type(
                ref=dialogue.speaker_ref,
                existing_entity_id=dialogue.speaker_existing_entity_id,
                label=f"dialogue {dialogue.ref} speaker",
            )
            if speaker_type is not None:
                _require_entity_type(speaker_type, "character", label=dialogue.ref)

        for event in chunk.events:
            for participant in event.participants:
                endpoint_type(
                    ref=participant.entity_ref,
                    existing_entity_id=participant.entity_existing_entity_id,
                    label=f"event {event.ref} participant",
                )
            location_type = endpoint_type(
                ref=event.location_ref,
                existing_entity_id=event.location_existing_entity_id,
                label=f"event {event.ref} location",
            )
            if location_type is not None:
                _require_entity_type(location_type, "location", label=event.ref)

        for relation in chunk.relations:
            from_type = endpoint_type(
                ref=relation.from_ref,
                existing_entity_id=relation.from_existing_entity_id,
                label=f"relation {relation.ref} from",
            )
            to_type = endpoint_type(
                ref=relation.to_ref,
                existing_entity_id=relation.to_existing_entity_id,
                label=f"relation {relation.ref} to",
            )
            if relation.relation_id is not None and relation.relation_id not in visible_graph_relation_ids:
                raise AnnotationAuthorizationError(
                    f"relation_id 未由本轮 search_graph 返回: {relation.relation_id}"
                )
            if relation.relation_type.lower() in _LOCATION_TARGET_RELATION_TYPES:
                _require_entity_type(to_type, "location", label=relation.ref)
            if relation.relation_semantics == "same_character":
                _require_entity_type(from_type, "character", label=relation.ref)
                _require_entity_type(to_type, "character", label=relation.ref)
                representative_type = endpoint_type(
                    ref=relation.representative_ref,
                    existing_entity_id=relation.representative_existing_entity_id,
                    label=f"relation {relation.ref} representative",
                )
                if representative_type is not None:
                    _require_entity_type(representative_type, "character", label=relation.ref)

        for state in chunk.states:
            endpoint_type(
                ref=state.entity_ref,
                existing_entity_id=state.entity_existing_entity_id,
                label=f"state {state.ref} entity",
            )
            endpoint_type(
                ref=state.object_ref,
                existing_entity_id=state.object_existing_entity_id,
                label=f"state {state.ref} object",
            )

        for foreshadowing in chunk.foreshadowings:
            if (
                foreshadowing.linked_setup_id is not None
                and foreshadowing.linked_setup_id not in visible_setup_ids
            ):
                raise AnnotationAuthorizationError(
                    "linked_setup_id 未由本轮 search_pool 返回: "
                    f"{foreshadowing.linked_setup_id}"
                )

        if not isinstance(chunk_text, str):
            raise ValueError(f"current chunk 原文类型异常: {chunk.chunk_id}")


def validate_chapter_finish(
    finish: ChapterFinish,
    *,
    chapter_id: int,
    current_chunks: list[tuple[int, str]],
    authorized_text_chunk_ids: set[int],
    visible_graph_fact_refs: set[tuple[str, int]],
    visible_graph_entities: dict[int, EntityType],
    visible_graph_relation_ids: set[str],
    visible_setup_ids: set[str],
) -> None:
    """2026-08-07 用于校验 ChapterFinish 完整覆盖原文锚点和全部授权引用"""
    expected_chunk_ids = [chunk_id for chunk_id, _text in current_chunks]
    actual_chunk_ids = [chunk.chunk_id for chunk in finish.chunks]
    if actual_chunk_ids != expected_chunk_ids:
        raise ValueError(
            "chunks 必须按原文顺序精确覆盖 current chunks: "
            f"expected={expected_chunk_ids} actual={actual_chunk_ids}"
        )
    coverage_chunk_ids = [coverage.chunk_id for coverage in finish.coverage]
    if coverage_chunk_ids != expected_chunk_ids:
        raise ValueError(
            "coverage 必须按原文顺序精确覆盖 current chunks: "
            f"expected={expected_chunk_ids} actual={coverage_chunk_ids}"
        )

    chunk_text_by_id = dict(current_chunks)
    entity_types_by_ref = _validate_entities(
        finish,
        chunk_text_by_id=chunk_text_by_id,
        visible_graph_entities=visible_graph_entities,
    )
    _validate_chunk_facts(
        finish,
        chunk_text_by_id=chunk_text_by_id,
        entity_types_by_ref=entity_types_by_ref,
        visible_graph_entities=visible_graph_entities,
        visible_graph_relation_ids=visible_graph_relation_ids,
        visible_setup_ids=visible_setup_ids,
    )

    for evidence in _iter_finish_evidence(finish):
        if isinstance(evidence, TextEvidence):
            if evidence.chunk_id not in authorized_text_chunk_ids:
                raise AnnotationAuthorizationError(
                    f"TextEvidence 未经当前输入或 read_text 授权: chunk_id={evidence.chunk_id}"
                )
        elif isinstance(evidence, GraphEvidence):
            reference = (evidence.fact_id, evidence.fact_revision)
            if reference not in visible_graph_fact_refs:
                raise AnnotationAuthorizationError(
                    f"GraphEvidence 未由本轮 search_graph 或池记录授权: {reference}"
                )
    if chapter_id <= 0:
        raise AnnotationInputError("chapter_id 必须为正整数")


def _bind_pushed_cases(
    finish: ChapterFinish,
    ledger: AnnotationToolLedger,
) -> list[PushedCase]:
    """2026-08-07 用于把暂存 push 与最终未确认对话 ref 建立一一稳定绑定"""
    unresolved_dialogues = {
        (chunk.chunk_id, dialogue.ref): dialogue
        for chunk in finish.chunks
        for dialogue in chunk.dialogues
        if dialogue.speaker_ref is None and dialogue.speaker_existing_entity_id is None
    }
    bound_refs: set[tuple[int, str]] = set()
    pushed_cases: list[PushedCase] = []
    for staged in ledger.staged_push_cases:
        matches = [
            (chunk_id, item_ref, dialogue)
            for (chunk_id, item_ref), dialogue in unresolved_dialogues.items()
            if chunk_id == staged.chunkid
            and dialogue.start <= staged.target_anchor.start
            and dialogue.end >= staged.target_anchor.end
        ]
        if len(matches) != 1:
            raise ValueError(
                "dialogue_speaker push 必须唯一定位最终 finish 中 speaker 为空的对话: "
                f"target_key={staged.target_key} matches={len(matches)}"
            )
        chunk_id, item_ref, dialogue = matches[0]
        target = (chunk_id, item_ref)
        if target in bound_refs:
            raise ValueError(f"同一未解决对话不能被重复 push: {target}")
        bound_refs.add(target)
        pushed_cases.append(
            PushedCase(
                **staged.model_dump(mode="python"),
                target_ref={
                    "kind": "dialogue",
                    "item_ref": item_ref,
                    "chunk_id": chunk_id,
                    "start": dialogue.start,
                    "end": dialogue.end,
                    "text": dialogue.content,
                },
            )
        )

    missing = sorted(set(unresolved_dialogues) - bound_refs)
    if missing:
        raise ValueError(f"speaker 为空的对话必须各自 push 一个 dialogue_speaker 案例: {missing}")
    return pushed_cases


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
    """2026-08-07 用于以全新阶段图账本和只读服务执行一次章节 Agent 尝试"""
    started_at = time.perf_counter()
    _set_session_read_only(session)
    query_service = query_service_factory(session)
    initial_cases, rotation_case_ids = query_service.find_initial_case_candidates(
        "\n".join(chunk_text for _chunk_id, chunk_text in current_chunks),
        semantic_limit=50,
        rotation_limit=50,
    )
    allow_future_context = settings.analysis.agents.annotation.allow_future_context
    ledger = AnnotationToolLedger(
        current_chapter_id=chapter_id,
        current_chunks=dict(current_chunks),
        allow_future_context=allow_future_context,
    )
    ledger.register_initial_cases(initial_cases, rotation_case_ids)
    tools = build_annotation_tools(query_service, ledger, run_scope=run_id)

    def current_validator(finish: ChapterFinish) -> None:
        """2026-08-07 用于校验当前与已授权前文形成的完整章节候选"""
        validate_chapter_finish(
            finish,
            chapter_id=chapter_id,
            current_chunks=current_chunks,
            authorized_text_chunk_ids=ledger.authorized_text_chunk_ids,
            visible_graph_fact_refs=ledger.visible_graph_fact_refs,
            visible_graph_entities=ledger.visible_graph_entities,
            visible_graph_relation_ids=ledger.visible_graph_relation_ids,
            visible_setup_ids=ledger.visible_setup_ids,
        )

    def future_validator(finish: ChapterFinish) -> None:
        """2026-08-07 用于校验后文授权加入后仍只标注 current 的最终候选"""
        validate_chapter_finish(
            finish,
            chapter_id=chapter_id,
            current_chunks=current_chunks,
            authorized_text_chunk_ids=ledger.authorized_text_chunk_ids,
            visible_graph_fact_refs=ledger.visible_graph_fact_refs,
            visible_graph_entities=ledger.visible_graph_entities,
            visible_graph_relation_ids=ledger.visible_graph_relation_ids,
            visible_setup_ids=ledger.visible_setup_ids,
        )

    graph = build_annotation_graph(
        llm,
        tools,
        ledger=ledger,
        max_iterations=max(1, settings.analysis.agents.annotation.max_iterations),
        current_validator=current_validator,
        future_validator=future_validator,
    )
    initial_messages = [
        SystemMessage(
            content=build_system_prompt(
                novel_title=novel_title,
                chapter_id=chapter_id,
                chunk_ids=[chunk_id for chunk_id, _text in current_chunks],
                initial_cases=initial_cases,
                allow_future_context=allow_future_context,
            )
        ),
        HumanMessage(content=_build_current_message(current_chunks)),
    ]
    initial_state = {
        "messages": initial_messages,
        "phase": "current_open",
        "iterations": 0,
        "candidate": None,
        "initial_finish": None,
        "final_finish": None,
        "revision_payloads": [],
        "error": None,
    }
    result_state = await graph.ainvoke(initial_state)
    error = result_state.get("error")
    if error:
        raise AnnotationRetryableError(str(error))
    if result_state.get("phase") != "completed":
        raise AnnotationRetryableError("annotation LangGraph 未正常到达 END")
    initial_finish_payload = result_state.get("initial_finish")
    final_finish_payload = result_state.get("final_finish")
    if initial_finish_payload is None or final_finish_payload is None:
        raise AnnotationRetryableError("annotation LangGraph 缺少完整初始或最终 ChapterFinish")

    messages = list(result_state.get("messages") or initial_messages)
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    initial_finish = ChapterFinish.model_validate(initial_finish_payload)
    final_finish = ChapterFinish.model_validate(final_finish_payload)
    pushed_cases = _bind_pushed_cases(final_finish, ledger)
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        finish=final_finish,
        pulled_results=list(ledger.pulled_results),
        pushed_cases=pushed_cases,
        audit=AgentRunAudit(
            allow_future_context=allow_future_context,
            initial_finish=initial_finish,
            revision_payloads=list(result_state.get("revision_payloads") or []),
            initial_case_candidate_ids=list(ledger.initial_cases),
            rotation_case_ids=ledger.rotation_case_ids,
            authorized_text_chunk_ids=sorted(ledger.authorized_text_chunk_ids),
            visible_graph_fact_refs=sorted(ledger.visible_graph_fact_refs),
            visible_graph_entity_ids=sorted(ledger.visible_graph_entities),
            visible_graph_relation_ids=sorted(ledger.visible_graph_relation_ids),
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
    "validate_chapter_finish",
]
