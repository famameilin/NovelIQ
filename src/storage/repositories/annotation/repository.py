"""
标注数据 Repository 主类

主Repository类，通过组合方式使用各模块函数
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
from . import characters, foreshadowing_threads, inserts, queries


class AnnotationRepository(BaseRepository[dict[str, Any]]):
    """
    标注数据 Repository

    管理分块标注、角色、对话、关系等数据
    所有操作都基于 run_id 进行数据隔离

    使用函数组合方式重组代码结构，拆分为3个模块：
        - inserts: 标注数据插入操作
        - queries: 标注数据查询操作
        - characters: 角色消歧、名称更新、别名映射
    """

    # ==================== inserts 模块方法 ====================

    def insert_chunk_annotation(
        self,
        run_id: str,
        chunk_id: int,
        annotation: ChunkAnnotationSchema,
        *,
        commit: bool = True,
    ) -> None:
        """插入分块标注"""
        return inserts.insert_chunk_annotation(self.session, run_id, chunk_id, annotation, commit=commit)

    def insert_chunk_characters(
        self,
        run_id: str,
        chunk_id: int,
        characters: Sequence[CharacterSnapshot],
        *,
        commit: bool = True,
    ) -> None:
        """插入分块角色数据"""
        return inserts.insert_chunk_characters(self.session, run_id, chunk_id, characters, commit=commit)

    def insert_chunk_relations(
        self,
        run_id: str,
        chunk_id: int,
        relations: Sequence[RelationChangeSnapshot],
        *,
        commit: bool = True,
    ) -> None:
        """插入分块关系数据"""
        return inserts.insert_chunk_relations(self.session, run_id, chunk_id, relations, commit=commit)

    def replace_chunk_relations_for_source_model(
        self,
        run_id: str,
        chunk_id: int,
        relations: Sequence[RelationChangeSnapshot | dict[str, Any]],
        *,
        source_model: str,
        commit: bool = True,
    ) -> None:
        """替换指定 source_model 生成的分块关系数据"""
        return inserts.replace_chunk_relations_for_source_model(
            self.session,
            run_id,
            chunk_id,
            relations,
            source_model=source_model,
            commit=commit,
        )

    def insert_chunk_dialogues(
        self,
        run_id: str,
        chunk_id: int,
        dialogues: Sequence[DialogueSnapshot],
        lengths: Sequence[int] | None = None,
        *,
        commit: bool = True,
    ) -> None:
        """插入分块对话数据"""
        return inserts.insert_chunk_dialogues(self.session, run_id, chunk_id, dialogues, lengths, commit=commit)

    def insert_foreshadowing(
        self,
        run_id: str,
        chunk_id: int,
        result: ForeshadowingResult,
        *,
        commit: bool = True,
    ) -> None:
        """插入伏笔分析结果"""
        return inserts.insert_foreshadowing(self.session, run_id, chunk_id, result, commit=commit)

    def fetch_active_foreshadowing_threads_for_prompt(
        self,
        run_id: str,
        *,
        max_chunk_id: int,
        limit: int | None = None,
    ) -> list[foreshadowing_threads.ActiveSetupPoolEntry]:
        """
        获取当前 chunk 可见的活跃 setup 池摘要

        active setup pool limit 已改为运行时读取 settings；
        wrapper 不能再用默认参数把模块导入时的旧值固化回 30
        """
        return foreshadowing_threads.fetch_active_foreshadowing_threads_for_prompt(
            self.session,
            run_id,
            max_chunk_id=max_chunk_id,
            limit=limit,
        )

    def sync_foreshadowing_thread(
        self,
        run_id: str,
        *,
        chunk_id: int,
        result: ForeshadowingResult,
    ) -> foreshadowing_threads.ForeshadowingThreadProjection:
        """同步一条 positive 伏笔结果到 thread ledger"""
        return foreshadowing_threads.sync_foreshadowing_thread(
            self.session,
            run_id=run_id,
            chunk_id=chunk_id,
            result=result,
        )

    def calculate_foreshadow_expectation(self, run_id: str) -> float | None:
        """基于 setup ledger 计算伏笔回收预期"""
        return foreshadowing_threads.calculate_foreshadow_expectation(self.session, run_id)

    def fetch_foreshadowing_threads(self, run_id: str) -> list[foreshadowing_threads.ForeshadowingThreadView]:
        """获取完整的 setup thread 汇总视图"""
        return foreshadowing_threads.fetch_foreshadowing_threads(self.session, run_id)

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

        """
        return queries.get_annotation_by_chunk(self.session, run_id, chunk_id)

    # ==================== characters 模块方法 ====================

    def fetch_alias_map(self, run_id: str) -> dict[str, str]:
        """获取别名映射表"""
        return characters.fetch_alias_map(self.session, run_id)

    def fetch_all_character_names(self, run_id: str, max_chunk_id: int | None = None) -> list[dict[str, str | int]]:
        """获取指定运行的所有角色名及出现频次"""
        return characters.fetch_all_character_names(self.session, run_id, max_chunk_id=max_chunk_id)

    def fetch_reference_aware_character_names(
        self,
        run_id: str,
        max_chunk_id: int | None = None,
    ) -> list[dict[str, str | int]]:
        """
        创建时间: 2026-04-29
        任务: 角色引用分层重构
        新建原因: 消歧候选需要 reference-aware 入口，不能复用读侧的 global-only 出口。
        """
        return characters.fetch_reference_aware_character_names(self.session, run_id, max_chunk_id=max_chunk_id)

    def apply_reference_resolutions_to_history(
        self,
        run_id: str,
        reference_resolutions: dict[str, str],
        *,
        apply: bool = True,
        from_chunk: int | None = None,
        to_chunk: int | None = None,
        table_scopes: tuple[str, ...] | list[str] | set[str] | None = None,
    ) -> dict[str, int]:
        """
        创建时间: 2026-04-29
        任务: 角色引用分层重构
        修改时间: 2026-05-02
        修改原因: graph projection 需要在投影前只回刷当前窗口的 relations，
                  因此仓储层也要透传 chunk window 和 table_scopes。
        """
        return characters.apply_reference_resolutions_to_history(
            self.session,
            run_id,
            reference_resolutions,
            apply=apply,
            from_chunk=from_chunk,
            to_chunk=to_chunk,
            table_scopes=table_scopes,
        )

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
