"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 settings.py 拆分分析相关配置类

本模块包含分析相关的配置数据类。

修改时间: 2026-04-20
修改者: Codex
任务: refactor-role-based-model-client-names
修改内容: 将 cloud_annotation_fallback_enabled 重命名为 annotation_fallback_enabled，强调它控制的是标注兜底角色
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
class StageProgressRange:
    """
    阶段进度范围配置

    创建时间: 2026-04-08
    创建者: TraeAI
    任务: 统一前后端进度配置
    说明: 定义每个阶段的进度百分比范围 [start, end]
    """

    start: float = 0.0
    end: float = 100.0


@dataclass
class ProgressSettings:
    """
    分析进度配置

    修改时间: 2026-04-08
    修改者: TraeAI
    任务: 统一前后端进度配置
    修改内容: 将单一进度值改为范围配置，支持更精确的进度计算
    """

    preprocess: StageProgressRange = field(default_factory=lambda: StageProgressRange(0, 10))
    annotate: StageProgressRange = field(default_factory=lambda: StageProgressRange(10, 80))
    aggregate: StageProgressRange = field(default_factory=lambda: StageProgressRange(80, 90))
    topic_model: StageProgressRange = field(default_factory=lambda: StageProgressRange(90, 95))
    diagnose: StageProgressRange = field(default_factory=lambda: StageProgressRange(95, 100))


@dataclass
class MultiPhaseAnnotationSettings:
    """
    多阶段标注配置

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: 移除单次调用模式，仅保留双次调用
    修改内容: 移除 enabled 字段，保留 parallel 字段控制并行/串行执行模式

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: rename-two-phase-to-multi-phase
    修改内容: 重命名为 MultiPhaseAnnotationSettings
    """

    parallel: bool = False


@dataclass
class AnalysisSettings:
    """
    分析配置

    修改时间: 2026-03-14
    修改者: TraeAI
    修改内容: 添加双次调用标注配置
    - multi_phase_annotation: 多阶段标注配置

    修改时间: 2026-03-19
    修改者: TraeAI
    修改内容: 添加有效层级关系类型配置

    修改时间: 2026-03-31
    修改者: TraeAI
    修改内容: 统一关系配置为valid_relation_types(中文)
    """

    incremental_disambig_interval: int = 10
    checkpoint_interval: int = 1
    projection_interval: int = 1
    analysis_log_rotation: str = "10 MB"
    analysis_log_retention: str = "30 days"
    sentence_preview_max_chars: int = 100
    sentence_pool_max_chars: int = 80
    annotation_fallback_enabled: bool = True
    progress: ProgressSettings = field(default_factory=ProgressSettings)
    multi_phase_annotation: MultiPhaseAnnotationSettings = field(default_factory=MultiPhaseAnnotationSettings)
    valid_relation_types: list[str] = field(
        default_factory=lambda: [
            "师徒",
            "敌对",
            "盟友",
            "爱慕",
            "家族",
            "利益",
            "主从",
            "友情",
        ]
    )


@dataclass
class SingleBookTopicSettings:
    """单书籍主题模型配置"""

    num_topics: int = 20
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
    """
    文本截断限制配置

    修改时间: 2026-04-08
    修改者: TraeAI
    任务: 移除未使用的 summary 配置
    修改内容: 移除 summary 字段，该字段仅用于已删除的 build_cloud_payload 函数
    """

    pivot_block: int = 300
    pivot_moment: int = 400
    high_tension: int = 300
    foreshadowing: int = 200


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
    """
    指标计算配置

    修改时间: 2026-04-07
    修改者: GLM-5
    任务: 张力曲线傅里叶平滑 - 配置抽离
    修改内容: 添加 fourier_smooth_keep_ratio 参数
    """

    mtld_threshold: float = 0.72
    emotion_recovery_threshold: float = 0.3
    slope_threshold: float = 0.01
    std_dev_threshold: float = 0.15
    middle_collapse_min_chunks: int = 10
    character_max_iter: int = 100
    fourier_smooth_keep_ratio: float = 0.1


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
    mention_extraction_enabled: bool = False
    level3_rerank_enabled: bool = False
    level3_top_k: int = 5
    level3_max_queries: int = 6
    level3_model_rerank_query_max_chars: int = 320


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


def _parse_stage_progress_range(
    data: dict[str, Any] | None,
    default_start: float,
    default_end: float,
) -> StageProgressRange:
    """
    解析阶段进度范围配置

    创建时间: 2026-04-08
    创建者: TraeAI
    任务: 统一前后端进度配置
    """
    if data is None:
        return StageProgressRange(default_start, default_end)
    return StageProgressRange(
        start=data.get("start", default_start),
        end=data.get("end", default_end),
    )


