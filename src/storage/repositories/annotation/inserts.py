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


def insert_chunk_annotation(
    session: Session, run_id: str, chunk_id: int, annotation: ChunkAnnotationSchema
) -> None:
    """插入分块标注"""
    record = ChunkAnnotation(
        chunk_id=chunk_id,
        emotional_valence=annotation.emotional_valence,
        pivot_moment=int(annotation.pivot_moment) if annotation.pivot_moment is not None else None,
        event_type=annotation.event_type,
        cliffhanger=int(annotation.cliffhanger) if annotation.cliffhanger is not None else None,
        has_foreshadowing=int(annotation.has_foreshadowing) if annotation.has_foreshadowing is not None else None,
        foreshadowing_type=annotation.foreshadowing_type,
        foreshadowing_desc=annotation.foreshadowing_desc,
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
    """插入分块关系数据"""
    records = [
        ChunkRelation(
            chunk_id=chunk_id,
            from_char=r.from_name,
            to_char=r.to_name,
            type=r.type,
            change=r.change,
            run_id=run_id,
        )
        for r in relations
        if r.from_name != r.to_name
    ]
    if not records:
        return
    session.add_all(records)
    session.commit()


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
                evidence=dialogue.evidence,
                run_id=run_id,
            )
        )
    session.add_all(records)
    session.commit()


def insert_foreshadowing(
    session: Session, run_id: str, chunk_id: int, result: ForeshadowingResult
) -> None:
    """插入伏笔分析结果"""
    if not result.has_foreshadowing:
        return
    record = ChunkForeshadowing(
        chunk_id=chunk_id,
        foreshadowing_type=result.foreshadowing_type,
        anchor_text=result.anchor_text,
        anchor_reason=result.anchor_reason,
        confidence=result.confidence,
        created_at=datetime.now().isoformat(),
        run_id=run_id,
    )
    session.add(record)
    session.commit()
