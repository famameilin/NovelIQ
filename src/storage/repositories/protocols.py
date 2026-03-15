"""
创建时间: 2026-03-14
创建者: TraeAI
任务: Repository 基类和 Protocol 接口定义
说明: 定义各 Repository 的 Protocol 接口，用于依赖注入和类型检查
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from src.chunking.chunker import Chunk
from src.models.cloud.schema import CloudAnalysis
from src.models.local.schema import (
    ChunkAnnotation,
    CharacterSnapshot,
    DialogueSnapshot,
    RelationChangeSnapshot,
    ForeshadowingResult,
)


@runtime_checkable
class RunRepositoryProtocol(Protocol):
    """
    分析运行管理接口

    管理分析运行的创建、查询和状态更新。
    """

    def create_run(self, novel_id: str, source_path: str | None, title: str | None) -> str:
        """
        创建新的分析运行记录

        Args:
            novel_id: 小说ID
            source_path: 源文件路径
            title: 小说标题

        Returns:
            运行ID
        """
        ...

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        获取运行记录

        Args:
            run_id: 运行ID

        Returns:
            运行记录字典，不存在则返回 None
        """
        ...

    def update_run_status(self, run_id: str, status: str) -> None:
        """
        更新运行状态

        Args:
            run_id: 运行ID
            status: 新状态
        """
        ...

    def get_latest_run(self, novel_id: str) -> Optional[Dict[str, Any]]:
        """
        获取指定小说的最新运行记录

        Args:
            novel_id: 小说ID

        Returns:
            最新运行记录字典，不存在则返回 None
        """
        ...


@runtime_checkable
class ChunkRepositoryProtocol(Protocol):
    """
    分块数据接口

    管理文本分块的存储和检索。
    """

    def insert_chunks(self, chunks: Sequence[Chunk]) -> None:
        """
        批量插入分块数据

        Args:
            chunks: 分块序列
        """
        ...

    def fetch_chunk_texts(self) -> List[Tuple[int, str]]:
        """
        获取所有分块文本

        Returns:
            (chunk_id, text) 元组列表
        """
        ...

    def fetch_chunk_styles(self) -> List[Tuple[int, float, float, float]]:
        """
        获取分块风格数据

        Returns:
            (chunk_id, dialogue_ratio, sent_len_std, avg_sent_len) 元组列表
        """
        ...

    def insert_chunk_style(self, rows: Sequence[Any]) -> None:
        """
        插入分块风格数据

        Args:
            rows: 风格数据行
        """
        ...

    def insert_chunk_culture(self, rows: Sequence[Tuple[int, float, float, float, float, float, float]]) -> None:
        """
        插入分块文化数据

        Args:
            rows: 文化数据行 (chunk_id, confucian_density, taoist_density, buddhist_density, folk_density, allusion_density, imagery_density)
        """
        ...

    def insert_chunk_topics(self, rows: Sequence[Tuple[int, int, float]]) -> None:
        """
        插入分块主题数据

        Args:
            rows: 主题数据行 (chunk_id, topic_id, topic_weight)
        """
        ...

    def clear_chunk_topics(self) -> None:
        """清空分块主题数据"""
        ...


