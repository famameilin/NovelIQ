"""
实体元数据相关操作

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分entity_repository
说明: 实体注册、快照、角色元数据等操作
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, select

from src.storage.models import (
    ChunkCharacter,
    ChunkRelation,
    EntityRegistry,
    EntitySnapshot,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def insert_entity_registry(
    session: Session,
    chunk_id: int,
    name: str,
    role: str,
    last_action: str,
    last_emotion: str,
    emotion_score: int,
    run_id: str | None = None,
) -> None:
    """插入实体注册记录"""
    now = datetime.now().isoformat()
    registry = EntityRegistry(
        chunk_id=chunk_id,
        name=name,
        role=role,
        last_action=last_action,
        last_emotion=last_emotion,
        emotion_score=emotion_score,
        updated_at=now,
        run_id=run_id,
    )
    session.add(registry)
    session.commit()


def fetch_active_entities(
    session: Session,
    current_chunk_id: int,
    lookback: int = 10,
    run_id: str | None = None,
) -> list[tuple[int, str, str, str, str, int]]:
    """
    获取活跃实体

    Returns:
        活跃实体元组列表 (entity_id, name, role, last_action, last_emotion, emotion_score)
    """
    start_chunk = max(0, current_chunk_id - lookback)
    conditions = [
        EntityRegistry.chunk_id >= start_chunk,
        EntityRegistry.chunk_id <= current_chunk_id,
    ]
    if run_id is not None:
        conditions.append(EntityRegistry.run_id == run_id)

    stmt = (
        select(
            EntityRegistry.entity_id,
            EntityRegistry.name,
            EntityRegistry.role,
            EntityRegistry.last_action,
            EntityRegistry.last_emotion,
            EntityRegistry.emotion_score,
        )
        .where(and_(*conditions))
        .order_by(EntityRegistry.chunk_id.desc(), EntityRegistry.entity_id.desc())
    )
    result = session.execute(stmt)
    return [tuple(row) for row in result.fetchall()]


def fetch_distinct_characters(session: Session, run_id: str) -> list[tuple[str]]:
    """获取所有不重复的角色名"""
    stmt = select(ChunkCharacter.name).where(ChunkCharacter.run_id == run_id).distinct()
    result = session.execute(stmt)
    return [(row[0],) for row in result.fetchall()]


def fetch_character_metadata_sequence(session: Session, run_id: str) -> list[tuple[str, int, str, str]]:
    """
    获取角色元数据序列（按 chunk_id 排序）

    Returns:
        (name, chunk_id, role_function, emotion_score) 元组列表
    """
    stmt = (
        select(
            ChunkCharacter.name,
            ChunkCharacter.chunk_id,
            ChunkCharacter.role_function,
            ChunkCharacter.emotion_score,
        )
        .where(ChunkCharacter.run_id == run_id)
        .order_by(ChunkCharacter.chunk_id)
    )
    result = session.execute(stmt)
    return [tuple(row) for row in result.fetchall()]


def fetch_relation_sequence(session: Session, run_id: str) -> list[tuple[str, str, str, str, int]]:
    """
    获取关系序列（按 chunk_id 排序）

    Returns:
        (from_char, to_char, type, change, chunk_id) 元组列表
    """
    stmt = (
        select(
            ChunkRelation.from_char,
            ChunkRelation.to_char,
            ChunkRelation.type,
            ChunkRelation.change,
            ChunkRelation.chunk_id,
        )
        .where(ChunkRelation.run_id == run_id)
        .order_by(ChunkRelation.chunk_id)
    )
    result = session.execute(stmt)
    return [tuple(row) for row in result.fetchall()]


def insert_entity_snapshot(
    session: Session,
    novel_id: str,
    entity_id: int,
    chunk_id: int,
    state_json: str,
    run_id: str | None = None,
) -> int | None:
    """插入实体快照"""
    snapshot = EntitySnapshot(
        novel_id=novel_id,
        entity_id=entity_id,
        chunk_id=chunk_id,
        state_json=state_json,
        run_id=run_id,
    )
    session.add(snapshot)
    session.commit()
    return snapshot.snap_id


def fetch_snapshots_by_chunk(
    session: Session,
    novel_id: str,
    start_chunk: int,
    end_chunk: int,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """获取指定分块范围内的快照"""
    conditions = [
        EntitySnapshot.novel_id == novel_id,
        EntitySnapshot.chunk_id >= start_chunk,
        EntitySnapshot.chunk_id <= end_chunk,
    ]
    if run_id is not None:
        conditions.append(EntitySnapshot.run_id == run_id)

    stmt = select(EntitySnapshot).where(and_(*conditions)).order_by(EntitySnapshot.chunk_id)
    result = session.execute(stmt)
    snapshots = result.scalars().all()

    return [
        {
            "snap_id": snap.snap_id,
            "novel_id": snap.novel_id,
            "entity_id": snap.entity_id,
            "chunk_id": snap.chunk_id,
            "state_json": snap.state_json,
            "run_id": snap.run_id,
        }
        for snap in snapshots
    ]


def fetch_recent_snapshots(
    session: Session,
    novel_id: str,
    run_id: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """获取最近的快照"""
    conditions = [EntitySnapshot.novel_id == novel_id]
    if run_id is not None:
        conditions.append(EntitySnapshot.run_id == run_id)

    stmt = select(EntitySnapshot).where(and_(*conditions)).order_by(EntitySnapshot.chunk_id.desc()).limit(limit)
    result = session.execute(stmt)
    snapshots = result.scalars().all()

    return [
        {
            "snap_id": snap.snap_id,
            "novel_id": snap.novel_id,
            "entity_id": snap.entity_id,
            "chunk_id": snap.chunk_id,
            "state_json": snap.state_json,
            "run_id": snap.run_id,
        }
        for snap in snapshots
    ]
