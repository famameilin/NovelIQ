"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 settings.py 拆分分析相关配置类

本模块包含分析相关的配置数据类。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List


@dataclass
class ChunkingSettings:
    """分块配置"""

    max_chars: int = 2000
    overlap: int = 200
    split_by_chapter: bool = True
    use_semantic_chunking: bool = False
    semantic_threshold: float = 0.7
    semantic_max_chars: int = 3000
    semantic_window_size: int = 3
    semantic_percentile: int = 10
    semantic_min_chars: int = 50
    semantic_use_dynamic_threshold: bool = True


@dataclass
class DatabaseSettings:
    """
    PostgreSQL 数据库连接池配置

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: postgresql-migration-cleanup
    修改内容: 移除 SQLite 特有配置，替换为 PostgreSQL 连接池配置
    """

    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 3600
    echo: bool = False


@dataclass
class ProgressSettings:
    """分析进度配置"""

    preprocess: int = 10
    annotate: int = 25
    aggregate: int = 50
    topic_model: int = 70
    diagnose: int = 85


@dataclass
class TwoPhaseAnnotationSettings:
    """
    双次调用标注配置

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分
    """

    enabled: bool = False
    parallel: bool = False


@dataclass
class AnalysisSettings:
    """
    分析配置

    修改时间: 2026-03-14
    修改者: TraeAI
    修改内容: 添加双次调用标注配置
    - two_phase_annotation: 双次调用标注配置

    修改时间: 2026-03-12
    修改者: TraeAI
    修改内容: 添加云端标注fallback开关配置
    - cloud_annotation_fallback_enabled: 是否启用云端chunk兜底，默认true

    修改时间: 2026-03-19
    修改者: TraeAI
    修改内容: 添加有效层级关系类型配置
    - valid_hierarchical_relation_types: 消歧阶段允许的层级关系类型列表
    """

    incremental_disambig_interval: int = 10
    analysis_log_rotation: str = "10 MB"
    analysis_log_retention: str = "30 days"
    sentence_preview_max_chars: int = 100
    sentence_pool_max_chars: int = 80
    cloud_annotation_fallback_enabled: bool = True
    progress: ProgressSettings = field(default_factory=ProgressSettings)
    two_phase_annotation: TwoPhaseAnnotationSettings = field(default_factory=TwoPhaseAnnotationSettings)
    valid_hierarchical_relation_types: List[str] = field(default_factory=lambda: [
        "belongs_to", "member_of", "leader_of", "affiliated_with"
    ])


@dataclass
class SingleBookTopicSettings:
    """单书籍主题模型配置"""

    num_topics: int = 25
    passes: int = 10
    iterations: int = 500


@dataclass
class MultiBookTopicSettings:
    """多书籍主题模型配置"""

    num_topics: int = 120
    passes: int = 15
    iterations: int = 1000


@dataclass
class CommonTopicSettings:
    """通用主题模型配置"""

    alpha: str = "auto"
    eta: str = "auto"
    random_state: int = 42
    chunksize: int = 2000
    minimum_probability: float = 0.01
    no_below: int = 5
    no_above: float = 0.5


@dataclass
class TopicModelSettings:
    """主题模型配置"""

    single_book: SingleBookTopicSettings = field(default_factory=SingleBookTopicSettings)
    multi_book: MultiBookTopicSettings = field(default_factory=MultiBookTopicSettings)
    common: CommonTopicSettings = field(default_factory=CommonTopicSettings)


@dataclass
class TextLimitsSettings:
    """文本截断限制配置"""

    pivot_block: int = 300
    pivot_moment: int = 400
    high_tension: int = 300
    foreshadowing: int = 200
    summary: int = 4000


@dataclass
class DiagnosisSettings:
    """诊断分析配置"""

    pivot_blocks_limit: int = 20
    pivot_moments_limit: int = 10
    high_tension_limit: int = 10
    relation_changes_limit: int = 50
    foreshadowing_limit: int = 30
    first_last_max_chars: int = 500
    topic_words_top_n: int = 10
    text_limits: TextLimitsSettings = field(default_factory=TextLimitsSettings)


