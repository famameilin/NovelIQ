"""
标注数据插入操作

标注数据插入相关操作
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, update

from src.models.local.character_reference_policy import CharacterReferenceDecision, decide_character_reference
from src.models.local.schema import (
    CharacterSnapshot,
    DialogueSnapshot,
    ForeshadowingResult,
    RelationChangeSnapshot,
)
from src.models.local.schema import (
    ChunkAnnotation as ChunkAnnotationSchema,
)
from src.storage.models import (
    ChunkAnnotation,
    ChunkCharacter,
    ChunkDialogue,
    ChunkForeshadowing,
    ChunkRelation,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _relation_value(relation: RelationChangeSnapshot | dict[str, Any], field_name: str, default: Any = None) -> Any:
    if isinstance(relation, dict):
        return relation.get(field_name, default)
    return getattr(relation, field_name, default)


def _reference_decision_to_dict(decision: CharacterReferenceDecision) -> dict[str, Any]:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: speaker_references 使用 JSONB 存储，需要把统一准入决策稳定序列化。
    """
    return {
        "surface_name": decision.surface_name,
        "reference_kind": decision.reference_kind,
        "reference_slot": decision.reference_slot,
        "resolved_global_name": decision.resolved_global_name,
        "can_enter_global_character": decision.can_enter_global_character,
        "global_skip_reason": decision.global_skip_reason,
    }


