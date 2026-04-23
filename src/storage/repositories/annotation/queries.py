"""
标注数据查询操作

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分annotation_repository
说明: 标注数据查询相关操作
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from src.storage.models import (
    Chunk,
    ChunkAnnotation,
    ChunkCharacter,
    ChunkDialogue,
    ChunkRelation,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def fetch_chunk_annotations(session: Session, run_id: str) -> list[Any]:
    """
    获取指定运行的所有分块标注

    Returns:
        (chunk_id, event_type, cliffhanger) 元组列表
    """
    stmt = (
        select(ChunkAnnotation.chunk_id, ChunkAnnotation.event_type, ChunkAnnotation.cliffhanger)
        .where(ChunkAnnotation.run_id == run_id)
        .order_by(ChunkAnnotation.chunk_id)
    )
    result = session.execute(stmt)
    return list(result.fetchall())


def fetch_chunk_annotations_full(session: Session, run_id: str) -> list[Any]:
    """
    获取完整的分块标注数据（用于结果导出）

    Returns:
        (chunk_id, emotional_valence, event_type, pivot_moment, cliffhanger,
         has_foreshadowing, foreshadowing_type, foreshadowing_desc) 元组列表
    """
    stmt = (
        select(
            ChunkAnnotation.chunk_id,
            ChunkAnnotation.emotional_valence,
            ChunkAnnotation.event_type,
            ChunkAnnotation.pivot_moment,
            ChunkAnnotation.cliffhanger,
            ChunkAnnotation.has_foreshadowing,
            ChunkAnnotation.foreshadowing_type,
            ChunkAnnotation.foreshadowing_desc,
        )
        .where(ChunkAnnotation.run_id == run_id)
        .order_by(ChunkAnnotation.chunk_id)
    )
    result = session.execute(stmt)
    return list(result.fetchall())


def fetch_chunk_characters_full(session: Session, run_id: str) -> list[Any]:
    """
    获取完整的分块角色数据

    Returns:
        (chunk_id, name, role_function, action, emotion_score) 元组列表
    """
    stmt = (
        select(
            ChunkCharacter.chunk_id,
            ChunkCharacter.name,
            ChunkCharacter.role_function,
            ChunkCharacter.action,
            ChunkCharacter.emotion_score,
        )
        .where(ChunkCharacter.run_id == run_id)
        .order_by(ChunkCharacter.chunk_id)
    )
    result = session.execute(stmt)
    return list(result.fetchall())


def fetch_chunk_relations_full(session: Session, run_id: str) -> list[Any]:
    """
    获取完整的分块关系数据

    Returns:
        (chunk_id, from_char, to_char, type, change) 元组列表
    """
    stmt = (
        select(
            ChunkRelation.chunk_id,
            ChunkRelation.from_char,
            ChunkRelation.to_char,
            ChunkRelation.type,
            ChunkRelation.change,
            ChunkRelation.evidence,
            ChunkRelation.confidence,
            ChunkRelation.source_model,
            ChunkRelation.projection_status,
            ChunkRelation.projected_at,
            ChunkRelation.projection_error,
            ChunkRelation.id,
        )
        .where(ChunkRelation.run_id == run_id)
        .order_by(ChunkRelation.chunk_id)
    )
    result = session.execute(stmt)
    return list(result.fetchall())


def fetch_chunk_dialogues_full(session: Session, run_id: str) -> list[Any]:
    """
    获取完整的分块对话数据

    修改时间: 2026-03-25
    修改者: TraeAI
    任务: fix-tone-distribution-semantic-error
    修改内容: 添加 tone 字段到返回结果

    Returns:
        (chunk_id, speaker, length, tone) 元组列表
    """
    stmt = (
        select(ChunkDialogue.chunk_id, ChunkDialogue.speaker, ChunkDialogue.length, ChunkDialogue.tone)
        .where(ChunkDialogue.run_id == run_id)
        .order_by(ChunkDialogue.chunk_id)
    )
    result = session.execute(stmt)
    return list(result.fetchall())


def fetch_annotated_chunk_ids(session: Session, run_id: str) -> set[int]:
    """
    获取指定运行已标注的分块ID集合

    Returns:
        已标注分块ID集合
    """
    stmt = select(ChunkAnnotation.chunk_id).where(ChunkAnnotation.run_id == run_id)
    result = session.execute(stmt)
    return {row.chunk_id for row in result.fetchall()}


def fetch_full_annotations(session: Session, run_id: str) -> list[Any]:
    """
    获取完整的分块标注数据

    Returns:
        (chunk_id, event_type, cliffhanger, pivot_moment, emotional_valence) 元组列表
    """
    stmt = (
        select(
            ChunkAnnotation.chunk_id,
            ChunkAnnotation.event_type,
            ChunkAnnotation.cliffhanger,
            ChunkAnnotation.pivot_moment,
            ChunkAnnotation.emotional_valence,
        )
        .where(ChunkAnnotation.run_id == run_id)
        .order_by(ChunkAnnotation.chunk_id)
    )
    result = session.execute(stmt)
    return list(result.fetchall())


def fetch_characters_with_scores(session: Session, run_id: str) -> list[Any]:
    """
    获取角色数据（含情绪分数）

    Returns:
        (name, role_function, emotion_score) 元组列表
    """
    stmt = select(
        ChunkCharacter.name,
        ChunkCharacter.role_function,
        ChunkCharacter.emotion_score,
    ).where(ChunkCharacter.run_id == run_id)
    result = session.execute(stmt)
    return list(result.fetchall())


def fetch_character_emotion_sequence(session: Session, run_id: str) -> list[Any]:
    """
    获取角色情绪序列（按 chunk_id 排序）

    Returns:
        (name, emotion_score) 元组列表，按 chunk_id 排序
    """
    stmt = (
        select(ChunkCharacter.name, ChunkCharacter.emotion_score)
        .where(ChunkCharacter.run_id == run_id)
        .order_by(ChunkCharacter.chunk_id)
    )
    result = session.execute(stmt)
    return list(result.fetchall())


def fetch_relations(session: Session, run_id: str) -> list[Any]:
    """
    获取角色关系（仅 from/to）

    Returns:
        (from_char, to_char) 元组列表
    """
    stmt = select(ChunkRelation.from_char, ChunkRelation.to_char).where(ChunkRelation.run_id == run_id)
    result = session.execute(stmt)
    return list(result.fetchall())


def fetch_full_relations(session: Session, run_id: str) -> list[Any]:
    """
    获取完整角色关系

    Returns:
        (from_char, to_char, type, change) 元组列表
    """
    stmt = select(
        ChunkRelation.from_char,
        ChunkRelation.to_char,
        ChunkRelation.type,
        ChunkRelation.change,
        ChunkRelation.evidence,
        ChunkRelation.confidence,
    ).where(ChunkRelation.run_id == run_id)
    result = session.execute(stmt)
    return list(result.fetchall())


def fetch_chunk_relations_window(
    session: Session,
    run_id: str,
    from_chunk: int | None = None,
    to_chunk: int | None = None,
    projection_status: str | None = None,
) -> list[Any]:
    stmt = select(ChunkRelation).where(ChunkRelation.run_id == run_id)
    if from_chunk is not None:
        stmt = stmt.where(ChunkRelation.chunk_id >= from_chunk)
    if to_chunk is not None:
        stmt = stmt.where(ChunkRelation.chunk_id <= to_chunk)
    if projection_status is not None:
        stmt = stmt.where(ChunkRelation.projection_status == projection_status)
    stmt = stmt.order_by(ChunkRelation.chunk_id, ChunkRelation.id)
    return list(session.execute(stmt).scalars().all())


def fetch_pending_chunk_relations(
    session: Session,
    run_id: str,
    to_chunk: int | None = None,
    limit: int = 200,
) -> list[ChunkRelation]:
    """获取待重试投影的关系（pending）。"""
    stmt = select(ChunkRelation).where(
        ChunkRelation.run_id == run_id,
        ChunkRelation.projection_status == "pending",
    )
    if to_chunk is not None:
        stmt = stmt.where(ChunkRelation.chunk_id <= to_chunk)
    stmt = stmt.order_by(ChunkRelation.chunk_id, ChunkRelation.id)
    if limit > 0:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars().all())


def has_annotations(session: Session, run_id: str) -> bool:
    """检查指定运行是否有标注数据"""
    stmt = select(func.count()).select_from(ChunkAnnotation).where(ChunkAnnotation.run_id == run_id)
    count = session.execute(stmt).scalar()
    return (count or 0) > 0


def is_annotate_complete(session: Session, run_id: str) -> bool:
    """
    检查标注阶段是否完成

    Returns:
        标注是否完成（标注数量 >= 分块数量）
    """
    chunks_count = session.execute(select(func.count()).select_from(Chunk).where(Chunk.run_id == run_id)).scalar() or 0
    annotations_count = (
        session.execute(
            select(func.count()).select_from(ChunkAnnotation).where(ChunkAnnotation.run_id == run_id)
        ).scalar()
        or 0
    )
    return chunks_count > 0 and annotations_count >= chunks_count


def get_annotation_by_chunk(session: Session, run_id: str, chunk_id: int) -> dict[str, Any] | None:
    """
    获取指定 chunk 的标注结果

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 修复缺失的 get_annotation_by_chunk 方法
    说明: 用于增量消歧时提取新出现的人名

    Args:
        session: 数据库会话
        run_id: 运行ID
        chunk_id: 分块ID

    Returns:
        标注结果字典，包含 characters 等字段
    """
    stmt = select(ChunkAnnotation).where(ChunkAnnotation.run_id == run_id).where(ChunkAnnotation.chunk_id == chunk_id)
    result = session.execute(stmt).scalar_one_or_none()

    if result is None:
        return None

    annotation_dict: dict[str, Any] = {
        "chunk_id": result.chunk_id,
        "event_type": result.event_type,
        "cliffhanger": result.cliffhanger,
        "pivot_moment": result.pivot_moment,
        "emotional_valence": result.emotional_valence,
        "characters": [],
    }

    char_stmt = select(ChunkCharacter).where(ChunkCharacter.run_id == run_id).where(ChunkCharacter.chunk_id == chunk_id)
    characters = session.execute(char_stmt).scalars().all()

    for char in characters:
        annotation_dict["characters"].append(
            {
                "name": char.name,
                "role_function": char.role_function,
                "action": char.action,
                "emotion_score": char.emotion_score,
            }
        )

    return annotation_dict