@dataclass
class MetricsSettings:
    """指标计算配置"""

    mtld_threshold: float = 0.72
    emotion_recovery_threshold: float = 0.3
    slope_threshold: float = 0.01
    std_dev_threshold: float = 0.15
    middle_collapse_min_chunks: int = 10
    character_max_iter: int = 100


@dataclass
class RAGSettings:
    """RAG 检索配置"""

    enabled: bool = True
    embedding_enabled: bool = True
    similarity_threshold: float = 0.7
    lookback_chunks: int = 10
    top_k: int = 3
    level1_enabled: bool = True
    level2_enabled: bool = True
    level3_enabled: bool = True


def _parse_chunking_settings(data: dict[str, Any] | None) -> ChunkingSettings:
    """解析分块配置"""
    if not data:
        return ChunkingSettings()
    return ChunkingSettings(
        max_chars=data.get("max_chars", 2000),
        overlap=data.get("overlap", 200),
        split_by_chapter=data.get("split_by_chapter", True),
        use_semantic_chunking=data.get("use_semantic_chunking", False),
        semantic_threshold=data.get("semantic_threshold", 0.7),
        semantic_max_chars=data.get("semantic_max_chars", 3000),
        semantic_window_size=data.get("semantic_window_size", 3),
        semantic_percentile=data.get("semantic_percentile", 10),
        semantic_min_chars=data.get("semantic_min_chars", 50),
        semantic_use_dynamic_threshold=data.get("semantic_use_dynamic_threshold", True),
    )


def _parse_database_settings(data: dict[str, Any] | None) -> DatabaseSettings:
    """
    解析数据库配置

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: postgresql-migration-cleanup
    修改内容: 替换为 PostgreSQL 连接池配置解析
    """
    if not data:
        return DatabaseSettings()
    return DatabaseSettings(
        pool_size=data.get("pool_size", 5),
        max_overflow=data.get("max_overflow", 10),
        pool_timeout=data.get("pool_timeout", 30),
        pool_recycle=data.get("pool_recycle", 3600),
        echo=data.get("echo", False),
    )


def _parse_progress_settings(data: dict[str, Any] | None) -> ProgressSettings:
    """解析进度配置"""
    if not data:
        return ProgressSettings()
    return ProgressSettings(
        preprocess=data.get("preprocess", 10),
        annotate=data.get("annotate", 25),
        aggregate=data.get("aggregate", 50),
        topic_model=data.get("topic_model", 70),
        diagnose=data.get("diagnose", 85),
    )


def _parse_two_phase_annotation_settings(data: dict[str, Any] | None) -> TwoPhaseAnnotationSettings:
    """
    解析双次调用标注配置

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分
    """
    if not data:
        return TwoPhaseAnnotationSettings()
    return TwoPhaseAnnotationSettings(
        enabled=data.get("enabled", False),
        parallel=data.get("parallel", False),
    )


def _parse_analysis_settings(data: dict[str, Any] | None) -> AnalysisSettings:
    """
    解析分析配置

    修改时间: 2026-03-14
    修改者: TraeAI
    修改内容: 添加双次调用标注配置解析

    修改时间: 2026-03-12
    修改者: TraeAI
    修改内容: 添加云端标注fallback开关配置解析

    修改时间: 2026-03-19
    修改者: TraeAI
    修改内容: 添加有效层级关系类型配置解析
    """
    if not data:
        return AnalysisSettings()
    return AnalysisSettings(
        incremental_disambig_interval=data.get("incremental_disambig_interval", 10),
        analysis_log_rotation=data.get("analysis_log_rotation", "10 MB"),
        analysis_log_retention=data.get("analysis_log_retention", "30 days"),
        sentence_preview_max_chars=data.get("sentence_preview_max_chars", 100),
        sentence_pool_max_chars=data.get("sentence_pool_max_chars", 80),
        cloud_annotation_fallback_enabled=data.get("cloud_annotation_fallback_enabled", True),
        progress=_parse_progress_settings(data.get("progress")),
        two_phase_annotation=_parse_two_phase_annotation_settings(data.get("two_phase_annotation")),
        valid_hierarchical_relation_types=data.get("valid_hierarchical_relation_types", [
            "belongs_to", "member_of", "leader_of", "affiliated_with"
        ]),
    )


