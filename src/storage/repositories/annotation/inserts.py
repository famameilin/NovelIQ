"""
标注数据插入操作

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分annotation_repository
说明: 标注数据插入相关操作
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Sequence

from src.models.local.schema import (
    ChunkAnnotation as ChunkAnnotationSchema,
    CharacterSnapshot,
    DialogueSnapshot,
    ForeshadowingResult,
    RelationChangeSnapshot,
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
        pivot_moment=int(annotation.pivot_moment) if annotation.pivot_moment else None,
        event_type=annotation.event_type,
        cliffhanger=int(annotation.cliffhanger) if annotation.cliffhanger else None,
        has_foreshadowing=int(annotation.has_foreshadowing) if annotation.has_foreshadowing else None,
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
    """
    records: List[ChunkDialogue] = []
    for idx, dialogue in enumerate(dialogues):
        length = lengths[idx] if lengths is not None and idx < len(lengths) else None
        records.append(
            ChunkDialogue(
                chunk_id=chunk_id,
                speaker=dialogue.speaker,
                length=length,
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
