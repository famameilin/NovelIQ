"""
标注数据 Repository 主类

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分annotation_repository
说明: 主Repository类，通过组合方式使用各模块函数
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Set

from src.models.local.schema import (
    ChunkAnnotation as ChunkAnnotationSchema,
    CharacterSnapshot,
    DialogueSnapshot,
    ForeshadowingResult,
    RelationChangeSnapshot,
)
from src.storage.repositories.base import BaseRepository

# 导入各模块函数
from . import characters, inserts, queries


class AnnotationRepository(BaseRepository[Dict[str, Any]]):
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
        speakers: Sequence[str] | None = None,
    ) -> None:
        """插入分块对话数据"""
        return inserts.insert_chunk_dialogues(self.session, run_id, chunk_id, dialogues, lengths, speakers)

    def insert_foreshadowing(self, run_id: str, chunk_id: int, result: ForeshadowingResult) -> None:
        """插入伏笔分析结果"""
        return inserts.insert_foreshadowing(self.session, run_id, chunk_id, result)

    # ==================== queries 模块方法 ====================

    def fetch_chunk_annotations(self, run_id: str) -> List[Any]:
        """获取指定运行的所有分块标注"""
        return queries.fetch_chunk_annotations(self.session, run_id)

    def fetch_chunk_annotations_full(self, run_id: str) -> List[Any]:
        """获取完整的分块标注数据（用于结果导出）"""
        return queries.fetch_chunk_annotations_full(self.session, run_id)

    def fetch_chunk_characters_full(self, run_id: str) -> List[Any]:
        """获取完整的分块角色数据"""
        return queries.fetch_chunk_characters_full(self.session, run_id)

    def fetch_chunk_relations_full(self, run_id: str) -> List[Any]:
        """获取完整的分块关系数据"""
        return queries.fetch_chunk_relations_full(self.session, run_id)

    def fetch_chunk_dialogues_full(self, run_id: str) -> List[Any]:
        """获取完整的分块对话数据"""
        return queries.fetch_chunk_dialogues_full(self.session, run_id)

    def fetch_annotated_chunk_ids(self, run_id: str) -> Set[int]:
        """获取指定运行已标注的分块ID集合"""
        return queries.fetch_annotated_chunk_ids(self.session, run_id)

    def fetch_full_annotations(self, run_id: str) -> List[Any]:
        """获取完整的分块标注数据"""
        return queries.fetch_full_annotations(self.session, run_id)

    def fetch_characters_with_scores(self, run_id: str) -> List[Any]:
        """获取角色数据（含情绪分数）"""
        return queries.fetch_characters_with_scores(self.session, run_id)

    def fetch_character_emotion_sequence(self, run_id: str) -> List[Any]:
        """获取角色情绪序列（按 chunk_id 排序）"""
        return queries.fetch_character_emotion_sequence(self.session, run_id)

    def fetch_relations(self, run_id: str) -> List[Any]:
        """获取角色关系（仅 from/to）"""
        return queries.fetch_relations(self.session, run_id)

    def fetch_full_relations(self, run_id: str) -> List[Any]:
        """获取完整角色关系"""
        return queries.fetch_full_relations(self.session, run_id)

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

    def fetch_alias_map(self, run_id: str) -> Dict[str, str]:
        """获取别名映射表"""
        return characters.fetch_alias_map(self.session, run_id)

    def fetch_all_character_names(self, run_id: str) -> List[Dict[str, str | int]]:
        """获取指定运行的所有角色名及出现频次"""
        return characters.fetch_all_character_names(self.session, run_id)

    def update_character_names(self, run_id: str, alias_map: Dict[str, str], novel_id: str = "default") -> None:
        """更新角色名称（消歧）"""
        return characters.update_character_names(self.session, run_id, alias_map, novel_id)

    def apply_alias_corrections(self, run_id: str, alias_map: Dict[str, str]) -> None:
        """用最终消歧结果修正所有标注表里的错误名字"""
        return characters.apply_alias_corrections(self.session, run_id, alias_map)