def _parse_topic_model_settings(data: dict[str, Any] | None) -> TopicModelSettings:
    """解析主题模型配置"""
    if not data:
        return TopicModelSettings()

    single_book_data = data.get("single_book", {})
    single_book = SingleBookTopicSettings(
        num_topics=single_book_data.get("num_topics", 25),
        passes=single_book_data.get("passes", 10),
        iterations=single_book_data.get("iterations", 500),
    )

    multi_book_data = data.get("multi_book", {})
    multi_book = MultiBookTopicSettings(
        num_topics=multi_book_data.get("num_topics", 120),
        passes=multi_book_data.get("passes", 15),
        iterations=multi_book_data.get("iterations", 1000),
    )

    common_data = data.get("common", {})
    common = CommonTopicSettings(
        alpha=common_data.get("alpha", "auto"),
        eta=common_data.get("eta", "auto"),
        random_state=common_data.get("random_state", 42),
        chunksize=common_data.get("chunksize", 2000),
        minimum_probability=common_data.get("minimum_probability", 0.01),
        no_below=common_data.get("no_below", 5),
        no_above=common_data.get("no_above", 0.5),
    )

    return TopicModelSettings(
        single_book=single_book,
        multi_book=multi_book,
        common=common,
    )


def _parse_diagnosis_settings(data: dict[str, Any] | None) -> DiagnosisSettings:
    """解析诊断配置"""
    if not data:
        return DiagnosisSettings()

    text_limits_data = data.get("text_limits", {})
    text_limits = TextLimitsSettings(
        pivot_block=text_limits_data.get("pivot_block", 300),
        pivot_moment=text_limits_data.get("pivot_moment", 400),
        high_tension=text_limits_data.get("high_tension", 300),
        foreshadowing=text_limits_data.get("foreshadowing", 200),
        summary=text_limits_data.get("summary", 4000),
    )

    return DiagnosisSettings(
        pivot_blocks_limit=data.get("pivot_blocks_limit", 20),
        pivot_moments_limit=data.get("pivot_moments_limit", 10),
        high_tension_limit=data.get("high_tension_limit", 10),
        relation_changes_limit=data.get("relation_changes_limit", 50),
        foreshadowing_limit=data.get("foreshadowing_limit", 30),
        first_last_max_chars=data.get("first_last_max_chars", 500),
        topic_words_top_n=data.get("topic_words_top_n", 10),
        text_limits=text_limits,
    )


def _parse_metrics_settings(data: dict[str, Any] | None) -> MetricsSettings:
    """解析指标配置"""
    if not data:
        return MetricsSettings()
    return MetricsSettings(
        mtld_threshold=data.get("mtld_threshold", 0.72),
        emotion_recovery_threshold=data.get("emotion_recovery_threshold", 0.3),
        slope_threshold=data.get("slope_threshold", 0.01),
        std_dev_threshold=data.get("std_dev_threshold", 0.15),
        middle_collapse_min_chunks=data.get("middle_collapse_min_chunks", 10),
        character_max_iter=data.get("character_max_iter", 100),
    )


def _parse_rag_settings(data: dict[str, Any] | None) -> RAGSettings:
    """解析RAG配置"""
    if not data:
        return RAGSettings()
    return RAGSettings(
        enabled=data.get("enabled", True),
        embedding_enabled=data.get("embedding_enabled", True),
        similarity_threshold=data.get("similarity_threshold", 0.7),
        lookback_chunks=data.get("lookback_chunks", 10),
        top_k=data.get("top_k", 3),
        level1_enabled=data.get("level1_enabled", True),
        level2_enabled=data.get("level2_enabled", True),
        level3_enabled=data.get("level3_enabled", True),
    )
