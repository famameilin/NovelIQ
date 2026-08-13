"""
章节语义标注唯一完成事务
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.annotation.schema import (
    AgentRunResult,
    CaseAction,
    CompletionCase,
    CompletionResolvedCase,
    CompletionResult,
    ResolvedCase,
)
from src.storage.models import (
    CasePoolCase,
    CaseResolutionMapping,
    ChapterAnnotationRecord,
    DialogueRecord,
    ForeshadowingThread,
    GraphFact,
    GraphVersion,
)
from src.storage.repositories import (
    CasePoolRepository,
    CaseResolutionMappingRepository,
    ChapterAnnotationRepository,
    DialogueRecordRepository,
    ForeshadowingRepository,
)
from src.storage.repositories.annotation.continuity import completion_case_view
from src.storage.repositories.graph import persist_completion_graph
from src.workflows.graph_verifier import build_alias_pending_cases


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
            action=cast(
                CaseAction,
                row.resolution.get("action")
                if isinstance(row.resolution.get("action"), str)
                else "close",
            ),
            type=row.case_type,
            reason=str(row.resolution.get("reason") or ""),
            target_dialogue_id=row.target_dialogue_id,
            target_setup_id=row.target_setup_id,
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


def _persist_dialogue_records(
    session: Session,
    *,
    result: AgentRunResult,
) -> None:
    """2026-08-11 用于把最终系统绑定对话投影到对话记录表"""
    repository = DialogueRecordRepository(session)
    for chunk in result.annotation.chunks:
        repository.sync_dialogues(
            run_id=result.run_id,
            chapter_id=result.chapter_id,
            chunk_id=chunk.chunk_id,
            dialogues=chunk.dialogues,
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


def _persist_pushed_cases(
    session: Session,
    *,
    result: AgentRunResult,
    annotation_id: str,
) -> list[CompletionCase]:
    """2026-08-10 用于把模型 push_case 创建的新案例登记进案例池"""
    repository = CasePoolRepository(session)
    existing_keys = set(
        session.execute(
            select(CasePoolCase.target_key).where(CasePoolCase.run_id == result.run_id)
        ).scalars()
    )
    completion_cases: list[CompletionCase] = []
    for pushed_case in result.pushed_cases:
        if pushed_case.target_key in existing_keys:
            continue
        row = repository.create_case(
            run_id=result.run_id,
            annotation_id=annotation_id,
            pending_case=pushed_case,
        )
        existing_keys.add(pushed_case.target_key)
        completion_cases.append(completion_case_view(row))
    return completion_cases


def _persist_alias_pending_cases(
    session: Session,
    *,
    run_id: str,
    annotation_id: str,
    graph_version: GraphVersion,
) -> list[CompletionCase]:
    """2026-08-09 用于把图验证器疑似同一人物对写入案例池待仲裁"""
    repository = CasePoolRepository(session)
    existing_keys = set(
        session.execute(
            select(CasePoolCase.target_key).where(CasePoolCase.run_id == run_id)
        ).scalars()
    )
    completion_cases: list[CompletionCase] = []
    for pending_case in build_alias_pending_cases(
        session,
        run_id=run_id,
        graph_version=graph_version,
        existing_target_keys=existing_keys,
    ):
        row = repository.create_case(
            run_id=run_id,
            annotation_id=annotation_id,
            pending_case=pending_case,
        )
        completion_cases.append(completion_case_view(row))
    return completion_cases


def _persist_resolution_mappings(
    session: Session,
    *,
    result: AgentRunResult,
    annotation_id: str,
    resolved_targets_by_case_id: dict,
) -> list[CompletionResolvedCase]:
    """2026-08-11 用于按案例动作保存解决结果与对应目标（对话/线程/事实版本）"""
    repository = CaseResolutionMappingRepository(session)
    completion_results: list[CompletionResolvedCase] = []
    for resolved_case in result.resolved_cases:
        target = resolved_targets_by_case_id.get(resolved_case.case_id)
        target_fact = target if isinstance(target, GraphFact) else None
        if resolved_case.action in {"dialogue", "foreshadowing"} and target is None:
            raise ValueError(f"{resolved_case.action} 动作未生成解决目标: {resolved_case.case_id}")
        target_dialogue_id = None
        target_setup_id = None
        if isinstance(target, DialogueRecord):
            target_dialogue_id = target.dialogue_id
        if isinstance(target, ForeshadowingThread):
            target_setup_id = target.setup_id
        repository.add_mapping(
            run_id=result.run_id,
            annotation_id=annotation_id,
            resolved_case=resolved_case,
            target_fact=target_fact,
            target_dialogue_id=target_dialogue_id,
            target_setup_id=target_setup_id,
        )
        completion_results.append(
            CompletionResolvedCase(
                case_id=resolved_case.case_id,
                action=resolved_case.action,
                type=resolved_case.type,
                reason=resolved_case.reason,
                target_dialogue_id=target_dialogue_id,
                target_setup_id=target_setup_id,
                target_fact_id=target_fact.fact_id if target_fact is not None else None,
                target_fact_revision=(
                    target_fact.fact_revision if target_fact is not None else None
                ),
            )
        )
    return completion_results


def _reelect_representatives(
    session: Session,
    *,
    run_id: str,
) -> None:
    """2026-08-11 用于每章完成后全量清空并重选规范名标记写入实体属性"""
    from sqlalchemy import func

    from src.storage.models.graph import GraphEntity, GraphRelation, GraphRelationVersion
    from src.storage.repositories.graph.election import elect_representatives

    entities = list(
        session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
    )
    latest_revision = (
        select(
            GraphRelationVersion.relation_id,
            func.max(GraphRelationVersion.relation_revision).label("max_revision"),
        )
        .where(GraphRelationVersion.run_id == run_id)
        .group_by(GraphRelationVersion.relation_id)
        .subquery()
    )
    relation_rows = (
        session.execute(
            select(GraphRelation.from_entity_id, GraphRelation.to_entity_id)
            .join(
                GraphRelationVersion,
                GraphRelationVersion.relation_id == GraphRelation.relation_id,
            )
            # 2026-08-13 P1-3 防御：只取每关系最新版本参与选举，历史残留的
            # active 版本（关系已被后续章节 break/retract）混入会让已解绑的
            # 实体对被错误选为代表
            .join(
                latest_revision,
                (latest_revision.c.relation_id == GraphRelationVersion.relation_id)
                & (latest_revision.c.max_revision == GraphRelationVersion.relation_revision),
            )
            .where(
                GraphRelation.run_id == run_id,
                GraphRelationVersion.run_id == run_id,
                GraphRelationVersion.is_active.is_(True),
                GraphRelation.relation_semantics == "same_character",
            )
            .distinct()
        ).all()
    )
    pairs = [(int(row[0]), int(row[1])) for row in relation_rows]
    flags = elect_representatives(entities, pairs=pairs)
    for entity in entities:
        attributes = dict(entity.attributes or {})
        if attributes.get("is_representative") == flags[int(entity.entity_id)]:
            continue
        attributes["is_representative"] = bool(flags[int(entity.entity_id)])
        entity.attributes = attributes


def complete_annotation_run(
    *,
    result: AgentRunResult,
    session_factory: Callable[[], Session],
) -> CompletionResult:
    """2026-08-10 用于原子提交正式标注图版本与连续性（审计由 AgentAuditRecorder 独立写入）

    2026-08-13 P2-5: 移除从未使用的 novel_id 参数（原实现立即 del，无任何消费点）。
    """
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
            _persist_dialogue_records(session, result=result)
            _persist_foreshadowing(session, result=result)
            graph_result = persist_completion_graph(
                session,
                annotation=annotation,
                resolved_cases=result.resolved_cases,
                authorized_text_chunk_ids=set(result.audit.authorized_text_chunk_ids),
            )
            _reelect_representatives(session, run_id=result.run_id)
            resolved_completion = _persist_resolution_mappings(
                session,
                result=result,
                annotation_id=annotation.annotation_id,
                resolved_targets_by_case_id=graph_result.resolved_targets_by_case_id,
            )
            case_repository.resolve_cases(locked_rows)
            pushed_completion = _persist_pushed_cases(
                session,
                result=result,
                annotation_id=annotation.annotation_id,
            )
            alias_completion = _persist_alias_pending_cases(
                session,
                run_id=result.run_id,
                annotation_id=annotation.annotation_id,
                graph_version=graph_result.graph_version,
            )
            case_repository.mark_surfaced(
                run_id=result.run_id,
                ids=result.audit.rotation_case_ids,
                annotation_id=annotation.annotation_id,
            )
            completion = CompletionResult(
                annotation_id=annotation.annotation_id,
                graph_version_id=graph_result.graph_version.graph_version_id,
                chapter_id=result.chapter_id,
                created_cases=[*pushed_completion, *alias_completion],
                resolved_cases=resolved_completion,
            )
        return completion
    finally:
        session.close()
