"""
章节标注唯一完成事务
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.annotation.schema import (
    AgentRunResult,
    CompletionCase,
    CompletionFact,
    CompletionForeshadowing,
    CompletionResult,
    Evidence,
    FactPayload,
    ForeshadowingPayload,
)
from src.storage.models import (
    CasePoolCase,
    CaseResolutionMapping,
    ChapterAnnotationRecord,
    ContinuityFact,
    ForeshadowingThread,
    ForeshadowingThreadHit,
)
from src.storage.repositories import (
    CasePoolRepository,
    CaseResolutionMappingRepository,
    ChapterAnnotationRepository,
    ContinuityFactRepository,
    ForeshadowingRepository,
    StatsRepository,
)
from src.storage.repositories.annotation.continuity import completion_case_view
from src.storage.repositories.model_interaction_repository import ModelInteractionRepository

from .graph_projection import project_graph_tables


def _validate_locked_sources(
    *,
    pulled_case_ids: list[str],
    rows: list[CasePoolCase],
) -> None:
    """2026-08-05 用于在写入前确认全部来源案例仍属于当前 run 且为 active"""
    rows_by_id = {row.id: row for row in rows}
    missing = [case_id for case_id in pulled_case_ids if case_id not in rows_by_id]
    if missing:
        raise ValueError(f"完成事务无法锁定全部来源案例: {missing}")
    inactive = [row.id for row in rows if row.state != "active"]
    if inactive:
        raise ValueError(f"来源案例已不再 active: {inactive}")


def _mapping_sources(source_case_ids: list[str]) -> list[str | None]:
    """2026-08-05 用于保证直接发现的输出也写一条 source_case_id 为空的映射"""
    return list(source_case_ids) if source_case_ids else [None]


def _save_success_audit(
    session: Session,
    *,
    result: AgentRunResult,
    anchor_chunk_id: int,
) -> None:
    """2026-08-05 用于在完成事务中写入最终成功模型与工具审计"""
    audit = result.success_audit
    ModelInteractionRepository(session).save_interaction(
        run_id=result.run_id,
        chunk_id=anchor_chunk_id,
        interaction_type="annotate",
        phase="chapter_agent",
        attempt_number=audit.attempt_number,
        model_name=audit.model_name,
        model_provider=audit.model_provider,
        prompt=json.dumps(
            {
                "messages": audit.messages,
                "tool_calls": audit.tool_calls,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        response=result.final_annotation.model_dump_json(),
        duration_ms=audit.duration_ms,
        status="success",
    )


def _save_token_usage(
    session: Session,
    *,
    result: AgentRunResult,
    novel_id: str,
    anchor_chunk_id: int,
) -> None:
    """2026-08-05 用于在完成事务中写入成功尝试的全部可信 Token 用量"""
    stats_repo = StatsRepository(session)
    for usage in result.token_usage:
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


def _fact_completion(row: ContinuityFact) -> CompletionFact:
    """2026-08-05 用于把已提交 continuity fact 转换为回读完成结果"""
    return CompletionFact(
        fact_id=row.fact_id,
        payload=FactPayload.model_validate(
            {
                "fact_type": row.fact_type,
                "subject": row.subject,
                "predicate": row.predicate,
                "object": row.object,
                "value": row.value,
                "participants": row.participants,
                "scope": row.scope,
                "story_time": row.story_time,
                "assertion": row.assertion,
                "change_kind": row.change_kind,
                "linked_fact_id": row.linked_fact_id,
                "confidence": row.confidence,
            }
        ),
        evidence=Evidence.model_validate(row.evidence),
    )


def _foreshadowing_completion(
    thread: ForeshadowingThread,
    hit: ForeshadowingThreadHit,
) -> CompletionForeshadowing:
    """2026-08-05 用于从真实 thread 与 hit 行重建完成事务返回结构"""
    evidence = Evidence.model_validate(hit.evidence)
    payload = ForeshadowingPayload.model_validate(
        {
            "has_foreshadowing": True,
            "foreshadowing_type": thread.foreshadowing_type,
            "setup_kind": thread.setup_kind,
            "setup_summary": thread.setup_summary,
            "why_unresolved_now": hit.why_unresolved_now,
            "expected_payoff_family": thread.expected_payoff_family,
            "payoff_likelihood": thread.payoff_likelihood,
            "is_new_setup": bool(hit.is_new_setup),
            "linked_setup_id": None if hit.is_new_setup else thread.setup_id,
            "setup_status": thread.status,
            "confidence": thread.confidence,
        }
    )
    return CompletionForeshadowing(
        setup_id=thread.setup_id,
        hit_id=hit.hit_id,
        payload=payload,
        evidence=evidence,
    )


def load_completion_result(
    session: Session,
    *,
    run_id: str,
    chapter_id: int,
) -> CompletionResult | None:
    """2026-08-05 用于按已提交章节标注与来源映射回读同一个 CompletionResult"""
    annotation_stmt = select(ChapterAnnotationRecord).where(
        ChapterAnnotationRecord.run_id == run_id,
        ChapterAnnotationRecord.chapter_id == chapter_id,
    )
    annotation = session.execute(annotation_stmt).scalar_one_or_none()
    if annotation is None:
        return None

    mapping_stmt = (
        select(CaseResolutionMapping)
        .where(
            CaseResolutionMapping.run_id == run_id,
            CaseResolutionMapping.annotation_id == annotation.annotation_id,
        )
        .order_by(CaseResolutionMapping.created_at, CaseResolutionMapping.mapping_id)
    )
    mappings = list(session.execute(mapping_stmt).scalars().all())

    target_case_ids = list(dict.fromkeys(row.target_case_id for row in mappings if row.target_case_id))
    target_fact_ids = list(dict.fromkeys(row.target_fact_id for row in mappings if row.target_fact_id))
    target_hit_ids = list(dict.fromkeys(row.target_hit_id for row in mappings if row.target_hit_id is not None))
    source_case_ids = list(dict.fromkeys(row.source_case_id for row in mappings if row.source_case_id))

    cases: list[CompletionCase] = []
    if target_case_ids:
        case_stmt = select(CasePoolCase).where(
            CasePoolCase.run_id == run_id,
            CasePoolCase.id.in_(target_case_ids),
        )
        cases_by_id = {row.id: row for row in session.execute(case_stmt).scalars().all()}
        cases = [completion_case_view(cases_by_id[case_id]) for case_id in target_case_ids if case_id in cases_by_id]

    facts: list[CompletionFact] = []
    if target_fact_ids:
        fact_stmt = select(ContinuityFact).where(
            ContinuityFact.run_id == run_id,
            ContinuityFact.fact_id.in_(target_fact_ids),
        )
        facts_by_id = {row.fact_id: row for row in session.execute(fact_stmt).scalars().all()}
        facts = [_fact_completion(facts_by_id[fact_id]) for fact_id in target_fact_ids if fact_id in facts_by_id]

    foreshadowing: list[CompletionForeshadowing] = []
    if target_hit_ids:
        hit_stmt = select(ForeshadowingThreadHit).where(
            ForeshadowingThreadHit.run_id == run_id,
            ForeshadowingThreadHit.hit_id.in_(target_hit_ids),
        )
        hits_by_id = {row.hit_id: row for row in session.execute(hit_stmt).scalars().all()}
        setup_ids = {hit.setup_id for hit in hits_by_id.values()}
        thread_stmt = select(ForeshadowingThread).where(
            ForeshadowingThread.run_id == run_id,
            ForeshadowingThread.setup_id.in_(setup_ids),
        )
        threads_by_id = {row.setup_id: row for row in session.execute(thread_stmt).scalars().all()}
        for hit_id in target_hit_ids:
            hit = hits_by_id.get(hit_id)
            if hit is None or hit.setup_id not in threads_by_id:
                continue
            foreshadowing.append(_foreshadowing_completion(threads_by_id[hit.setup_id], hit))

    source_case_states: dict[str, Any] = {}
    if source_case_ids:
        source_stmt = select(CasePoolCase).where(
            CasePoolCase.run_id == run_id,
            CasePoolCase.id.in_(source_case_ids),
        )
        source_case_states = {
            row.id: row.state
            for row in session.execute(source_stmt).scalars().all()
        }
    rejected_source_case_ids = list(
        dict.fromkeys(
            row.source_case_id
            for row in mappings
            if row.result_kind == "rejected" and row.source_case_id
        )
    )
    return CompletionResult(
        annotation_id=annotation.annotation_id,
        chapter_id=annotation.chapter_id,
        cases=cases,
        facts=facts,
        foreshadowing=foreshadowing,
        rejected_source_case_ids=rejected_source_case_ids,
        source_case_states=source_case_states,
    )


def _persist_outputs(
    session: Session,
    *,
    result: AgentRunResult,
    annotation_id: str,
    anchor_chunk_id: int,
) -> tuple[list[CompletionCase], list[CompletionFact], list[CompletionForeshadowing], set[str]]:
    """2026-08-05 用于规范化写入全部 staged outputs 与来源映射"""
    case_repo = CasePoolRepository(session)
    fact_repo = ContinuityFactRepository(session)
    foreshadowing_repo = ForeshadowingRepository(session)
    mapping_repo = CaseResolutionMappingRepository(session)
    cases: list[CompletionCase] = []
    facts: list[CompletionFact] = []
    foreshadowing: list[CompletionForeshadowing] = []
    rejected_ids: set[str] = set()

    for output in result.staged_outputs:
        if output.output_kind == "case":
            case_target = case_repo.upsert_case(
                run_id=result.run_id,
                annotation_id=annotation_id,
                payload=output.payload,
                evidence=output.evidence,
            )
            cases.append(completion_case_view(case_target))
            for source_case_id in _mapping_sources(output.source_case_ids):
                mapping_repo.add_mapping(
                    run_id=result.run_id,
                    annotation_id=annotation_id,
                    result_kind="case",
                    evidence=output.evidence,
                    source_case_id=source_case_id,
                    target_case_id=case_target.id,
                )
        elif output.output_kind == "fact":
            fact_target = fact_repo.upsert_fact(
                run_id=result.run_id,
                annotation_id=annotation_id,
                payload=output.payload,
                evidence=output.evidence,
            )
            facts.append(fact_repo.completion_view(fact_target))
            for source_case_id in _mapping_sources(output.source_case_ids):
                mapping_repo.add_mapping(
                    run_id=result.run_id,
                    annotation_id=annotation_id,
                    result_kind="fact",
                    evidence=output.evidence,
                    source_case_id=source_case_id,
                    target_fact_id=fact_target.fact_id,
                )
        elif output.output_kind == "foreshadowing":
            thread, hit = foreshadowing_repo.sync(
                run_id=result.run_id,
                chunk_id=anchor_chunk_id,
                payload=output.payload,
                evidence=output.evidence,
            )
            foreshadowing.append(
                foreshadowing_repo.completion_view(thread, hit, output.payload, output.evidence)
            )
            for source_case_id in _mapping_sources(output.source_case_ids):
                mapping_repo.add_mapping(
                    run_id=result.run_id,
                    annotation_id=annotation_id,
                    result_kind="foreshadowing",
                    evidence=output.evidence,
                    source_case_id=source_case_id,
                    target_setup_id=thread.setup_id,
                    target_hit_id=hit.hit_id,
                )
        else:
            rejected_ids.update(output.source_case_ids)
            for source_case_id in output.source_case_ids:
                mapping_repo.add_mapping(
                    run_id=result.run_id,
                    annotation_id=annotation_id,
                    result_kind="rejected",
                    evidence=output.evidence,
                    source_case_id=source_case_id,
                    rejected_reason_code=output.payload.reason_code,
                )
    return cases, facts, foreshadowing, rejected_ids


def complete_annotation_run(
    *,
    result: AgentRunResult,
    novel_id: str,
    session_factory: Callable[[], Session],
) -> CompletionResult:
    """2026-08-05 用于在唯一 session.begin 中原子提交章节结果图审计与 Token 用量"""
    anchor_chunk_id = result.final_annotation.segments[0].chunk_id
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

            source_repo = CasePoolRepository(session)
            source_rows = source_repo.lock_active_cases(result.run_id, result.pulled_case_ids)
            _validate_locked_sources(pulled_case_ids=result.pulled_case_ids, rows=source_rows)

            annotation = ChapterAnnotationRepository(session).add_annotation(
                run_id=result.run_id,
                chapter_id=result.chapter_id,
                annotation=result.final_annotation,
                initial_finish=result.initial_finish,
                after_chapter_ids=result.after_chapter_ids,
                revision_payload=result.revision_payload,
            )
            cases, facts, foreshadowing, rejected_ids = _persist_outputs(
                session,
                result=result,
                annotation_id=annotation.annotation_id,
                anchor_chunk_id=anchor_chunk_id,
            )
            source_repo.update_source_states(source_rows, rejected_ids=rejected_ids)
            source_repo.mark_surfaced(
                run_id=result.run_id,
                ids=result.rotation_case_ids,
                annotation_id=annotation.annotation_id,
            )
            project_graph_tables(
                result.run_id,
                session=session,
                annotation_id=annotation.annotation_id,
            )
            _save_success_audit(session, result=result, anchor_chunk_id=anchor_chunk_id)
            _save_token_usage(
                session,
                result=result,
                novel_id=novel_id,
                anchor_chunk_id=anchor_chunk_id,
            )
            completion = CompletionResult.model_validate(
                {
                    "annotation_id": annotation.annotation_id,
                    "chapter_id": result.chapter_id,
                    "cases": cases,
                    "facts": facts,
                    "foreshadowing": foreshadowing,
                    "rejected_source_case_ids": sorted(rejected_ids),
                    "source_case_states": {row.id: row.state for row in source_rows},
                }
            )
        return completion
    finally:
        session.close()
