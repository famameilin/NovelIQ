"""
创建时间: 2026-03-14
创建者: TraeAI
任务: 实现 AnnotationRepository 类
说明: 标注数据的数据库操作实现，管理分块标注、角色、对话、关系等数据

修改时间: 2026-03-14
修改者: TraeAI
任务: refactor-routes-use-repository
修改内容: 添加查询方法 fetch_chunk_annotations_full, fetch_chunk_characters, fetch_chunk_relations, fetch_chunk_dialogues, fetch_alias_map

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session，使用 ORM 模型替代原生 SQL
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Sequence, Set

from sqlalchemy import func, select, update, delete, or_
from sqlalchemy.dialects.postgresql import insert

from src.models.local.schema import (
    ChunkAnnotation as ChunkAnnotationSchema,
    CharacterSnapshot,
    DialogueSnapshot,
    RelationChangeSnapshot,
    ForeshadowingResult,
)
from src.storage.models import (
    ChunkAnnotation,
    ChunkCharacter,
    ChunkRelation,
    ChunkDialogue,
    ChunkForeshadowing,
    CharacterAppearance,
    Entity,
    EntityAlias,
    Chunk,
)

from .base import BaseRepository


class AnnotationRepository(BaseRepository[Dict[str, Any]]):
    """
    标注数据 Repository

    管理分块标注、角色、对话、关系等数据。
    所有操作都基于 run_id 进行数据隔离。

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session
    """

    def insert_chunk_annotation(self, run_id: str, chunk_id: int, annotation: ChunkAnnotationSchema) -> None:
        """
        插入分块标注

        Args:
            run_id: 运行ID
            chunk_id: 分块ID
            annotation: 标注数据
        """
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
        self.session.add(record)
        self.session.commit()

    def insert_chunk_characters(self, run_id: str, chunk_id: int, characters: Sequence[CharacterSnapshot]) -> None:
        """
        插入分块角色数据

        Args:
            run_id: 运行ID
            chunk_id: 分块ID
            characters: 角色快照序列
        """
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
        self.session.add_all(records)
        self.session.commit()

    def insert_chunk_relations(self, run_id: str, chunk_id: int, relations: Sequence[RelationChangeSnapshot]) -> None:
        """
        插入分块关系数据

        Args:
            run_id: 运行ID
            chunk_id: 分块ID
            relations: 关系变更快照序列
        """
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
        self.session.add_all(records)
        self.session.commit()

    def insert_chunk_dialogues(
        self,
        run_id: str,
        chunk_id: int,
        dialogues: Sequence[DialogueSnapshot],
        lengths: Sequence[int] | None = None,
    ) -> None:
        """
        插入分块对话数据

        Args:
            run_id: 运行ID
            chunk_id: 分块ID
            dialogues: 对话快照序列
            lengths: 对话长度序列（可选）
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
        self.session.add_all(records)
        self.session.commit()

    def insert_foreshadowing(self, run_id: str, chunk_id: int, result: ForeshadowingResult) -> None:
        """
        插入伏笔分析结果

        Args:
            run_id: 运行ID
            chunk_id: 分块ID
            result: 伏笔分析结果
        """
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
        self.session.add(record)
        self.session.commit()

    def fetch_chunk_annotations(self, run_id: str) -> List[Any]:
        """
        获取指定运行的所有分块标注

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, event_type, cliffhanger) 元组列表
        """
        stmt = (
            select(ChunkAnnotation.chunk_id, ChunkAnnotation.event_type, ChunkAnnotation.cliffhanger)
            .where(ChunkAnnotation.run_id == run_id)
            .order_by(ChunkAnnotation.chunk_id)
        )
        result = self.session.execute(stmt)
        return list(result.fetchall())

    def fetch_chunk_annotations_full(self, run_id: str) -> List[Any]:
        """
        获取完整的分块标注数据（用于结果导出）

        Args:
            run_id: 运行ID

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
            .where(or_(ChunkAnnotation.run_id == run_id, ChunkAnnotation.run_id.is_(None)))
            .order_by(ChunkAnnotation.chunk_id)
        )
        result = self.session.execute(stmt)
        return list(result.fetchall())

    def fetch_chunk_characters_full(self, run_id: str) -> List[Any]:
        """
        获取完整的分块角色数据

        Args:
            run_id: 运行ID

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
            .where(or_(ChunkCharacter.run_id == run_id, ChunkCharacter.run_id.is_(None)))
            .order_by(ChunkCharacter.chunk_id)
        )
        result = self.session.execute(stmt)
        return list(result.fetchall())

    def fetch_chunk_relations_full(self, run_id: str) -> List[Any]:
        """
        获取完整的分块关系数据

        Args:
            run_id: 运行ID

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
            )
            .where(or_(ChunkRelation.run_id == run_id, ChunkRelation.run_id.is_(None)))
            .order_by(ChunkRelation.chunk_id)
        )
        result = self.session.execute(stmt)
        return list(result.fetchall())

    def fetch_chunk_dialogues_full(self, run_id: str) -> List[Any]:
        """
        获取完整的分块对话数据

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, speaker, length) 元组列表
        """
        stmt = (
            select(ChunkDialogue.chunk_id, ChunkDialogue.speaker, ChunkDialogue.length)
            .where(or_(ChunkDialogue.run_id == run_id, ChunkDialogue.run_id.is_(None)))
            .order_by(ChunkDialogue.chunk_id)
        )
        result = self.session.execute(stmt)
        return list(result.fetchall())

    def fetch_alias_map(self, run_id: str) -> Dict[str, str]:
        """
        获取别名映射表

        Args:
            run_id: 运行ID

        Returns:
            别名到规范名的映射字典
        """
        stmt = select(EntityAlias.alias, EntityAlias.alias_type).where(
            EntityAlias.alias_type == "disambiguation"
        )
        result = self.session.execute(stmt)
        return {row[0]: row[1] for row in result.fetchall()}

    def fetch_annotated_chunk_ids(self, run_id: str) -> Set[int]:
        """
        获取指定运行已标注的分块ID集合

        Args:
            run_id: 运行ID

        Returns:
            已标注分块ID集合
        """
        stmt = select(ChunkAnnotation.chunk_id).where(ChunkAnnotation.run_id == run_id)
        result = self.session.execute(stmt)
        return {row[0] for row in result.fetchall()}

    def fetch_all_character_names(self, run_id: str) -> List[Dict[str, str | int]]:
        """
        获取指定运行的所有角色名及出现频次

        同时从 chunk_characters 和 character_appearances 表获取名字，
        确保外貌描述性称呼也能参与消歧。

        Args:
            run_id: 运行ID

        Returns:
            [{"name": "角色名", "count": 频次}, ...] 列表
        """
        stmt1 = (
            select(ChunkCharacter.name, func.count().label("count"))
            .where(ChunkCharacter.run_id == run_id)
            .group_by(ChunkCharacter.name)
        )
        stmt2 = (
            select(CharacterAppearance.raw_name.label("name"), func.count().label("count"))
            .where(CharacterAppearance.run_id == run_id)
            .group_by(CharacterAppearance.raw_name)
        )
        result1 = self.session.execute(stmt1).fetchall()
        result2 = self.session.execute(stmt2).fetchall()
        name_counts: dict[str, int] = {}
        for row in result1:
            name = row[0]
            count = row[1]
            if name:
                name_counts[name] = name_counts.get(name, 0) + count
        for row in result2:
            name = row[0]
            count = row[1]
            if name:
                name_counts[name] = name_counts.get(name, 0) + count
        return [{"name": name, "count": count} for name, count in sorted(name_counts.items(), key=lambda x: -x[1])]

    def update_character_names(self, run_id: str, alias_map: Dict[str, str], novel_id: str = "default") -> None:
        """
        更新角色名称（消歧）

        将别名更新为规范名，并创建实体和别名映射记录。

        Args:
            run_id: 运行ID
            alias_map: 别名到规范名的映射
            novel_id: 小说ID
        """
        canonical_to_entity_id: dict[str, int] = {}
        for alias, canonical in alias_map.items():
            if alias != canonical:
                self._update_character_names_in_tables(alias, canonical, run_id)
            entity_id = self._ensure_entity_exists(novel_id, canonical, canonical_to_entity_id)
            if entity_id is not None:
                self._create_alias_mapping(entity_id, alias, canonical, run_id)
        self.session.execute(
            delete(ChunkRelation).where(
                ChunkRelation.from_char == ChunkRelation.to_char,
                ChunkRelation.run_id == run_id,
            )
        )
        self.session.commit()

    def _update_character_names_in_tables(self, alias: str, canonical: str, run_id: str) -> None:
        """
        更新多个表中的角色名（从别名更新为规范名）

        Args:
            alias: 别名
            canonical: 规范名
            run_id: 运行ID
        """
        self.session.execute(
            update(ChunkCharacter)
            .where(ChunkCharacter.name == alias, ChunkCharacter.run_id == run_id)
            .values(name=canonical)
        )
        self.session.execute(
            update(ChunkRelation)
            .where(ChunkRelation.from_char == alias, ChunkRelation.run_id == run_id)
            .values(from_char=canonical)
        )
        self.session.execute(
            update(ChunkRelation)
            .where(ChunkRelation.to_char == alias, ChunkRelation.run_id == run_id)
            .values(to_char=canonical)
        )
        self.session.execute(
            update(ChunkDialogue)
            .where(ChunkDialogue.speaker == alias, ChunkDialogue.run_id == run_id)
            .values(speaker=canonical)
        )

    def _ensure_entity_exists(
        self, novel_id: str, canonical: str, canonical_to_entity_id: dict[str, int]
    ) -> int | None:
        """
        确保实体存在，返回实体ID

        Args:
            novel_id: 小说ID
            canonical: 规范名
            canonical_to_entity_id: 规范名到实体ID的缓存映射

        Returns:
            实体ID，插入失败则返回 None
        """
        if canonical in canonical_to_entity_id:
            return canonical_to_entity_id[canonical]
        stmt = select(Entity.entity_id).where(
            Entity.novel_id == novel_id,
            Entity.canonical == canonical,
        )
        row = self.session.execute(stmt).fetchone()
        if row:
            canonical_to_entity_id[canonical] = row[0]
            return row[0]
        entity = Entity(
            novel_id=novel_id,
            canonical=canonical,
            entity_type="character",
            first_chunk=None,
            last_chunk=None,
            description=None,
            confidence=1.0,
        )
        self.session.add(entity)
        self.session.flush()
        if entity.entity_id is not None:
            canonical_to_entity_id[canonical] = entity.entity_id
            return entity.entity_id
        return None

    def _create_alias_mapping(self, entity_id: int, alias: str, canonical: str, run_id: str) -> None:
        """
        创建别名映射记录

        使用 PostgreSQL 的 INSERT ... ON CONFLICT DO NOTHING 实现 INSERT OR IGNORE 语义。

        Args:
            entity_id: 实体ID
            alias: 别名
            canonical: 规范名
            run_id: 运行ID
        """
        alias_type = "disambiguation" if alias != canonical else "canonical"
        alias_value = alias if alias != canonical else canonical
        stmt = insert(EntityAlias).values(
            entity_id=entity_id,
            alias=alias_value,
            alias_type=alias_type,
            source_chunk=None,
            confirm_count=1,
            run_id=run_id,
        ).on_conflict_do_nothing(constraint="uq_entity_aliases_entity_alias")
        self.session.execute(stmt)

    def fetch_full_annotations(self, run_id: str) -> List[Any]:
        """
        获取完整的分块标注数据

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 aggregate_metrics.py

        Args:
            run_id: 运行ID

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
        result = self.session.execute(stmt)
        return list(result.fetchall())

    def fetch_characters_with_scores(self, run_id: str) -> List[Any]:
        """
        获取角色数据（含情绪分数）

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 aggregate_metrics.py

        Args:
            run_id: 运行ID

        Returns:
            (name, role_function, emotion_score) 元组列表
        """
        stmt = select(
            ChunkCharacter.name,
            ChunkCharacter.role_function,
            ChunkCharacter.emotion_score,
        ).where(ChunkCharacter.run_id == run_id)
        result = self.session.execute(stmt)
        return list(result.fetchall())

    def fetch_character_emotion_sequence(self, run_id: str) -> List[Any]:
        """
        获取角色情绪序列（按 chunk_id 排序）

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 aggregate_metrics.py

        Args:
            run_id: 运行ID

        Returns:
            (name, emotion_score) 元组列表，按 chunk_id 排序
        """
        stmt = (
            select(ChunkCharacter.name, ChunkCharacter.emotion_score)
            .where(ChunkCharacter.run_id == run_id)
            .order_by(ChunkCharacter.chunk_id)
        )
        result = self.session.execute(stmt)
        return list(result.fetchall())

    def fetch_relations(self, run_id: str) -> List[Any]:
        """
        获取角色关系（仅 from/to）

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 aggregate_metrics.py

        Args:
            run_id: 运行ID

        Returns:
            (from_char, to_char) 元组列表
        """
        stmt = select(ChunkRelation.from_char, ChunkRelation.to_char).where(
            ChunkRelation.run_id == run_id
        )
        result = self.session.execute(stmt)
        return list(result.fetchall())

    def fetch_full_relations(self, run_id: str) -> List[Any]:
        """
        获取完整角色关系

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 aggregate_metrics.py

        Args:
            run_id: 运行ID

        Returns:
            (from_char, to_char, type, change) 元组列表
        """
        stmt = select(
            ChunkRelation.from_char,
            ChunkRelation.to_char,
            ChunkRelation.type,
            ChunkRelation.change,
        ).where(ChunkRelation.run_id == run_id)
        result = self.session.execute(stmt)
        return list(result.fetchall())

    def has_annotations(self, run_id: str) -> bool:
        """
        检查指定运行是否有标注数据

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: storage-layer-decoupling
        修改内容: 新增方法替代 operations.completeness.has_annotations

        Args:
            run_id: 运行ID

        Returns:
            是否有标注数据
        """
        stmt = select(func.count()).select_from(ChunkAnnotation).where(
            ChunkAnnotation.run_id == run_id
        )
        count = self.session.execute(stmt).scalar()
        return (count or 0) > 0

    def is_annotate_complete(self, run_id: str) -> bool:
        """
        检查标注阶段是否完成

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: storage-layer-decoupling
        修改内容: 新增方法替代 operations.completeness.is_annotate_complete

        Args:
            run_id: 运行ID

        Returns:
            标注是否完成（标注数量 >= 分块数量）
        """
        chunks_count = self.session.execute(
            select(func.count()).select_from(Chunk).where(Chunk.run_id == run_id)
        ).scalar() or 0
        annotations_count = self.session.execute(
            select(func.count()).select_from(ChunkAnnotation).where(
                ChunkAnnotation.run_id == run_id
            )
        ).scalar() or 0
        return chunks_count > 0 and annotations_count >= chunks_count