def _build_reference_skip_reason(*decisions: CharacterReferenceDecision) -> str | None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 未解析关系 endpoint 必须明确记录 pending 原因，不能静默丢弃。
    """
    reasons = [
        f"{decision.surface_name}: {decision.global_skip_reason}"
        for decision in decisions
        if not decision.can_enter_global_character and decision.global_skip_reason
    ]
    return "; ".join(reasons) if reasons else None


def insert_chunk_annotation(
    session: Session,
    run_id: str,
    chunk_id: int,
    annotation: ChunkAnnotationSchema,
    *,
    commit: bool = True,
) -> None:
    """插入分块标注"""
    record = ChunkAnnotation(
        chunk_id=chunk_id,
        emotional_valence=annotation.emotional_valence,
        pivot_moment=int(annotation.pivot_moment) if annotation.pivot_moment is not None else None,
        event_type=annotation.event_type,
        cliffhanger=int(annotation.cliffhanger) if annotation.cliffhanger is not None else None,
        has_foreshadowing=int(annotation.has_foreshadowing) if annotation.has_foreshadowing is not None else None,
        is_strong_setup=int(annotation.is_strong_setup) if annotation.is_strong_setup is not None else None,
        foreshadowing_type=annotation.foreshadowing_type,
        setup_kind=annotation.setup_kind,
        foreshadowing_desc=annotation.foreshadowing_desc,
        setup_summary=annotation.setup_summary,
        why_unresolved_now=annotation.why_unresolved_now,
        expected_payoff_family=annotation.expected_payoff_family,
        payoff_likelihood=annotation.payoff_likelihood,
        linked_setup_id=annotation.linked_setup_id,
        run_id=run_id,
    )
    session.add(record)
    if commit:
        session.commit()
    else:
        session.flush()


def insert_chunk_characters(
    session: Session,
    run_id: str,
    chunk_id: int,
    characters: Sequence[CharacterSnapshot],
    *,
    commit: bool = True,
) -> None:
    """
    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: chunk_characters 保留 raw surface，同时写入统一准入后的 reference/global 字段。
    """
    records = []
    for c in characters:
        decision = decide_character_reference(
            c.surface_name or c.name,
            resolved_global_name=c.resolved_global_name,
            chunk_id=chunk_id,
        )
        records.append(
            ChunkCharacter(
                chunk_id=chunk_id,
                name=c.name,
                surface_name=decision.surface_name,
                reference_kind=decision.reference_kind,
                reference_slot=decision.reference_slot,
                resolved_global_name=decision.resolved_global_name,
                global_skip_reason=decision.global_skip_reason,
                role_function=c.role_function,
                action=c.action,
                action_type=c.action_type,
                emotion_score=c.emotion_score,
                run_id=run_id,
            )
        )
    session.add_all(records)
    if commit:
        session.commit()
    else:
        session.flush()


def insert_chunk_relations(
    session: Session,
    run_id: str,
    chunk_id: int,
    relations: Sequence[RelationChangeSnapshot],
    *,
    commit: bool = True,
) -> None:
    """
    插入分块关系数据

    添加 directionality 字段写入

    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: 关系 endpoint 需要同时保留 raw surface 与可投影 global endpoint。
    """
    records = []
    for r in relations:
        if r.from_name == r.to_name:
            continue
        from_decision = decide_character_reference(
            r.from_name,
            resolved_global_name=r.resolved_from_global_name,
            chunk_id=chunk_id,
        )
        to_decision = decide_character_reference(
            r.to_name,
            resolved_global_name=r.resolved_to_global_name,
            chunk_id=chunk_id,
        )
        records.append(
            ChunkRelation(
                chunk_id=chunk_id,
                from_char=r.from_name,
                to_char=r.to_name,
                from_reference_kind=from_decision.reference_kind,
                to_reference_kind=to_decision.reference_kind,
                resolved_from_global_name=from_decision.resolved_global_name,
                resolved_to_global_name=to_decision.resolved_global_name,
                reference_skip_reason=r.reference_skip_reason
                or _build_reference_skip_reason(from_decision, to_decision),
                type=r.type,
                change=r.change,
                directionality=r.directionality,
                evidence=r.evidence,
                confidence=r.confidence,
                source_model=r.source_model,
                projection_status=r.projection_status,
                projected_at=datetime.fromisoformat(r.projected_at) if r.projected_at else None,
                projection_error=r.projection_error,
                run_id=run_id,
            )
        )
    if not records:
        return
    session.add_all(records)
    if commit:
        session.commit()
    else:
        session.flush()


def replace_chunk_relations_for_source_model(
    session: Session,
    run_id: str,
    chunk_id: int,
    relations: Sequence[RelationChangeSnapshot | dict[str, Any]],
    *,
    source_model: str,
    commit: bool = True,
) -> None:
    """
    2026-04-27，任务：graph final-disambiguation rebuild fixes
    终消歧生成的层级关系需要先稳定回写到 chunk_relations，再交给后续 rebuild 统一投影，
    否则直接写进 graph_* 表的结果会在 reset_graph_tables() 后丢失
    """
    session.execute(
        delete(ChunkRelation).where(
            ChunkRelation.run_id == run_id,
            ChunkRelation.source_model == source_model,
        )
    )
    if relations:
        records = []
        for relation in relations:
            from_name = _relation_value(relation, "from_name")
            to_name = _relation_value(relation, "to_name")
            if from_name == to_name:
                continue
            from_decision = decide_character_reference(
                from_name,
                resolved_global_name=_relation_value(relation, "resolved_from_global_name"),
                chunk_id=chunk_id,
            )
            to_decision = decide_character_reference(
                to_name,
                resolved_global_name=_relation_value(relation, "resolved_to_global_name"),
                chunk_id=chunk_id,
            )
            records.append(
                ChunkRelation(
                    chunk_id=chunk_id,
                    from_char=from_name,
                    to_char=to_name,
                    from_reference_kind=_relation_value(relation, "from_reference_kind")
                    or from_decision.reference_kind,
                    to_reference_kind=_relation_value(relation, "to_reference_kind") or to_decision.reference_kind,
                    resolved_from_global_name=from_decision.resolved_global_name,
                    resolved_to_global_name=to_decision.resolved_global_name,
                    reference_skip_reason=_relation_value(relation, "reference_skip_reason")
                    or _build_reference_skip_reason(from_decision, to_decision),
                    type=_relation_value(relation, "type"),
                    change=_relation_value(relation, "change"),
                    directionality=_relation_value(relation, "directionality", "directed"),
                    evidence=_relation_value(relation, "evidence"),
                    confidence=_relation_value(relation, "confidence"),
                    source_model=source_model,
                    projection_status=_relation_value(relation, "projection_status", "pending"),
                    projected_at=(
                        datetime.fromisoformat(_relation_value(relation, "projected_at"))
                        if _relation_value(relation, "projected_at")
                        else None
                    ),
                    projection_error=_relation_value(relation, "projection_error"),
                    run_id=run_id,
                )
            )
        session.add_all(records)
    if commit:
        session.commit()
    else:
        session.flush()


def update_relation_projection_status(
    session: Session,
    relation_id: int,
    projection_status: str,
    projected_at: datetime | None = None,
    projection_error: str | None = None,
) -> None:
    """更新单条关系的投影状态"""
    stmt = (
        update(ChunkRelation)
        .where(ChunkRelation.id == relation_id)
        .values(
            projection_status=projection_status,
            projected_at=projected_at,
            projection_error=projection_error,
        )
    )
    session.execute(stmt)


def insert_chunk_dialogues(
    session: Session,
    run_id: str,
    chunk_id: int,
    dialogues: Sequence[DialogueSnapshot],
    lengths: Sequence[int] | None = None,
    *,
    commit: bool = True,
) -> None:
    """插入分块对话数据

    speakers 参数已移除， dialogue.speaker 字段已包含正确的说话者

    从 dialogue.tone 字段获取语气类型并保存到数据库

    保存 content 和 evidence 字段，便于追溯未知说话者的上下文

    保存 identity_clue 字段，存储 Phase 3 提取的身份线索

    speaker 存储为 JSON 数组字符串，删除 evidence 字段

    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: 对话 speaker 保留 raw surface，并同步写入 reference 决策 JSON 供审计和后续解析。
    """

    records: list[ChunkDialogue] = []
    for idx, dialogue in enumerate(dialogues):
        length = lengths[idx] if lengths is not None and idx < len(lengths) else None
        if dialogue.speaker_references:
            speaker_references = [reference.model_dump() for reference in dialogue.speaker_references]
        else:
            speaker_references = [
                _reference_decision_to_dict(decide_character_reference(speaker, chunk_id=chunk_id))
                for speaker in (dialogue.speaker or [])
                if speaker
            ]
        records.append(
            ChunkDialogue(
                chunk_id=chunk_id,
                speaker=dialogue.speaker,
                speaker_references=speaker_references or None,
                length=length,
                tone=dialogue.tone,
                content=dialogue.content,
                identity_clue=dialogue.identity_clue,
                run_id=run_id,
            )
        )
    session.add_all(records)
    if commit:
        session.commit()
    else:
        session.flush()


def insert_foreshadowing(
    session: Session,
    run_id: str,
    chunk_id: int,
    result: ForeshadowingResult,
    *,
    commit: bool = True,
) -> None:
    """插入伏笔分析结果"""
    if not result.has_foreshadowing:
        return
    record = ChunkForeshadowing(
        chunk_id=chunk_id,
        is_strong_setup=int(result.is_strong_setup) if result.is_strong_setup is not None else None,
        foreshadowing_type=result.foreshadowing_type,
        setup_kind=result.setup_kind,
        anchor_text=result.anchor_text,
        anchor_reason=result.anchor_reason,
        setup_summary=result.setup_summary,
        why_unresolved_now=result.why_unresolved_now,
        expected_payoff_family=result.expected_payoff_family,
        payoff_likelihood=result.payoff_likelihood,
        is_new_setup=int(result.is_new_setup),
        linked_setup_id=result.linked_setup_id,
        setup_status=result.setup_status,
        confidence=result.confidence,
        created_at=datetime.now().isoformat(),
        run_id=run_id,
    )
    session.add(record)
    if commit:
        session.commit()
    else:
        session.flush()
