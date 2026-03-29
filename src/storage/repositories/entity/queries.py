"""
实体查询相关操作

创建时间: 2026-03-17
创建者: TraeAI
任务: code-quality-refactor - 拆分entity_repository
说明: 实体查询、别名查询等操作

修改时间: 2026-03-18
修改者: TraeAI
任务: entity-type-relation-extraction
修改内容: 新增 get_entity_id_by_name 便捷方法
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert

from src.storage.models import Entity, EntityAlias

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def insert_entity(
    session: Session,
    novel_id: str,
    canonical: str,
    entity_type: str,
    run_id: str,
    first_chunk: int | None = None,
    description: str | None = None,
    confidence: float = 1.0,
) -> int | None:
    """插入实体"""
    entity = Entity(
        novel_id=novel_id,
        canonical=canonical,
        entity_type=entity_type,
        first_chunk=first_chunk,
        last_chunk=first_chunk,
        description=description,
        confidence=confidence,
        run_id=run_id,
    )
    session.add(entity)
    session.commit()
    return entity.entity_id


def insert_entity_alias(
    session: Session,
    entity_id: int,
    alias: str,
    run_id: str,
    alias_type: str | None = None,
    source_chunk: int | None = None,
) -> int | None:
    """插入实体别名"""
    stmt = (
        insert(EntityAlias)
        .values(
            entity_id=entity_id,
            alias=alias,
            alias_type=alias_type,
            source_chunk=source_chunk,
            confirm_count=1,
            run_id=run_id,
        )
        .on_conflict_do_nothing(constraint="uq_entity_aliases_entity_alias")
        .returning(EntityAlias.alias_id)
    )

    result = session.execute(stmt)
    session.commit()
    row = result.fetchone()
    return row[0] if row else None


def insert_entity_embedding(session: Session, entity_id: int, embedding: list[float]) -> None:
    """插入实体嵌入向量"""
    stmt = update(Entity).where(Entity.entity_id == entity_id).values(embedding_vector=embedding)
    session.execute(stmt)
    session.commit()


def fetch_entity_by_canonical(
    session: Session,
    novel_id: str,
    canonical: str,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """根据规范名获取实体"""
    conditions = [Entity.novel_id == novel_id, Entity.canonical == canonical]
    if run_id is not None:
        conditions.append(Entity.run_id == run_id)

    stmt = select(Entity).where(and_(*conditions))
    result = session.execute(stmt)
    entity = result.scalar_one_or_none()

    if entity is None:
        return None

    return {
        "entity_id": entity.entity_id,
        "novel_id": entity.novel_id,
        "canonical": entity.canonical,
        "entity_type": entity.entity_type,
        "first_chunk": entity.first_chunk,
        "last_chunk": entity.last_chunk,
        "description": entity.description,
        "embedding_vector": entity.embedding_vector,
        "confidence": entity.confidence,
        "run_id": entity.run_id,
    }


def fetch_all_aliases_for_entity(
    session: Session,
    entity_id: int,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """获取实体的所有别名"""
    conditions = [EntityAlias.entity_id == entity_id]
    if run_id is not None:
        conditions.append(EntityAlias.run_id == run_id)

    stmt = select(EntityAlias).where(and_(*conditions)).order_by(EntityAlias.confirm_count.desc())
    result = session.execute(stmt)
    aliases = result.scalars().all()

    return [
        {
            "alias_id": alias.alias_id,
            "alias": alias.alias,
            "alias_type": alias.alias_type,
            "source_chunk": alias.source_chunk,
            "confirm_count": alias.confirm_count,
            "run_id": alias.run_id,
        }
        for alias in aliases
    ]


def update_entity_last_chunk(session: Session, entity_id: int, last_chunk: int) -> None:
    """更新实体最后出现的分块"""
    stmt = update(Entity).where(Entity.entity_id == entity_id).values(last_chunk=last_chunk)
    session.execute(stmt)
    session.commit()


def increment_alias_confirm(session: Session, entity_id: int, alias: str) -> None:
    """增加别名确认计数"""
    stmt = (
        update(EntityAlias)
        .where(and_(EntityAlias.entity_id == entity_id, EntityAlias.alias == alias))
        .values(confirm_count=EntityAlias.confirm_count + 1)
    )
    session.execute(stmt)
    session.commit()


def fetch_entities_with_embeddings(
    session: Session, novel_id: str, run_id: str | None = None
) -> list[tuple[int, str, str, bytes | None]]:
    """获取实体及其嵌入向量"""
    conditions = [
        Entity.novel_id == novel_id,
        Entity.embedding_vector.is_not(None),
        Entity.description.is_not(None),
    ]
    if run_id is not None:
        conditions.append(Entity.run_id == run_id)

    stmt = select(
        Entity.entity_id,
        Entity.canonical,
        Entity.description,
        Entity.embedding_vector,
    ).where(and_(*conditions))
    result = session.execute(stmt)
    return [tuple(row) for row in result.fetchall()]


def get_entity_id_by_name(
    session: Session,
    novel_id: str,
    name: str,
    run_id: str | None = None,
) -> int | None:
    """
    根据实体名称获取实体ID的便捷方法

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 先尝试按规范名查询，再尝试按别名查询

    Args:
        session: 数据库会话
        novel_id: 小说ID
        name: 实体名称（规范名或别名）
        run_id: 运行ID（可选）

    Returns:
        实体ID，如果不存在返回 None
    """
    entity = fetch_entity_by_canonical(session, novel_id, name, run_id)
    if entity is not None:
        return entity["entity_id"]

    alias_conditions = [Entity.novel_id == novel_id, EntityAlias.alias == name]
    if run_id is not None:
        alias_conditions.append(Entity.run_id == run_id)
        alias_conditions.append(EntityAlias.run_id == run_id)

    alias_stmt = (
        select(Entity.entity_id)
        .join(EntityAlias, Entity.entity_id == EntityAlias.entity_id)
        .where(and_(*alias_conditions))
        .order_by(EntityAlias.confirm_count.desc())
        .limit(1)
    )
    alias_row = session.execute(alias_stmt).fetchone()
    if alias_row is not None:
        return alias_row[0]

    return None


def fetch_all_canonical_names(
    session: Session,
    novel_id: str,
    run_id: str,
) -> set[str]:
    """
    获取指定小说和运行的所有实体规范名

    创建时间: 2026-03-28
    创建者: TraeAI
    任务: fix-hierarchical-relation-filter
    说明: 用于层级关系验证，确保消歧阶段创建的实体不被错误过滤

    Args:
        session: 数据库会话
        novel_id: 小说ID
        run_id: 运行ID

    Returns:
        实体规范名集合
    """
    stmt = select(Entity.canonical).where(
        Entity.novel_id == novel_id,
        Entity.run_id == run_id,
    )
    result = session.execute(stmt)
    return {row[0] for row in result.fetchall()}
