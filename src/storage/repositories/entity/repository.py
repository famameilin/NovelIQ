"""
实体数据 Repository 主类

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分entity_repository
说明: 主Repository类，通过组合方式使用各模块函数
"""

from __future__ import annotations

from typing import Any

from src.storage.repositories.base import BaseRepository

# 导入各模块函数
from . import metadata, queries, relations


class EntityRepository(BaseRepository["EntityRepository"]):
    """
    实体数据仓库

    管理实体、别名、嵌入向量、关系等数据的存储和检索。

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - 拆分entity_repository
    修改内容: 使用函数组合方式重组代码结构，拆分为3个模块：
        - queries: 实体查询、别名查询、嵌入向量
        - relations: 实体关系查询、插入、更新
        - metadata: 实体注册、快照、角色元数据
    """

    # ==================== queries 模块方法 ====================

    def insert_entity(
        self,
        novel_id: str,
        canonical: str,
        entity_type: str,
        run_id: str,
        first_chunk: int | None = None,
        description: str | None = None,
        confidence: float = 1.0,
    ) -> int | None:
        """插入实体"""
        return queries.insert_entity(
            self.session, novel_id, canonical, entity_type, run_id, first_chunk, description, confidence
        )

    def insert_entity_alias(
        self,
        entity_id: int,
        alias: str,
        run_id: str,
        alias_type: str | None = None,
        source_chunk: int | None = None,
    ) -> int | None:
        """插入实体别名"""
        return queries.insert_entity_alias(
            self.session, entity_id, alias, run_id, alias_type, source_chunk
        )

    def insert_entity_embedding(self, entity_id: int, embedding: list[float]) -> None:
        """插入实体嵌入向量"""
        return queries.insert_entity_embedding(self.session, entity_id, embedding)

    def fetch_entity_by_canonical(
        self,
        novel_id: str,
        canonical: str,
        run_id: str | None = None,
    ) -> dict[str, Any] | None:
        """根据规范名获取实体"""
        return queries.fetch_entity_by_canonical(self.session, novel_id, canonical, run_id)

    def fetch_entity_by_alias(
        self,
        novel_id: str,
        alias: str,
        run_id: str | None = None,
    ) -> dict[str, Any] | None:
        """根据别名获取实体"""
        return queries.fetch_entity_by_alias(self.session, novel_id, alias, run_id)

    def fetch_all_aliases_for_entity(
        self,
        entity_id: int,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取实体的所有别名"""
        return queries.fetch_all_aliases_for_entity(self.session, entity_id, run_id)

    def update_entity_last_chunk(self, entity_id: int, last_chunk: int) -> None:
        """更新实体最后出现的分块"""
        return queries.update_entity_last_chunk(self.session, entity_id, last_chunk)

    def increment_alias_confirm(self, entity_id: int, alias: str) -> None:
        """增加别名确认计数"""
        return queries.increment_alias_confirm(self.session, entity_id, alias)

    def fetch_all_aliases_with_canonical(self, novel_id: str, run_id: str | None = None) -> list[tuple[str, str]]:
        """获取所有别名及其规范名映射"""
        return queries.fetch_all_aliases_with_canonical(self.session, novel_id, run_id)

    def fetch_entities_with_embeddings(
        self, novel_id: str, run_id: str | None = None
    ) -> list[tuple[int, str, str, bytes | None]]:
        """获取实体及其嵌入向量"""
        return queries.fetch_entities_with_embeddings(self.session, novel_id, run_id)

    def get_entity_id_by_name(
        self,
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
        """
        return queries.get_entity_id_by_name(self.session, novel_id, name, run_id)

    def fetch_all_canonical_names(
        self,
        novel_id: str,
        run_id: str,
    ) -> set[str]:
        """
        获取指定小说和运行的所有实体规范名

        创建时间: 2026-03-28
        创建者: TraeAI
        任务: fix-hierarchical-relation-filter
        说明: 用于层级关系验证，确保消歧阶段创建的实体不被错误过滤
        """
        return queries.fetch_all_canonical_names(self.session, novel_id, run_id)

    # ==================== relations 模块方法 ====================

    def insert_entity_relation(
        self,
        novel_id: str,
        from_entity: int,
        to_entity: int,
        rel_type: str,
        run_id: str,
        first_chunk: int | None = None,
        tension: float = 0.0,
        rel_category: str = "interpersonal",
    ) -> int | None:
        """插入实体关系"""
        return relations.insert_entity_relation(
            self.session, novel_id, from_entity, to_entity, rel_type, run_id, first_chunk, tension, rel_category
        )

    def fetch_relations_for_entity(
        self,
        entity_id: int,
        novel_id: str | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取实体的所有关系"""
        return relations.fetch_relations_for_entity(self.session, entity_id, novel_id, run_id)

    def fetch_active_relations(
        self,
        novel_id: str,
        entity_id: int | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取活跃关系"""
        return relations.fetch_active_relations(self.session, novel_id, entity_id, run_id)

    def update_relation_last_chunk(self, rel_id: int, last_chunk: int) -> None:
        """更新关系最后出现的分块"""
        return relations.update_relation_last_chunk(self.session, rel_id, last_chunk)

    def fetch_hierarchical_relations_with_names(
        self,
        novel_id: str,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取层级关系（带实体名称）"""
        return relations.fetch_hierarchical_relations_with_names(self.session, novel_id, run_id)

    # ==================== metadata 模块方法 ====================

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
        """插入实体注册记录"""
        return metadata.insert_entity_registry(
            self.session, chunk_id, name, role, last_action, last_emotion, emotion_score, run_id
        )

    def fetch_active_entities(
        self,
        current_chunk_id: int,
        lookback: int = 10,
        run_id: str | None = None,
    ) -> list[tuple[int, str, str, str, str, int]]:
        """获取活跃实体"""
        return metadata.fetch_active_entities(self.session, current_chunk_id, lookback, run_id)

    def fetch_distinct_characters(self, run_id: str) -> list[tuple[str]]:
        """获取所有不重复的角色名"""
        return metadata.fetch_distinct_characters(self.session, run_id)

    def fetch_character_metadata_sequence(self, run_id: str) -> list[tuple[str, int, str, str]]:
        """获取角色元数据序列"""
        return metadata.fetch_character_metadata_sequence(self.session, run_id)

    def fetch_relation_sequence(self, run_id: str) -> list[tuple[str, str, str, str, int]]:
        """获取关系序列"""
        return metadata.fetch_relation_sequence(self.session, run_id)

    def insert_entity_snapshot(
        self,
        novel_id: str,
        entity_id: int,
        chunk_id: int,
        state_json: str,
        run_id: str | None = None,
    ) -> int | None:
        """插入实体快照"""
        return metadata.insert_entity_snapshot(
            self.session, novel_id, entity_id, chunk_id, state_json, run_id
        )

    def fetch_snapshots_by_chunk(
        self,
        novel_id: str,
        start_chunk: int,
        end_chunk: int,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取指定分块范围内的快照"""
        return metadata.fetch_snapshots_by_chunk(
            self.session, novel_id, start_chunk, end_chunk, run_id
        )

    def fetch_recent_snapshots(
        self,
        novel_id: str,
        run_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """获取最近的快照"""
        return metadata.fetch_recent_snapshots(self.session, novel_id, run_id, limit)