@runtime_checkable
class AnnotationRepositoryProtocol(Protocol):
    """
    标注数据接口

    管理分块标注、角色、对话、关系等数据。

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: 实现 AnnotationRepository 类
    修改内容: 为所有方法添加 run_id 参数支持
    """

    def insert_chunk_annotation(self, run_id: str, chunk_id: int, annotation: ChunkAnnotation) -> None:
        """
        插入分块标注

        Args:
            run_id: 运行ID
            chunk_id: 分块ID
            annotation: 标注数据
        """
        ...

    def insert_chunk_characters(self, run_id: str, chunk_id: int, characters: Sequence[CharacterSnapshot]) -> None:
        """
        插入分块角色数据

        Args:
            run_id: 运行ID
            chunk_id: 分块ID
            characters: 角色快照序列
        """
        ...

    def insert_chunk_relations(self, run_id: str, chunk_id: int, relations: Sequence[RelationChangeSnapshot]) -> None:
        """
        插入分块关系数据

        Args:
            run_id: 运行ID
            chunk_id: 分块ID
            relations: 关系变更快照序列
        """
        ...

    def insert_chunk_dialogues(
        self, run_id: str, chunk_id: int, dialogues: Sequence[DialogueSnapshot], lengths: Sequence[int] | None = None
    ) -> None:
        """
        插入分块对话数据

        Args:
            run_id: 运行ID
            chunk_id: 分块ID
            dialogues: 对话快照序列
            lengths: 对话长度序列（可选）
        """
        ...

    def insert_foreshadowing(self, run_id: str, chunk_id: int, result: ForeshadowingResult) -> None:
        """
        插入伏笔分析结果

        Args:
            run_id: 运行ID
            chunk_id: 分块ID
            result: 伏笔分析结果
        """
        ...

    def fetch_chunk_annotations(self, run_id: str) -> List[Tuple[int, str, int]]:
        """
        获取指定运行的所有分块标注

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, event_type, cliffhanger) 元组列表
        """
        ...

    def fetch_annotated_chunk_ids(self, run_id: str) -> set[int]:
        """
        获取指定运行已标注的分块ID集合

        Args:
            run_id: 运行ID

        Returns:
            已标注分块ID集合
        """
        ...

    def fetch_all_character_names(self, run_id: str) -> List[Dict[str, str | int]]:
        """
        获取指定运行的所有角色名及出现频次

        Args:
            run_id: 运行ID

        Returns:
            [{"name": "角色名", "count": 频次}, ...] 列表
        """
        ...

    def update_character_names(self, run_id: str, alias_map: Dict[str, str], novel_id: str = "default") -> None:
        """
        更新角色名称（消歧）

        Args:
            run_id: 运行ID
            alias_map: 别名到规范名的映射
            novel_id: 小说ID
        """
        ...


@runtime_checkable
class StatsRepositoryProtocol(Protocol):
    """
    统计数据接口

    管理全局统计、情绪曲线、节奏曲线等数据。
    """

    def insert_chunk_summary(self, chunk_id: int, summary: str) -> None:
        """
        插入分块摘要

        Args:
            chunk_id: 分块ID
            summary: 摘要文本
        """
        ...

    def insert_character_appearances(self, chunk_id: int, appearances: Sequence[Any]) -> None:
        """
        插入角色出场信息

        Args:
            chunk_id: 分块ID
            appearances: 角色出场信息序列
        """
        ...

    def insert_emotion_curve(self, rows: Sequence[Tuple[int, float, float, float, float]]) -> None:
        """
        插入情绪曲线数据

        Args:
            rows: 情绪数据行 (chunk_id, pos_density, neg_density, net_density, smoothed_density)
        """
        ...

    def insert_rhythm_curve(self, rows: Sequence[Tuple[int, float, float]]) -> None:
        """
        插入节奏曲线数据

        Args:
            rows: 节奏数据行 (chunk_id, tension_proxy, tension_composite)
        """
        ...

    def insert_global_stats(self, stats: Sequence[Tuple[str, float]]) -> None:
        """
        插入全局统计数据

        Args:
            stats: 统计数据行 (stat_name, stat_value)
        """
        ...

    def insert_cloud_analysis(self, analysis: CloudAnalysis) -> None:
        """
        插入云端分析结果

        Args:
            analysis: 云端分析数据
        """
        ...

    def insert_global_context(
        self, novel_id: str, core_characters: str, world_setting: str, novel_title: str | None = None
    ) -> None:
        """
        插入全局上下文

        Args:
            novel_id: 小说ID
            core_characters: 核心角色
            world_setting: 世界观设定
            novel_title: 小说标题（可选）
        """
        ...

    def fetch_global_context(self, novel_id: str) -> Optional[Tuple[str, str, str, str]]:
        """
        获取全局上下文

        Args:
            novel_id: 小说ID

        Returns:
            (novel_title, core_characters, world_setting, updated_at) 元组，不存在则返回 None
        """
        ...

    def update_global_context(self, novel_id: str, **kwargs: Any) -> None:
        """
        更新全局上下文

        Args:
            novel_id: 小说ID
            **kwargs: 要更新的字段
        """
        ...

    def insert_token_usage(
        self,
        novel_id: str,
        task_type: str,
        call_type: str,
        model: str,
        prompt_tokens: int,
        total_tokens: int,
        completion_tokens: int | None = None,
        chunk_id: int | None = None,
    ) -> int | None:
        """
        插入 token 使用记录

        Args:
            novel_id: 小说ID
            task_type: 任务类型
            call_type: 调用类型
            model: 模型名称
            prompt_tokens: 提示 token 数
            total_tokens: 总 token 数
            completion_tokens: 完成 token 数（可选）
            chunk_id: 分块ID（可选）

        Returns:
            插入记录的ID
        """
        ...

    def fetch_token_usage_by_novel(self, novel_id: str) -> List[Dict[str, Any]]:
        """
        获取指定小说的 token 使用记录

        Args:
            novel_id: 小说ID

        Returns:
            token 使用记录列表
        """
        ...

    def fetch_token_usage_stats(self, novel_id: str) -> Dict[str, Any]:
        """
        获取 token 使用统计

        Args:
            novel_id: 小说ID

        Returns:
            使用统计数据字典
        """
        ...


