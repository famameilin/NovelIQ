"""
实体关系相关操作

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分entity_repository
说明: 实体关系查询、插入、更新等操作
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from src.storage.models import EntityRelation

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def insert_entity_relation(
    session: Session,
    novel_id: str,
    from_entity: int,
    to_entity: int,
    rel_type: str,
    first_chunk: int | None = None,
    tension: float = 0.0,
    run_id: str | None = None,
) -> int | None:
    """
    插入实体关系

    使用 PostgreSQL 的 INSERT ... ON CONFLICT DO NOTHING 替代 SQLite 的 INSERT OR IGNORE
    """
    stmt = (
        insert(EntityRelation)
        .values(
            novel_id=novel_id,
            from_entity=from_entity,
            to_entity=to_entity,
            rel_type=rel_type,
            first_chunk=first_chunk,
            last_chunk=first_chunk,
            tension=tension,
            run_id=run_id,
        )
        .on_conflict_do_nothing(constraint="uq_entity_relations")
        .returning(EntityRelation.rel_id)
    )

    result = session.execute(stmt)
    session.commit()
    row = result.fetchone()
    return row[0] if row else None


def _fetch_relations(
    session: Session,
    novel_id: str | None = None,
    entity_id: int | None = None,
    is_active_only: bool = False,
    run_id: str | None = None,
) -> List[Dict[str, Any]]:
    """
    辅助函数：统一查询实体关系的 ORM 逻辑
    """
    conditions = []

    if novel_id is not None:
        conditions.append(EntityRelation.novel_id == novel_id)

    if entity_id is not None:
        conditions.append(
            or_(
                EntityRelation.from_entity == entity_id,
                EntityRelation.to_entity == entity_id,
            )
        )

    if is_active_only:
        conditions.append(EntityRelation.is_active == 1)

    if run_id is not None:
        conditions.append(EntityRelation.run_id == run_id)

    stmt = select(EntityRelation)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.order_by(EntityRelation.last_chunk.desc())

    result = session.execute(stmt)
    relations = result.scalars().all()

    return [
        {
            "rel_id": rel.rel_id,
            "novel_id": rel.novel_id,
            "from_entity": rel.from_entity,
            "to_entity": rel.to_entity,
            "rel_type": rel.rel_type,
            "first_chunk": rel.first_chunk,
            "last_chunk": rel.last_chunk,
            "tension": rel.tension,
            "is_active": bool(rel.is_active),
            "run_id": rel.run_id,
        }
        for rel in relations
    ]


def fetch_relations_for_entity(
    session: Session,
    entity_id: int,
    novel_id: str | None = None,
    run_id: str | None = None,
) -> List[Dict[str, Any]]:
    """获取实体的所有关系"""
    return _fetch_relations(
        session=session,
        novel_id=novel_id,
        entity_id=entity_id,
        is_active_only=False,
        run_id=run_id,
    )


def fetch_active_relations(
    session: Session,
    novel_id: str,
    entity_id: int | None = None,
    run_id: str | None = None,
) -> List[Dict[str, Any]]:
    """获取活跃关系"""
    return _fetch_relations(
        session=session,
        novel_id=novel_id,
        entity_id=entity_id,
        is_active_only=True,
        run_id=run_id,
    )


def update_relation_last_chunk(session: Session, rel_id: int, last_chunk: int) -> None:
    """更新关系最后出现的分块"""
    stmt = update(EntityRelation).where(EntityRelation.rel_id == rel_id).values(last_chunk=last_chunk)
    session.execute(stmt)
    session.commit()
