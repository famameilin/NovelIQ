"""
标注数据 Repository 主类

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分annotation_repository
说明: 主Repository类，通过组合方式使用各模块函数
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.models.local.schema import (
    CharacterSnapshot,
    DialogueSnapshot,
    ForeshadowingResult,
    RelationChangeSnapshot,
)
from src.models.local.schema import (
    ChunkAnnotation as ChunkAnnotationSchema,
)
from src.storage.repositories.base import BaseRepository

# 导入各模块函数
from . import characters, inserts, queries


class AnnotationRepository(BaseRepository[dict[str, Any]]):
    """
    标注数据 Repository

    管理分块标注、角色、对话、关系等数据。
    所有操作都基于 run_id 进行数据隔离。

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - 拆分annotation_repository
    修改内容: 使用函数组合方式重组代码结构，拆分为3个模块：
        - inserts: 标注数据插入操作
        - queries: 标注数据查询操作
        - characters: 角色消歧、名称更新、别名映射
    """

    # ==================== inserts 模块方法 ====================

    def insert_chunk_annotation(self, run_id: str, chunk_id: int, annotation: ChunkAnnotationSchema) -> None:
        """插入分块标注"""
        return inserts.insert_chunk_annotation(self.session, run_id, chunk_id, annotation)

    def insert_chunk_characters(self, run_id: str, chunk_id: int, characters: Sequence[CharacterSnapshot]) -> None:
        """插入分块角色数据"""
        return inserts.insert_chunk_characters(self.session, run_id, chunk_id, characters)

    def insert_chunk_relations(self, run_id: str, chunk_id: int, relations: Sequence[RelationChangeSnapshot]) -> None:
        """插入分块关系数据"""
        return inserts.insert_chunk_relations(self.session, run_id, chunk_id, relations)

    def insert_chunk_dialogues(
        self,
        run_id: str,
        chunk_id: int,
        dialogues: Sequence[DialogueSnapshot],
        lengths: Sequence[int] | None = None,
    ) -> None:
        """插入分块对话数据"""
        return inserts.insert_chunk_dialogues(self.session, run_id, chunk_id, dialogues, lengths)

    def insert_foreshadowing(self, run_id: str, chunk_id: int, result: ForeshadowingResult) -> None:
        """插入伏笔分析结果"""
        return inserts.insert_foreshadowing(self.session, run_id, chunk_id, result)

    # ==================== queries 模块方法 ====================

    def fetch_chunk_annotations(self, run_id: str) -> list[Any]:
        """获取指定运行的所有分块标注"""
        return queries.fetch_chunk_annotations(self.session, run_id)

    def fetch_chunk_annotations_full(self, run_id: str) -> list[Any]:
        """获取完整的分块标注数据（用于结果导出）"""
        return queries.fetch_chunk_annotations_full(self.session, run_id)

    def fetch_chunk_characters_full(self, run_id: str) -> list[Any]:
        """获取完整的分块角色数据"""
        return queries.fetch_chunk_characters_full(self.session, run_id)

    def fetch_chunk_relations_full(self, run_id: str) -> list[Any]:
        """获取完整的分块关系数据"""
        return queries.fetch_chunk_relations_full(self.session, run_id)

    def fetch_chunk_dialogues_full(self, run_id: str) -> list[Any]:
        """获取完整的分块对话数据"""
        return queries.fetch_chunk_dialogues_full(self.session, run_id)

    def fetch_annotated_chunk_ids(self, run_id: str) -> set[int]:
        """获取指定运行已标注的分块ID集合"""
        return queries.fetch_annotated_chunk_ids(self.session, run_id)

    def fetch_full_annotations(self, run_id: str) -> list[Any]:
        """获取完整的分块标注数据"""
        return queries.fetch_full_annotations(self.session, run_id)

    def fetch_characters_with_scores(self, run_id: str) -> list[Any]:
        """获取角色数据（含情绪分数）"""
        return queries.fetch_characters_with_scores(self.session, run_id)

    def fetch_character_emotion_sequence(self, run_id: str) -> list[Any]:
        """获取角色情绪序列（按 chunk_id 排序）"""
        return queries.fetch_character_emotion_sequence(self.session, run_id)

    def fetch_relations(self, run_id: str) -> list[Any]:
        """获取角色关系（仅 from/to）"""
        return queries.fetch_relations(self.session, run_id)

    def fetch_full_relations(self, run_id: str) -> list[Any]:
        """获取完整角色关系"""
        return queries.fetch_full_relations(self.session, run_id)

    def fetch_chunk_relations_window(
        self,
        run_id: str,
        from_chunk: int | None = None,
        to_chunk: int | None = None,
        projection_status: str | None = None,
    ) -> list[Any]:
        return queries.fetch_chunk_relations_window(
            self.session,
            run_id,
            from_chunk=from_chunk,
            to_chunk=to_chunk,
            projection_status=projection_status,
        )

    def fetch_pending_chunk_relations(
        self,
        run_id: str,
        to_chunk: int | None = None,
        limit: int = 200,
    ) -> list[Any]:
        return queries.fetch_pending_chunk_relations(
            self.session,
            run_id,
            to_chunk=to_chunk,
            limit=limit,
        )

    def update_relation_projection_status(
        self,
        relation_id: int,
        projection_status: str,
        projected_at=None,
        projection_error: str | None = None,
    ) -> None:
        return inserts.update_relation_projection_status(
            self.session,
            relation_id,
            projection_status,
            projected_at=projected_at,
            projection_error=projection_error,
        )

    def has_annotations(self, run_id: str) -> bool:
        """检查指定运行是否有标注数据"""
        return queries.has_annotations(self.session, run_id)

    def is_annotate_complete(self, run_id: str) -> bool:
        """检查标注阶段是否完成"""
        return queries.is_annotate_complete(self.session, run_id)

    def get_annotation_by_chunk(self, run_id: str, chunk_id: int) -> dict[str, Any] | None:
        """
        获取指定 chunk 的标注结果

        创建时间: 2026-03-19
        创建者: TraeAI
        任务: 修复缺失的 get_annotation_by_chunk 方法
        """
        return queries.get_annotation_by_chunk(self.session, run_id, chunk_id)

    # ==================== characters 模块方法 ====================

    def fetch_alias_map(self, run_id: str) -> dict[str, str]:
        """获取别名映射表"""
        return characters.fetch_alias_map(self.session, run_id)

    def fetch_all_character_names(self, run_id: str, max_chunk_id: int | None = None) -> list[dict[str, str | int]]:
        """获取指定运行的所有角色名及出现频次"""
        return characters.fetch_all_character_names(self.session, run_id, max_chunk_id=max_chunk_id)

    def ensure_canonical_entities(
        self,
        run_id: str,
        known_canonical_names: frozenset[str],
        novel_id: str,
        entity_types: dict[str, str] | None = None,
    ) -> dict[str, int]:
        return characters.ensure_canonical_entities(
            self.session,
            run_id,
            known_canonical_names,
            novel_id,
            entity_types,
        )

    def cleanup_self_loop_relations(self, run_id: str) -> None:
        return characters.cleanup_self_loop_relations(self.session, run_id)
