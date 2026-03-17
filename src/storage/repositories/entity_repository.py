"""
创建时间: 2026-03-14
创建者: TraeAI
任务: Repository 层重构 - 实现 EntityRepository
说明: 实现实体数据接口，管理实体、别名、嵌入向量、关系等数据

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session，使用 ORM 查询
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from src.storage.models import (
    Entity,
    EntityAlias,
    EntityRelation,
    EntitySnapshot,
    EntityRegistry,
    ChunkCharacter,
    ChunkRelation,
)

from .base import BaseRepository


class EntityRepository(BaseRepository["EntityRepository"]):
    """
    实体数据仓库

    管理实体、别名、嵌入向量、关系等数据的存储和检索。

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session
    """

    def insert_entity(
        self,
        novel_id: str,
        canonical: str,
        entity_type: str,
        first_chunk: int | None = None,
        description: str | None = None,
        confidence: float = 1.0,
        run_id: str | None = None,
    ) -> int | None:
        """
        插入实体

        Args:
            novel_id: 小说ID
            canonical: 规范名
            entity_type: 实体类型
            first_chunk: 首次出现的分块ID（可选）
            description: 描述（可选）
            confidence: 置信度
            run_id: 运行ID（可选）

        Returns:
            插入记录的ID
        """
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
        self.session.add(entity)
        self.session.commit()
        return entity.entity_id

    def insert_entity_alias(
        self,
        entity_id: int,
        alias: str,
        alias_type: str | None = None,
        source_chunk: int | None = None,
        run_id: str | None = None,
    ) -> int | None:
        """
        插入实体别名

        使用 PostgreSQL 的 INSERT ... ON CONFLICT DO NOTHING 替代 SQLite 的 INSERT OR IGNORE

        Args:
            entity_id: 实体ID
            alias: 别名
            alias_type: 别名类型（可选）
            source_chunk: 来源分块ID（可选）
            run_id: 运行ID（可选）

        Returns:
            插入记录的ID
        """
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

        result = self.session.execute(stmt)
        self.session.commit()
        row = result.fetchone()
        return row[0] if row else None

    def insert_entity_embedding(self, entity_id: int, embedding: List[float]) -> None:
        """
        插入实体嵌入向量

        Args:
            entity_id: 实体ID
            embedding: 嵌入向量
        """
        stmt = update(Entity).where(Entity.entity_id == entity_id).values(embedding_vector=embedding)
        self.session.execute(stmt)
        self.session.commit()

    def fetch_entity_by_canonical(
        self,
        novel_id: str,
        canonical: str,
        run_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        """
        根据规范名获取实体

        Args:
            novel_id: 小说ID
            canonical: 规范名
            run_id: 运行ID（可选，用于过滤）

        Returns:
            实体字典，不存在则返回 None
        """
        conditions = [Entity.novel_id == novel_id, Entity.canonical == canonical]
        if run_id is not None:
            conditions.append(Entity.run_id == run_id)

        stmt = select(Entity).where(and_(*conditions))
        result = self.session.execute(stmt)
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

    def fetch_entity_by_alias(
        self,
        novel_id: str,
        alias: str,
        run_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        """
        根据别名获取实体

        Args:
            novel_id: 小说ID
            alias: 别名
            run_id: 运行ID（可选，用于过滤）

        Returns:
            实体字典，不存在则返回 None
        """
        conditions = [Entity.novel_id == novel_id, EntityAlias.alias == alias]
        if run_id is not None:
            conditions.append(Entity.run_id == run_id)

        stmt = (
            select(Entity, EntityAlias.alias_type, EntityAlias.confirm_count)
            .join(EntityAlias, Entity.entity_id == EntityAlias.entity_id)
            .where(and_(*conditions))
            .order_by(EntityAlias.confirm_count.desc())
            .limit(1)
        )
        result = self.session.execute(stmt)
        row = result.fetchone()

        if row is None:
            return None

        entity, alias_type, confirm_count = row
        return {
            "entity_id": entity.entity_id,
            "novel_id": entity.novel_id,
            "canonical": entity.canonical,
            "entity_type": entity.entity_type,
            "first_chunk": entity.first_chunk,
            "last_chunk": entity.last_chunk,
            "description": entity.description,
            "confidence": entity.confidence,
            "alias_type": alias_type,
            "confirm_count": confirm_count,
            "run_id": entity.run_id,
        }

    def fetch_all_aliases_for_entity(
        self,
        entity_id: int,
        run_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """
        获取实体的所有别名

        Args:
            entity_id: 实体ID
            run_id: 运行ID（可选，用于过滤）

        Returns:
            别名字典列表
        """
        conditions = [EntityAlias.entity_id == entity_id]
        if run_id is not None:
            conditions.append(EntityAlias.run_id == run_id)

        stmt = select(EntityAlias).where(and_(*conditions)).order_by(EntityAlias.confirm_count.desc())
        result = self.session.execute(stmt)
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

    def update_entity_last_chunk(self, entity_id: int, last_chunk: int) -> None:
        """
        更新实体最后出现的分块

        Args:
            entity_id: 实体ID
            last_chunk: 最后出现的分块ID
        """
        stmt = update(Entity).where(Entity.entity_id == entity_id).values(last_chunk=last_chunk)
        self.session.execute(stmt)
        self.session.commit()

    def increment_alias_confirm(self, entity_id: int, alias: str) -> None:
        """
        增加别名确认计数

        Args:
            entity_id: 实体ID
            alias: 别名
        """
        stmt = (
            update(EntityAlias)
            .where(and_(EntityAlias.entity_id == entity_id, EntityAlias.alias == alias))
            .values(confirm_count=EntityAlias.confirm_count + 1)
        )
        self.session.execute(stmt)
        self.session.commit()

    def insert_entity_registry(
        self,
        chunk_id: int,
        name: str,
        role: str,
        last_action: str,
        last_emotion: str,
        emotion_score: int,
        run_id: str | None = None,
    ) -> None:
        """
        插入实体注册记录

        Args:
            chunk_id: 分块ID
            name: 名称
            role: 角色
            last_action: 最后动作
            last_emotion: 最后情绪
            emotion_score: 情绪分数
            run_id: 运行ID（可选）
        """
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
        self.session.add(registry)
        self.session.commit()

    def fetch_active_entities(
        self,
        current_chunk_id: int,
        lookback: int = 10,
        run_id: str | None = None,
    ) -> List[Tuple[int, str, str, str, str, int]]:
        """
        获取活跃实体

        Args:
            current_chunk_id: 当前分块ID
            lookback: 回溯范围
            run_id: 运行ID（可选，用于过滤）

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
        result = self.session.execute(stmt)
        return [tuple(row) for row in result.fetchall()]

    def insert_entity_relation(
        self,
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

        Args:
            novel_id: 小说ID
            from_entity: 源实体ID
            to_entity: 目标实体ID
            rel_type: 关系类型
            first_chunk: 首次出现的分块ID（可选）
            tension: 张力值
            run_id: 运行ID（可选）

        Returns:
            插入记录的ID
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

        result = self.session.execute(stmt)
        self.session.commit()
        row = result.fetchone()
        return row[0] if row else None

    def _fetch_relations(
        self,
        novel_id: str | None = None,
        entity_id: int | None = None,
        is_active_only: bool = False,
        run_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """
        辅助函数：统一查询实体关系的 ORM 逻辑

        Args:
            novel_id: 小说ID（可选）
            entity_id: 实体ID（可选）
            is_active_only: 是否只查询活跃关系
            run_id: 运行ID（可选）

        Returns:
            关系字典列表
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

        result = self.session.execute(stmt)
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
        self,
        entity_id: int,
        novel_id: str | None = None,
        run_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """
        获取实体的所有关系

        Args:
            entity_id: 实体ID
            novel_id: 小说ID（可选）
            run_id: 运行ID（可选）

        Returns:
            关系字典列表
        """
        return self._fetch_relations(
            novel_id=novel_id,
            entity_id=entity_id,
            is_active_only=False,
            run_id=run_id,
        )

    def fetch_active_relations(
        self,
        novel_id: str,
        entity_id: int | None = None,
        run_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """
        获取活跃关系

        Args:
            novel_id: 小说ID
            entity_id: 实体ID（可选）
            run_id: 运行ID（可选）

        Returns:
            活跃关系字典列表
        """
        return self._fetch_relations(
            novel_id=novel_id,
            entity_id=entity_id,
            is_active_only=True,
            run_id=run_id,
        )

    def update_relation_last_chunk(self, rel_id: int, last_chunk: int) -> None:
        """
        更新关系最后出现的分块

        Args:
            rel_id: 关系ID
            last_chunk: 最后出现的分块ID
        """
        stmt = update(EntityRelation).where(EntityRelation.rel_id == rel_id).values(last_chunk=last_chunk)
        self.session.execute(stmt)
        self.session.commit()

    def fetch_all_aliases_with_canonical(self, novel_id: str, run_id: str | None = None) -> List[Tuple[str, str]]:
        """
        获取所有别名及其规范名映射

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 graph.py 和 retriever.py

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: postgresql-migration
        修改内容: 迁移到 SQLAlchemy ORM

        Args:
            novel_id: 小说ID
            run_id: 运行ID（可选）

        Returns:
            (canonical, alias) 元组列表
        """
        conditions = [Entity.novel_id == novel_id]
        if run_id is not None:
            conditions.append(Entity.run_id == run_id)

        stmt = (
            select(Entity.canonical, EntityAlias.alias)
            .join(EntityAlias, Entity.entity_id == EntityAlias.entity_id)
            .where(and_(*conditions))
        )
        result = self.session.execute(stmt)
        return [tuple(row) for row in result.fetchall()]

    def fetch_entities_with_embeddings(
        self, novel_id: str, run_id: str | None = None
    ) -> List[Tuple[int, str, str, bytes | None]]:
        """
        获取实体及其嵌入向量

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 retriever.py

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: postgresql-migration
        修改内容: 迁移到 SQLAlchemy ORM

        Args:
            novel_id: 小说ID
            run_id: 运行ID（可选）

        Returns:
            (entity_id, canonical, description, embedding_vector) 元组列表
        """
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
        result = self.session.execute(stmt)
        return [tuple(row) for row in result.fetchall()]

    def fetch_distinct_characters(self, run_id: str) -> List[Tuple[str]]:
        """
        获取所有不重复的角色名

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 graph.py

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: postgresql-migration
        修改内容: 迁移到 SQLAlchemy ORM

        Args:
            run_id: 运行ID

        Returns:
            (name,) 元组列表
        """
        stmt = select(ChunkCharacter.name).where(ChunkCharacter.run_id == run_id).distinct()
        result = self.session.execute(stmt)
        return [(row[0],) for row in result.fetchall()]

    def fetch_character_metadata_sequence(self, run_id: str) -> List[Tuple[str, int, str, str]]:
        """
        获取角色元数据序列（按 chunk_id 排序）

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 graph.py

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: postgresql-migration
        修改内容: 迁移到 SQLAlchemy ORM

        Args:
            run_id: 运行ID

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
        result = self.session.execute(stmt)
        return [tuple(row) for row in result.fetchall()]

    def fetch_relation_sequence(self, run_id: str) -> List[Tuple[str, str, str, str, int]]:
        """
        获取关系序列（按 chunk_id 排序）

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 graph.py

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: postgresql-migration
        修改内容: 迁移到 SQLAlchemy ORM

        Args:
            run_id: 运行ID

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
        result = self.session.execute(stmt)
        return [tuple(row) for row in result.fetchall()]

    def insert_entity_snapshot(
        self,
        novel_id: str,
        entity_id: int,
        chunk_id: int,
        state_json: str,
        run_id: str | None = None,
    ) -> int | None:
        """
        插入实体快照

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: storage-layer-decoupling
        修改内容: 新增方法支持测试

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: postgresql-migration
        修改内容: 迁移到 SQLAlchemy ORM

        Args:
            novel_id: 小说ID
            entity_id: 实体ID
            chunk_id: 分块ID
            state_json: 状态JSON
            run_id: 运行ID（可选）

        Returns:
            插入记录的ID
        """
        snapshot = EntitySnapshot(
            novel_id=novel_id,
            entity_id=entity_id,
            chunk_id=chunk_id,
            state_json=state_json,
            run_id=run_id,
        )
        self.session.add(snapshot)
        self.session.commit()
        return snapshot.snap_id

    def fetch_snapshots_by_chunk(
        self,
        novel_id: str,
        start_chunk: int,
        end_chunk: int,
        run_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """
        获取指定分块范围内的快照

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: storage-layer-decoupling
        修改内容: 新增方法支持测试

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: postgresql-migration
        修改内容: 迁移到 SQLAlchemy ORM

        Args:
            novel_id: 小说ID
            start_chunk: 起始分块ID
            end_chunk: 结束分块ID
            run_id: 运行ID（可选）

        Returns:
            快照字典列表
        """
        conditions = [
            EntitySnapshot.novel_id == novel_id,
            EntitySnapshot.chunk_id >= start_chunk,
            EntitySnapshot.chunk_id <= end_chunk,
        ]
        if run_id is not None:
            conditions.append(EntitySnapshot.run_id == run_id)

        stmt = select(EntitySnapshot).where(and_(*conditions)).order_by(EntitySnapshot.chunk_id)
        result = self.session.execute(stmt)
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
        self,
        novel_id: str,
        run_id: str | None = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        获取最近的快照

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: storage-layer-decoupling
        修改内容: 新增方法支持测试

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: postgresql-migration
        修改内容: 迁移到 SQLAlchemy ORM

        Args:
            novel_id: 小说ID
            run_id: 运行ID（可选）
            limit: 返回数量限制

        Returns:
            快照字典列表
        """
        conditions = [EntitySnapshot.novel_id == novel_id]
        if run_id is not None:
            conditions.append(EntitySnapshot.run_id == run_id)

        stmt = select(EntitySnapshot).where(and_(*conditions)).order_by(EntitySnapshot.chunk_id.desc()).limit(limit)
        result = self.session.execute(stmt)
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
