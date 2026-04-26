"""
标注数据插入操作

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分annotation_repository
说明: 标注数据插入相关操作
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import update

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


def insert_chunk_annotation(session: Session, run_id: str, chunk_id: int, annotation: ChunkAnnotationSchema) -> None:
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
        why_unresolved_now=annotation.why_unresolved_now,
        expected_payoff_family=annotation.expected_payoff_family,
        run_id=run_id,
    )
    session.add(record)
    session.commit()


def insert_chunk_characters(
    session: Session, run_id: str, chunk_id: int, characters: Sequence[CharacterSnapshot]
) -> None:
    """插入分块角色数据"""
    records = [
        ChunkCharacter(
            chunk_id=chunk_id,
            name=c.name,
            role_function=c.role_function,
            action=c.action,
            action_type=c.action_type,
            emotion_score=c.emotion_score,
            run_id=run_id,
        )
        for c in characters
    ]
    session.add_all(records)
    session.commit()


def insert_chunk_relations(
    session: Session, run_id: str, chunk_id: int, relations: Sequence[RelationChangeSnapshot]
) -> None:
    """
    插入分块关系数据

    修改时间: 2026-04-05
    修改者: TraeAI
    任务: phase4-code-review-fix
    修改内容: 添加 directionality 字段写入
    """
    records = [
        ChunkRelation(
            chunk_id=chunk_id,
            from_char=r.from_name,
            to_char=r.to_name,
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
        for r in relations
        if r.from_name != r.to_name
    ]
    if not records:
        return
    session.add_all(records)
    session.commit()


def update_relation_projection_status(
    session: Session,
    relation_id: int,
    projection_status: str,
    projected_at: datetime | None = None,
    projection_error: str | None = None,
) -> None:
    """更新单条关系的投影状态。"""
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
) -> None:
    """插入分块对话数据

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: fix-insert_chunk_dialogues-speakers-param
    修改内容: speakers 参数已移除， dialogue.speaker 字段已包含正确的说话者

    修改时间: 2026-03-25
    修改者: TraeAI
    任务: fix-tone-distribution-semantic-error
    修改内容: 从 dialogue.tone 字段获取语气类型并保存到数据库

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: fix-unknown-speaker-context
    修改内容: 保存 content 和 evidence 字段，便于追溯未知说话者的上下文

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: use-phase3-identity-clue-in-disambiguation
    修改内容: 保存 identity_clue 字段，存储 Phase 3 提取的身份线索

    修改时间: 2026-04-08
    修改者: TraeAI
    任务: fix-multi-speaker-support
    修改内容: speaker 存储为 JSON 数组字符串，删除 evidence 字段
    """

    records: list[ChunkDialogue] = []
    for idx, dialogue in enumerate(dialogues):
        length = lengths[idx] if lengths is not None and idx < len(lengths) else None
        records.append(
            ChunkDialogue(
                chunk_id=chunk_id,
                speaker=dialogue.speaker,
                length=length,
                tone=dialogue.tone,
                content=dialogue.content,
                identity_clue=dialogue.identity_clue,
                run_id=run_id,
            )
        )
    session.add_all(records)
    session.commit()


def insert_foreshadowing(session: Session, run_id: str, chunk_id: int, result: ForeshadowingResult) -> None:
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
        why_unresolved_now=result.why_unresolved_now,
        expected_payoff_family=result.expected_payoff_family,
        confidence=result.confidence,
        created_at=datetime.now().isoformat(),
        run_id=run_id,
    )
    session.add(record)
    session.commit()
