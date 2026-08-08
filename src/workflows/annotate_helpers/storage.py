"""
章节语义标注唯一完成事务
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.annotation.schema import (
    AgentRunResult,
    CaseType,
    CompletionCase,
    CompletionResolvedCase,
    CompletionResult,
    ResolvedCase,
)
from src.storage.models import (
    CasePoolCase,
    CaseResolutionMapping,
    ChapterAnnotationRecord,
    GraphVersion,
)
from src.storage.repositories import (
    CasePoolRepository,
    CaseResolutionMappingRepository,
    ChapterAnnotationRepository,
    ForeshadowingRepository,
    StatsRepository,
)
from src.storage.repositories.annotation.continuity import completion_case_view
from src.storage.repositories.graph import persist_completion_graph
from src.storage.repositories.model_interaction_repository import ModelInteractionRepository


def _validate_locked_cases(
    *,
    resolved_cases: list[ResolvedCase],
    rows: list[CasePoolCase],
) -> None:
    """2026-08-07 用于确认全部解决案例仍 active 且稳定目标未变化"""
    case_ids = [result.case_id for result in resolved_cases]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("resolved_cases.case_id 不允许重复")
    rows_by_id = {row.id: row for row in rows}
    missing = [case_id for case_id in case_ids if case_id not in rows_by_id]
    if missing:
        raise ValueError(f"完成事务无法锁定全部 resolved cases: {missing}")
    results_by_id = {result.case_id: result for result in resolved_cases}
    for row in rows:
        result = results_by_id[row.id]
        if row.state != "active":
            raise ValueError(f"resolved case 已不再 active: {row.id}")
        if row.case_type != result.type:
            raise ValueError(
                f"resolved case 类型已变化: case_id={row.id} "
                f"expected={row.case_type} actual={result.type}"
            )
        if row.target_key != result.target_key or dict(row.target_ref) != result.target_ref:
            raise ValueError(f"resolved case 稳定目标已变化: {row.id}")


def _save_success_audit(
    session: Session,
    *,
    result: AgentRunResult,
    anchor_chunk_id: int,
) -> None:
    """2026-08-07 用于在完成事务中写入模型工具和领域修订审计"""
    success = result.audit.success
    ModelInteractionRepository(session).save_interaction(
        run_id=result.run_id,
        chunk_id=anchor_chunk_id,
        interaction_type="annotate",
        phase="chapter_agent",
        attempt_number=success.attempt_number,
        model_name=success.model_name,
        model_provider=success.model_provider,
        prompt=json.dumps(
            {
                "messages": success.messages,
                "tool_calls": success.tool_calls,
                "allow_future_context": result.audit.allow_future_context,
                "write_revisions": result.audit.write_revisions,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        response=result.annotation.model_dump_json(),
        duration_ms=success.duration_ms,
        status="success",
    )


def _save_token_usage(
    session: Session,
    *,
    result: AgentRunResult,
    novel_id: str,
    anchor_chunk_id: int,
) -> None:
    """2026-08-07 用于保存成功尝试的全部可信 Token 用量"""
    stats_repo = StatsRepository(session)
    for usage in result.audit.token_usage:
        stats_repo.insert_token_usage(
            run_id=result.run_id,
            novel_id=novel_id,
            task_type="annotation",
            call_type="agent",
            model=usage.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            chunk_id=anchor_chunk_id,
        )


def load_completion_result(
    session: Session,
    *,
    run_id: str,
    chapter_id: int,
) -> CompletionResult | None:
    """2026-08-07 用于按最新合同标注案例和解决映射回读完成结果"""
    annotation = session.execute(
        select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == run_id,
            ChapterAnnotationRecord.chapter_id == chapter_id,
        )
    ).scalar_one_or_none()
    if annotation is None:
        return None
    if annotation.payload.get("contract_version") != "agent-semantic-v1":
        raise ValueError(
            "章节标注使用旧合同，必须重新运行 annotation: "
            f"run_id={run_id} chapter_id={chapter_id}"
        )
    graph_version = session.execute(
        select(GraphVersion).where(
            GraphVersion.run_id == run_id,
            GraphVersion.chapter_id == chapter_id,
            GraphVersion.annotation_id == annotation.annotation_id,
        )
    ).scalar_one_or_none()
    if graph_version is None:
        raise ValueError(
            f"章节标注缺少唯一图版本: run_id={run_id} chapter_id={chapter_id}"
        )
    created_rows = list(
        session.execute(
            select(CasePoolCase)
            .where(
                CasePoolCase.run_id == run_id,
                CasePoolCase.created_by_annotation_id == annotation.annotation_id,
            )
            .order_by(CasePoolCase.created_at, CasePoolCase.id)
        ).scalars()
    )
    mapping_rows = list(
        session.execute(
            select(CaseResolutionMapping)
            .where(
                CaseResolutionMapping.run_id == run_id,
                CaseResolutionMapping.annotation_id == annotation.annotation_id,
            )
            .order_by(CaseResolutionMapping.created_at, CaseResolutionMapping.mapping_id)
        ).scalars()
    )
    resolved = [
        CompletionResolvedCase(
            case_id=row.case_id,
            type=cast(CaseType, row.case_type),
            speaker=str(row.resolution["speaker"]),
            reason=str(row.resolution["reason"]),
            target_fact_id=row.target_fact_id,
            target_fact_revision=row.target_fact_revision,
        )
        for row in mapping_rows
    ]
    return CompletionResult(
        annotation_id=annotation.annotation_id,
        graph_version_id=graph_version.graph_version_id,
        chapter_id=annotation.chapter_id,
        created_cases=[completion_case_view(row) for row in created_rows],
        resolved_cases=resolved,
    )


def _persist_foreshadowing(
    session: Session,
    *,
    result: AgentRunResult,
) -> None:
    """2026-08-07 用于把最终系统绑定伏笔投影到线程与命中表"""
    repository = ForeshadowingRepository(session)
    for chunk in result.annotation.chunks:
        for foreshadowing in chunk.foreshadowings:
            repository.sync(
                run_id=result.run_id,
                chunk_id=chunk.chunk_id,
                foreshadowing=foreshadowing,
            )


def _persist_pending_cases(
    session: Session,
    *,
    result: AgentRunResult,
    annotation_id: str,
    dialogue_facts_by_candidate_key: dict,
) -> list[CompletionCase]:
    """2026-08-07 用于把系统自动案例绑定实际对话事实后创建记录"""
    repository = CasePoolRepository(session)
    completion_cases: list[CompletionCase] = []
    for pending_case in result.pending_cases:
        candidate_key = str(pending_case.target_ref.get("candidate_key") or "")
        target_fact = dialogue_facts_by_candidate_key.get(candidate_key)
        if target_fact is None:
            raise ValueError(
                f"pending case 目标未生成对话事实: {pending_case.target_key}"
            )
        content = dict(target_fact.content)
        if content.get("kind") != "dialogue" or content.get("speaker") is not None:
            raise ValueError(
                f"pending dialogue_speaker 目标不是未解决对话: {pending_case.target_key}"
            )
        enriched = pending_case.model_copy(
            update={
                "target_ref": {
                    **pending_case.target_ref,
                    "fact_id": target_fact.fact_id,
                    "fact_revision": target_fact.fact_revision,
                }
            }
        )
        row = repository.create_case(
            run_id=result.run_id,
            annotation_id=annotation_id,
            pending_case=enriched,
        )
        completion_cases.append(completion_case_view(row))
    return completion_cases


def _persist_resolution_mappings(
    session: Session,
    *,
    result: AgentRunResult,
    annotation_id: str,
    resolved_facts_by_case_id: dict,
) -> list[CompletionResolvedCase]:
    """2026-08-07 用于保存案例解决与历史事实修订映射"""
    repository = CaseResolutionMappingRepository(session)
    completion_results: list[CompletionResolvedCase] = []
    for resolved_case in result.resolved_cases:
        target_fact = resolved_facts_by_case_id.get(resolved_case.case_id)
        if target_fact is None:
            raise ValueError(f"resolve_case 未生成历史事实修订: {resolved_case.case_id}")
        repository.add_mapping(
            run_id=result.run_id,
            annotation_id=annotation_id,
            resolved_case=resolved_case,
            target_fact=target_fact,
        )
        completion_results.append(
            CompletionResolvedCase(
                case_id=resolved_case.case_id,
                type=resolved_case.type,
                speaker=resolved_case.speaker,
                reason=resolved_case.reason,
                target_fact_id=target_fact.fact_id,
                target_fact_revision=target_fact.fact_revision,
            )
        )
    return completion_results


def complete_annotation_run(
    *,
    result: AgentRunResult,
    novel_id: str,
    session_factory: Callable[[], Session],
) -> CompletionResult:
    """2026-08-07 用于原子提交正式标注图版本连续性审计和 Token 用量"""
    anchor_chunk_id = result.annotation.chunks[0].chunk_id
    session = session_factory()
    try:
        with session.begin():
            existing = load_completion_result(
                session,
                run_id=result.run_id,
                chapter_id=result.chapter_id,
            )
            if existing is not None:
                return existing

            case_repository = CasePoolRepository(session)
            resolved_case_ids = [item.case_id for item in result.resolved_cases]
            locked_rows = case_repository.lock_active_cases(
                result.run_id,
                resolved_case_ids,
            )
            _validate_locked_cases(
                resolved_cases=result.resolved_cases,
                rows=locked_rows,
            )
            annotation = ChapterAnnotationRepository(session).add_annotation(
                run_id=result.run_id,
                chapter_id=result.chapter_id,
                annotation=result.annotation,
            )
            graph_result = persist_completion_graph(
                session,
                annotation=annotation,
                resolved_cases=result.resolved_cases,
                authorized_text_chunk_ids=set(result.audit.authorized_text_chunk_ids),
            )
            resolved_completion = _persist_resolution_mappings(
                session,
                result=result,
                annotation_id=annotation.annotation_id,
                resolved_facts_by_case_id=graph_result.resolved_facts_by_case_id,
            )
            case_repository.resolve_cases(locked_rows)
            created_completion = _persist_pending_cases(
                session,
                result=result,
                annotation_id=annotation.annotation_id,
                dialogue_facts_by_candidate_key=(
                    graph_result.dialogue_facts_by_candidate_key
                ),
            )
            _persist_foreshadowing(session, result=result)
            case_repository.mark_surfaced(
                run_id=result.run_id,
                ids=result.audit.rotation_case_ids,
                annotation_id=annotation.annotation_id,
            )
            _save_success_audit(
                session,
                result=result,
                anchor_chunk_id=anchor_chunk_id,
            )
            _save_token_usage(
                session,
                result=result,
                novel_id=novel_id,
                anchor_chunk_id=anchor_chunk_id,
            )
            completion = CompletionResult(
                annotation_id=annotation.annotation_id,
                graph_version_id=graph_result.graph_version.graph_version_id,
                chapter_id=result.chapter_id,
                created_cases=created_completion,
                resolved_cases=resolved_completion,
            )
        return completion
    finally:
        session.close()