@runtime_checkable
class EntityRepositoryProtocol(Protocol):
    """
    实体数据接口

    管理实体、别名、嵌入等数据。
    """

    def insert_entity(
        self,
        novel_id: str,
        canonical: str,
        entity_type: str,
        first_chunk: int | None = None,
        description: str | None = None,
        confidence: float = 1.0,
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

        Returns:
            插入记录的ID
        """
        ...

    def insert_entity_alias(
        self,
        entity_id: int,
        alias: str,
        alias_type: str | None = None,
        source_chunk: int | None = None,
    ) -> int | None:
        """
        插入实体别名

        Args:
            entity_id: 实体ID
            alias: 别名
            alias_type: 别名类型（可选）
            source_chunk: 来源分块ID（可选）

        Returns:
            插入记录的ID
        """
        ...

    def insert_entity_embedding(self, entity_id: int, embedding: List[float]) -> None:
        """
        插入实体嵌入向量

        Args:
            entity_id: 实体ID
            embedding: 嵌入向量
        """
        ...

    def fetch_entity_by_canonical(self, novel_id: str, canonical: str) -> Optional[Dict[str, Any]]:
        """
        根据规范名获取实体

        Args:
            novel_id: 小说ID
            canonical: 规范名

        Returns:
            实体字典，不存在则返回 None
        """
        ...

    def fetch_entity_by_alias(self, novel_id: str, alias: str) -> Optional[Dict[str, Any]]:
        """
        根据别名获取实体

        Args:
            novel_id: 小说ID
            alias: 别名

        Returns:
            实体字典，不存在则返回 None
        """
        ...

    def fetch_all_aliases_for_entity(self, entity_id: int) -> List[Dict[str, Any]]:
        """
        获取实体的所有别名

        Args:
            entity_id: 实体ID

        Returns:
            别名字典列表
        """
        ...

    def update_entity_last_chunk(self, entity_id: int, last_chunk: int) -> None:
        """
        更新实体最后出现的分块

        Args:
            entity_id: 实体ID
            last_chunk: 最后出现的分块ID
        """
        ...

    def increment_alias_confirm(self, entity_id: int, alias: str) -> None:
        """
        增加别名确认计数

        Args:
            entity_id: 实体ID
            alias: 别名
        """
        ...

    def insert_entity_registry(
        self,
        chunk_id: int,
        name: str,
        role: str,
        last_action: str,
        last_emotion: str,
        emotion_score: int,
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
        """
        ...

    def fetch_active_entities(self, current_chunk_id: int, lookback: int = 10) -> List[Tuple[int, str, str, str, str, int]]:
        """
        获取活跃实体

        Args:
            current_chunk_id: 当前分块ID
            lookback: 回溯范围

        Returns:
            活跃实体元组列表
        """
        ...


@runtime_checkable
class DiagnosisRepositoryProtocol(Protocol):
    """
    诊断数据接口

    管理诊断分析相关的数据查询和存储。

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: 实现 DiagnosisRepository 类
    修改内容: 为所有方法添加 run_id 参数支持
    """

    def fetch_pivot_blocks(self, run_id: str, limit: int | None = None) -> List[Tuple[int, str, str]]:
        """
        获取转折点分块

        Args:
            run_id: 运行ID
            limit: 返回数量限制

        Returns:
            (chunk_id, text, event_type) 元组列表
        """
        ...

    def fetch_high_tension_chunks(self, run_id: str, limit: int | None = None) -> List[Tuple[int, str, float]]:
        """
        获取高张力分块

        Args:
            run_id: 运行ID
            limit: 返回数量限制

        Returns:
            (chunk_id, text, tension) 元组列表
        """
        ...

    def fetch_relation_changes(self, run_id: str, limit: int | None = None) -> List[Tuple[int, str, str, str, str]]:
        """
        获取关系变更记录

        Args:
            run_id: 运行ID
            limit: 返回数量限制

        Returns:
            (chunk_id, from_char, to_char, type, change) 元组列表
        """
        ...

    def fetch_foreshadowing_chunks(self, run_id: str, limit: int | None = None) -> List[Tuple[int, str, str, str]]:
        """
        获取伏笔分块

        Args:
            run_id: 运行ID
            limit: 返回数量限制

        Returns:
            (chunk_id, text, foreshadowing_type, foreshadowing_desc) 元组列表
        """
        ...

    def fetch_first_last_chunk_summary(self, run_id: str, max_chars: int | None = None) -> Tuple[str, str]:
        """
        获取首尾分块摘要

        Args:
            run_id: 运行ID
            max_chars: 最大字符数

        Returns:
            (首分块摘要, 尾分块摘要) 元组
        """
        ...

    def fetch_pivot_moments(self, run_id: str, limit: int | None = None) -> List[Tuple[int, str]]:
        """
        获取高潮时刻

        Args:
            run_id: 运行ID
            limit: 返回数量限制

        Returns:
            (chunk_id, text) 元组列表
        """
        ...

    def insert_entity_snapshot(
        self, run_id: str, novel_id: str, entity_id: int, chunk_id: int, state_json: str
    ) -> int | None:
        """
        插入实体快照

        Args:
            run_id: 运行ID
            novel_id: 小说ID
            entity_id: 实体ID
            chunk_id: 分块ID
            state_json: 状态JSON

        Returns:
            插入记录的ID
        """
        ...

    def fetch_snapshots_by_chunk(
        self, run_id: str, novel_id: str, start_chunk: int, end_chunk: int
    ) -> List[Dict[str, Any]]:
        """
        按分块范围获取快照

        Args:
            run_id: 运行ID
            novel_id: 小说ID
            start_chunk: 起始分块ID
            end_chunk: 结束分块ID

        Returns:
            快照字典列表
        """
        ...

    def fetch_recent_snapshots(self, run_id: str, novel_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取最近的快照

        Args:
            run_id: 运行ID
            novel_id: 小说ID
            limit: 返回数量限制

        Returns:
            快照字典列表
        """
        ...