def _parse_progress_settings(data: dict[str, Any] | None) -> ProgressSettings:
    """
    解析进度配置

    修改时间: 2026-04-08
    修改者: TraeAI
    任务: 统一前后端进度配置
    修改内容: 支持解析范围配置
    """
    if not data:
        return ProgressSettings()
    return ProgressSettings(
        preprocess=_parse_stage_progress_range(data.get("preprocess"), 0, 10),
        annotate=_parse_stage_progress_range(data.get("annotate"), 10, 80),
        aggregate=_parse_stage_progress_range(data.get("aggregate"), 80, 90),
        topic_model=_parse_stage_progress_range(data.get("topic_model"), 90, 95),
        diagnose=_parse_stage_progress_range(data.get("diagnose"), 95, 100),
    )


def _parse_multi_phase_annotation_settings(data: dict[str, Any] | None) -> MultiPhaseAnnotationSettings:
    """
    解析多阶段标注配置

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: 移除单次调用模式，仅保留双次调用
    修改内容: 删除 enabled 字段解析

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: rename-two-phase-to-multi-phase
    修改内容: 重命名为 _parse_multi_phase_annotation_settings
    """
    if not data:
        return MultiPhaseAnnotationSettings()
    return MultiPhaseAnnotationSettings(
        parallel=data.get("parallel", False),
    )


def _parse_analysis_settings(data: dict[str, Any] | None) -> AnalysisSettings:
    """
    解析分析配置

    修改时间: 2026-03-14
    修改者: TraeAI
    修改内容: 添加双次调用标注配置解析

    修改时间: 2026-03-19
    修改者: TraeAI
    修改内容: 添加有效层级关系类型配置解析

    修改时间: 2026-04-20
    修改者: Codex
    任务: refactor-role-based-model-client-names
    修改内容: 将 cloud_annotation_fallback_enabled 重命名为 annotation_fallback_enabled
    """
    if not data:
        return AnalysisSettings()
    return AnalysisSettings(
        incremental_disambig_interval=data.get("incremental_disambig_interval", 10),
        checkpoint_interval=data.get("checkpoint_interval", 1),
        projection_interval=data.get("projection_interval", 1),
        analysis_log_rotation=data.get("analysis_log_rotation", "10 MB"),
        analysis_log_retention=data.get("analysis_log_retention", "30 days"),
        sentence_preview_max_chars=data.get("sentence_preview_max_chars", 100),
        sentence_pool_max_chars=data.get("sentence_pool_max_chars", 80),
        annotation_fallback_enabled=data.get("annotation_fallback_enabled", True),
        progress=_parse_progress_settings(data.get("progress")),
        multi_phase_annotation=_parse_multi_phase_annotation_settings(data.get("multi_phase_annotation")),
        valid_relation_types=data.get(
            "valid_relation_types",
            [
                "师徒",
                "敌对",
                "盟友",
                "爱慕",
                "家族",
                "利益",
                "主从",
                "友情",
            ],
        ),
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
    """
    解析诊断配置

    修改时间: 2026-04-08
    修改者: TraeAI
    任务: 移除未使用的 summary 配置
    修改内容: 移除 summary 参数解析
    """
    if not data:
        return DiagnosisSettings()

    text_limits_data = data.get("text_limits", {})
    text_limits = TextLimitsSettings(
        pivot_block=text_limits_data.get("pivot_block", 300),
        pivot_moment=text_limits_data.get("pivot_moment", 400),
        high_tension=text_limits_data.get("high_tension", 300),
        foreshadowing=text_limits_data.get("foreshadowing", 200),
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
    """
    解析指标配置

    修改时间: 2026-04-07
    修改者: GLM-5
    任务: 张力曲线傅里叶平滑 - 配置抽离
    修改内容: 添加 fourier_smooth_keep_ratio 解析
    """
    if not data:
        return MetricsSettings()
    return MetricsSettings(
        mtld_threshold=data.get("mtld_threshold", 0.72),
        emotion_recovery_threshold=data.get("emotion_recovery_threshold", 0.3),
        slope_threshold=data.get("slope_threshold", 0.01),
        std_dev_threshold=data.get("std_dev_threshold", 0.15),
        middle_collapse_min_chunks=data.get("middle_collapse_min_chunks", 10),
        character_max_iter=data.get("character_max_iter", 100),
        fourier_smooth_keep_ratio=data.get("fourier_smooth_keep_ratio", 0.1),
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
        mention_extraction_enabled=data.get("mention_extraction_enabled", False),
        level3_rerank_enabled=data.get("level3_rerank_enabled", False),
        level3_top_k=data.get("level3_top_k", data.get("top_k", 5)),
        level3_max_queries=data.get("level3_max_queries", 6),
        level3_model_rerank_query_max_chars=data.get("level3_model_rerank_query_max_chars", 320),
    )
