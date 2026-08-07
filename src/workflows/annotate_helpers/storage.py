"""
章节标注唯一完成事务
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
    CompletionPulledResult,
    CompletionResult,
    DialogueSpeakerResolution,
    EvidenceList,
    PulledResult,
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
    pulled_results: list[PulledResult],
    rows: list[CasePoolCase],
) -> None:
    """2026-08-07 用于确认全部 pulled 案例仍 active 且类型目标未变化"""
    case_ids = [result.case_id for result in pulled_results]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("pulled_results.case_id 不允许重复")
    rows_by_id = {row.id: row for row in rows}
    missing = [case_id for case_id in case_ids if case_id not in rows_by_id]
    if missing:
        raise ValueError(f"完成事务无法锁定全部 pulled 案例: {missing}")
    results_by_id = {result.case_id: result for result in pulled_results}
    for row in rows:
        result = results_by_id[row.id]
        if row.state != "active":
            raise ValueError(f"pulled 案例已不再 active: {row.id}")
        if row.case_type != result.type:
            raise ValueError(
                f"pulled 案例类型已变化: case_id={row.id} "
                f"expected={row.case_type} actual={result.type}"
            )
        if row.target_key != result.target_key or dict(row.target_ref) != result.target_ref:
            raise ValueError(f"pulled 案例稳定目标已变化: {row.id}")


def _save_success_audit(
    session: Session,
    *,
    result: AgentRunResult,
    anchor_chunk_id: int,
) -> None:
    """2026-08-07 用于在完成事务中写入最终成功模型与工具审计"""
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
                "initial_finish": result.audit.initial_finish.model_dump(mode="json"),
                "revision_payloads": result.audit.revision_payloads,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        response=result.finish.model_dump_json(),
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
    """2026-08-07 用于在完成事务中写入成功尝试的全部可信 Token 用量"""
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
    """2026-08-07 用于按已提交 finish 案例和解决映射回读完成结果"""
    annotation = session.execute(
        select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == run_id,
            ChapterAnnotationRecord.chapter_id == chapter_id,
        )
    ).scalar_one_or_none()
    if annotation is None:
        return None
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

    pushed_rows = list(
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
    pulled_results = [
        CompletionPulledResult(
            case_id=row.case_id,
            type=cast(CaseType, row.case_type),
            resolution=DialogueSpeakerResolution.model_validate(row.resolution),
            target_fact_id=row.target_fact_id,
            target_fact_revision=row.target_fact_revision,
        )
        for row in mapping_rows
    ]
    return CompletionResult(
        annotation_id=annotation.annotation_id,
        graph_version_id=graph_version.graph_version_id,
        chapter_id=annotation.chapter_id,
        pushed_cases=[completion_case_view(row) for row in pushed_rows],
        pulled_results=pulled_results,
    )


def _persist_foreshadowing(
    session: Session,
    *,
    result: AgentRunResult,
) -> None:
    """2026-08-07 用于把最终 finish 的伏笔事实投影到线程与命中表"""
    repository = ForeshadowingRepository(session)
    for chunk in result.finish.chunks:
        for foreshadowing in chunk.foreshadowings:
            repository.sync(
                run_id=result.run_id,
                chunk_id=chunk.chunk_id,
                foreshadowing=foreshadowing,
            )


def _persist_pushed_cases(
    session: Session,
    *,
    result: AgentRunResult,
    annotation_id: str,
    finish_facts_by_ref: dict,
) -> list[CompletionCase]:
    """2026-08-07 用于把最终未解决案例绑定实际对话事实后创建 active 记录"""
    repository = CasePoolRepository(session)
    completion_cases: list[CompletionCase] = []
    for pushed_case in result.pushed_cases:
        item_ref = str(pushed_case.target_ref.get("item_ref") or "")
        target_fact = finish_facts_by_ref.get(item_ref)
        if target_fact is None:
            raise ValueError(
                f"pushed case 目标 ref 未生成图事实: {pushed_case.target_key}"
            )
        content = dict(target_fact.content)
        if content.get("kind") != "dialogue" or content.get("speaker") is not None:
            raise ValueError(
                f"pushed dialogue_speaker 目标不是未解决对话: {pushed_case.target_key}"
            )
        enriched_case = pushed_case.model_copy(
            update={
                "target_ref": {
                    **pushed_case.target_ref,
                    "fact_id": target_fact.fact_id,
                    "fact_revision": target_fact.fact_revision,
                }
            }
        )
        row = repository.create_case(
            run_id=result.run_id,
            annotation_id=annotation_id,
            pushed_case=enriched_case,
            evidence=EvidenceList.model_validate(target_fact.evidence),
        )
        completion_cases.append(completion_case_view(row))
    return completion_cases


def _persist_pull_mappings(
    session: Session,
    *,
    result: AgentRunResult,
    annotation_id: str,
    pulled_facts_by_case_id: dict,
) -> list[CompletionPulledResult]:
    """2026-08-07 用于保存 pulled 案例与实际历史事实修订的解决映射"""
    repository = CaseResolutionMappingRepository(session)
    completion_results: list[CompletionPulledResult] = []
    for pulled_result in result.pulled_results:
        target_fact = pulled_facts_by_case_id.get(pulled_result.case_id)
        if target_fact is None:
            raise ValueError(f"pull 未生成历史事实修订: {pulled_result.case_id}")
        repository.add_mapping(
            run_id=result.run_id,
            annotation_id=annotation_id,
            pulled_result=pulled_result,
            target_fact=target_fact,
        )
        completion_results.append(
            CompletionPulledResult(
                case_id=pulled_result.case_id,
                type=pulled_result.type,
                resolution=pulled_result.resolution,
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
    """2026-08-07 用于原子提交 finish pull push 图版本审计和 Token 用量"""
    anchor_chunk_id = result.finish.chunks[0].chunk_id
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
            pulled_case_ids = [item.case_id for item in result.pulled_results]
            locked_rows = case_repository.lock_active_cases(
                result.run_id,
                pulled_case_ids,
            )
            _validate_locked_cases(
                pulled_results=result.pulled_results,
                rows=locked_rows,
            )

            annotation = ChapterAnnotationRepository(session).add_annotation(
                run_id=result.run_id,
                chapter_id=result.chapter_id,
                finish=result.finish,
                initial_finish=result.audit.initial_finish,
                revision_payloads=result.audit.revision_payloads,
            )
            graph_result = persist_completion_graph(
                session,
                annotation=annotation,
                pulled_results=result.pulled_results,
                authorized_text_chunk_ids=set(result.audit.authorized_text_chunk_ids),
                visible_graph_fact_refs=set(result.audit.visible_graph_fact_refs),
                visible_relation_ids=set(result.audit.visible_graph_relation_ids),
                visible_graph_entity_ids=set(result.audit.visible_graph_entity_ids),
            )
            pulled_completion = _persist_pull_mappings(
                session,
                result=result,
                annotation_id=annotation.annotation_id,
                pulled_facts_by_case_id=graph_result.pulled_facts_by_case_id,
            )
            case_repository.resolve_cases(locked_rows)
            pushed_completion = _persist_pushed_cases(
                session,
                result=result,
                annotation_id=annotation.annotation_id,
                finish_facts_by_ref=graph_result.finish_facts_by_ref,
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
                pushed_cases=pushed_completion,
                pulled_results=pulled_completion,
            )
        return completion
    finally:
        session.close()
