"""
章节语义标注唯一完成事务
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

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
    GraphFact,
    Paragraph,
)
from src.storage.models.graph import ChapterBoundary
from src.storage.repositories import (
    CasePoolRepository,
    CaseResolutionMappingRepository,
    ChapterAnnotationRepository,
    DialogueRecordRepository,
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
                f"resolved case 类型已变化: case_id={row.id} expected={row.case_type} actual={result.type}"
            )
        if row.target_key != result.target_key or dict(row.target_ref) != result.target_ref:
            raise ValueError(f"resolved case 稳定目标已变化: {row.id}")


def load_completion_result(
    session: Session,
    *,
    run_id: str,
    chapter_id: int,
) -> CompletionResult | None:
    """2026-08-19 用于按章节标注和解决映射回读完成结果"""
    annotation = session.execute(
        select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == run_id,
            ChapterAnnotationRecord.chapter_id == chapter_id,
        )
    ).scalar_one_or_none()
    if annotation is None:
        return None
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
                row.resolution.get("action") if isinstance(row.resolution.get("action"), str) else "close",
            ),
            type=row.case_type,
            reason=str(row.resolution.get("reason") or ""),
            target_dialogue_id=row.target_dialogue_id,
            target_root_event_id=row.target_root_event_id,
            target_event_id=row.target_event_id,
            target_fact_id=row.target_fact_id,
        )
        for row in mapping_rows
    ]
    return CompletionResult(
        annotation_id=annotation.annotation_id,
        chapter_id=annotation.chapter_id,
        created_cases=[completion_case_view(row) for row in created_rows],
        resolved_cases=resolved,
    )


def _persist_dialogue_records(
    session: Session,
    *,
    result: AgentRunResult,
) -> None:
    """2026-08-11 用于把最终系统绑定对话投影到对话记录表

    2026-08-18 P3：按事件锚点列表写入，对话弱关联到完全包含其字符区间的事件。
    2026-08-22锚点直接取服务端生成的 event.node_id。
    2026-08-22 重构：BoundEvent 不再携带字符区间，弱关联改用章级原文区间。
    """
    repository = DialogueRecordRepository(session)
    paragraphs = list(
        session.execute(
            select(Paragraph)
            .where(
                Paragraph.run_id == result.run_id,
                Paragraph.chapter_id == result.chapter_id,
            )
            .order_by(Paragraph.paragraph_index)
        ).scalars()
    )
    if not paragraphs:
        raise ValueError(f"对话落库缺少章节段落: run_id={result.run_id} chapter_id={result.chapter_id}")
    char_start = min(int(row.local_start_char) for row in paragraphs)
    char_end = max(int(row.local_end_char) for row in paragraphs)
    for chunk in result.annotation.chunks:
        event_anchors = [(event.node_id, char_start, char_end) for event in chunk.events]
        repository.sync_dialogues(
            run_id=result.run_id,
            chapter_id=result.chapter_id,
            dialogues=chunk.dialogues,
            event_anchors=event_anchors,
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
        session.execute(select(CasePoolCase.target_key).where(CasePoolCase.run_id == result.run_id)).scalars()
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
    chapter_boundary: ChapterBoundary,
) -> list[CompletionCase]:
    """2026-08-09 用于把图验证器疑似同一人物对写入案例池待仲裁"""
    repository = CasePoolRepository(session)
    existing_keys = set(session.execute(select(CasePoolCase.target_key).where(CasePoolCase.run_id == run_id)).scalars())
    completion_cases: list[CompletionCase] = []
    for pending_case in build_alias_pending_cases(
        session,
        run_id=run_id,
        chapter_boundary=chapter_boundary,
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
    resolved_cases: list[ResolvedCase],
    annotation_id: str,
    resolved_targets_by_case_id: dict,
) -> list[CompletionResolvedCase]:
    """2026-08-11 用于按案例动作保存解决结果与对应目标（对话/伏笔树/事实版本）

    2026-09-13：foreshadowing 动作返回 dict（含伏笔树根 + 挂树事件目标），
    其他动作返回 GraphFact / DialogueRecord / None。

    2026-09-04 单一写面：resolved_cases 由调用方传入（含从 relation_change_ops
    还原的 fact 裁决），不再直接读 result.resolved_cases。
    """
    repository = CaseResolutionMappingRepository(session)
    completion_results: list[CompletionResolvedCase] = []
    for resolved_case in resolved_cases:
        target = resolved_targets_by_case_id.get(resolved_case.case_id)
        target_fact = target if isinstance(target, GraphFact) else None
        if resolved_case.action in {"dialogue", "foreshadowing"} and target is None:
            raise ValueError(f"{resolved_case.action} 动作未生成解决目标: {resolved_case.case_id}")
        target_dialogue_id: str | None = None
        target_root_event_id: str | None = None
        target_event_id: str | None = None
        if isinstance(target, DialogueRecord):
            target_dialogue_id = target.dialogue_id
        if isinstance(target, dict) and "root" in target:
            # 2026-09-13 foreshadowing 动作返回 dict（伏笔树根 + 挂树事件）
            target_root_event_id = target.get("target_root_event_id")
            target_event_id = target.get("target_event_id")
        repository.add_mapping(
            run_id=result.run_id,
            annotation_id=annotation_id,
            resolved_case=resolved_case,
            target_fact=target_fact,
            target_dialogue_id=target_dialogue_id,
            target_root_event_id=target_root_event_id,
            target_event_id=target_event_id,
        )
        completion_results.append(
            CompletionResolvedCase(
                case_id=resolved_case.case_id,
                action=resolved_case.action,
                type=resolved_case.type,
                reason=resolved_case.reason,
                target_dialogue_id=target_dialogue_id,
                target_root_event_id=target_root_event_id,
                target_event_id=target_event_id,
                target_fact_id=target_fact.fact_id if target_fact is not None else None,
            )
        )
    return completion_results


def _reelect_representatives(
    session: Session,
    *,
    run_id: str,
) -> None:
    """2026-08-11 用于每章完成后全量清空并重选规范名标记写入实体属性"""
    from src.storage.models.graph import GraphEntity
    from src.storage.repositories.graph.election import elect_representatives
    from src.storage.repositories.graph.repository import GraphRepository

    entities = list(session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars())
    pairs = [
        (int(row.from_entity_id), int(row.to_entity_id))
        for row in GraphRepository(session).fetch_latest_relations(run_id, active_only=True)
        if row.relation_semantics == "same_character"
    ]
    flags = elect_representatives(entities, pairs=pairs)
    for entity in entities:
        attributes = dict(entity.attributes or {})
        if attributes.get("is_representative") == flags[int(entity.entity_id)]:
            continue
        attributes["is_representative"] = bool(flags[int(entity.entity_id)])
        entity.attributes = attributes


def _graph_fact_resolved_cases(result: AgentRunResult) -> list[ResolvedCase]:
    """2026-09-04 单一写面：把 FactGraph 关系变更操作日志还原为 fact 裁决 ResolvedCase

    resolve_fact_case 不再向 resolved_cases 追加条目，图域裁决随 relation_change_ops
    进入完成事务；此处按原 ResolvedCase 形状重建，使锁行校验、_persist_fact_resolution
    与解决映射写入沿用既有链路。
    """
    return [
        ResolvedCase(
            case_id=op["case_id"],
            action="fact",
            type=op["case_type"],
            reason=op["reason"],
            target_key=op["target_key"],
            target_ref=dict(op["target_ref"]),
            from_entity=op["from_entity"],
            to_entity=op["to_entity"],
            relation_type=op["relation_type"],
            change_kind=op["change_kind"],
        )
        for op in result.relation_change_ops
    ]


def _fold_resolved_cases(entries: list[ResolvedCase]) -> list[ResolvedCase]:
    """2026-09-11 用于按 case_id 折叠重复裁决（章内并行设计 §14 过渡补丁）

    现行串行子块协议下，两个子块可能各自解决同一案例（run e84339d1 第 20 章
    两块对同一批 active 案例各裁决一次，合并拼接后撞唯一性校验整章失败）。
    两条裁决都是真实观察（A 块拿到引入段写埋设、B 块拿到坐实段写确认），
    因此折叠而非丢弃：字段级后值非空覆盖（与伏笔树根属性覆盖语义
    一致）、reason 拼接、保持首次出现顺序。fact 路径
    （_graph_fact_resolved_cases）与 foreshadowing/dialogue 路径的同 case_id
    重复在同一暴露面处理。
    """
    folded: dict[str, ResolvedCase] = {}
    order: list[str] = []
    for entry in entries:
        existing = folded.get(entry.case_id)
        if existing is None:
            folded[entry.case_id] = entry
            order.append(entry.case_id)
            continue
        updates: dict[str, Any] = {}
        for field_name in ResolvedCase.model_fields:
            if field_name in {"case_id", "reason"}:
                continue
            later_value = getattr(entry, field_name)
            if later_value is not None:
                updates[field_name] = later_value
        merged_reason = "\n".join(
            reason for reason in (existing.reason, entry.reason) if reason
        )
        folded[entry.case_id] = existing.model_copy(update={**updates, "reason": merged_reason})
    return [folded[case_id] for case_id in order]


def complete_annotation_run(
    *,
    result: AgentRunResult,
    session_factory: Callable[[], Session],
) -> CompletionResult:
    """2026-08-10 用于原子提交正式标注图版本与连续性（审计由 AgentAuditRecorder 独立写入）

    2026-08-13 P2-5: 移除从未使用的 novel_id 参数（原实现立即 del，无任何消费点）。
    2026-09-04 单一写面：图域输入改为 FactGraph 操作日志（entity_ops /
    relation_assert_ops / relation_change_ops）；fact 裁决在边界还原为
    ResolvedCase 后与 resolved_cases 合并，锁行/校验/映射链路不变。
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
            annotation = ChapterAnnotationRepository(session).add_annotation(
                run_id=result.run_id,
                chapter_id=result.chapter_id,
                annotation=result.annotation,
            )
            # 2026-09-13 登记即进池：模型 push_case 的案例先落行（行 id 即 target_key），
            # 本 chunk 内"推入即解决"的裁决才能在下面对同一标识锁行并校验稳定目标
            pushed_completion = _persist_pushed_cases(
                session,
                result=result,
                annotation_id=annotation.annotation_id,
            )
            # 2026-09-11 §14 过渡补丁：重复裁决按 case_id 折叠后再锁行校验；
            # 两段式写者落地后单写者使重复不再产生，该折叠为串行子块的兜底
            all_resolved_cases = _fold_resolved_cases(
                [*result.resolved_cases, *_graph_fact_resolved_cases(result)]
            )
            resolved_case_ids = [item.case_id for item in all_resolved_cases]
            locked_rows = case_repository.lock_active_cases(
                result.run_id,
                resolved_case_ids,
            )
            _validate_locked_cases(
                resolved_cases=all_resolved_cases,
                rows=locked_rows,
            )
            _persist_dialogue_records(session, result=result)
            graph_result = persist_completion_graph(
                session,
                annotation=annotation,
                resolved_cases=all_resolved_cases,
                entity_ops=result.entity_ops,
                relation_assert_ops=result.relation_assert_ops,
                # 2026-08-18：完成事务同时复核 Agent 实际读取过的段落授权
                authorized_text_chapter_ids=set(result.audit.authorized_chapter_ids),
                authorized_text_paragraph_ids=set(result.audit.authorized_text_paragraph_ids),
            )
            _reelect_representatives(session, run_id=result.run_id)
            resolved_completion = _persist_resolution_mappings(
                session,
                result=result,
                resolved_cases=all_resolved_cases,
                annotation_id=annotation.annotation_id,
                resolved_targets_by_case_id=graph_result.resolved_targets_by_case_id,
            )
            case_repository.resolve_cases(locked_rows)
            alias_completion = _persist_alias_pending_cases(
                session,
                run_id=result.run_id,
                annotation_id=annotation.annotation_id,
                chapter_boundary=graph_result.chapter_boundary,
            )
            completion = CompletionResult(
                annotation_id=annotation.annotation_id,
                chapter_id=result.chapter_id,
                created_cases=[*pushed_completion, *alias_completion],
                resolved_cases=resolved_completion,
            )
        return completion
    finally:
        session.close()
