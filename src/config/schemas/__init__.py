"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 配置数据类模块入口

本模块包含所有配置数据类的导出。

修改时间: 2026-03-17
修改者: TraeAI
任务: code-quality-refactor - 消除魔法数字
修改内容: 添加 AnnotationConfig 配置类
"""

from .analysis import (
    AnalysisSettings,
    ChunkingSettings,
    CommonTopicSettings,
    DatabaseSettings,
    DiagnosisSettings,
    MetricsSettings,
    MultiBookTopicSettings,
    ProgressSettings,
    RAGSettings,
    SingleBookTopicSettings,
    TextLimitsSettings,
    TopicModelSettings,
    _parse_analysis_settings,
    _parse_chunking_settings,
    _parse_database_settings,
    _parse_diagnosis_settings,
    _parse_metrics_settings,
    _parse_progress_settings,
    _parse_rag_settings,
    _parse_topic_model_settings,
)
from .annotation import (
    ANNOTATION_CONFIG,
    AnnotationConfig,
)
from .api import (
    APISettings,
    PathSettings,
    PromptSettings,
    _parse_api_settings,
    _parse_path_settings,
    _parse_prompt_settings,
)
from .logging import (
    LoggingModuleSettings,
    LoggingSettings,
    _parse_logging_settings,
)
from .model import (
    EmbeddingModelSettings,
    ModelsSettings,
    StreamingSettings,
    TaskModelSettings,
    ThinkingConfig,
    ThinkingSettings,
    _parse_embedding_model_settings,
    _parse_models_settings,
    _parse_streaming_settings,
    _parse_task_model_settings,
    _parse_thinking_settings,
)

__all__ = [
    "AnalysisSettings",
    "AnnotationConfig",
    "ANNOTATION_CONFIG",
    "APISettings",
    "ChunkingSettings",
    "CommonTopicSettings",
    "DatabaseSettings",
    "DiagnosisSettings",
    "EmbeddingModelSettings",
    "LoggingModuleSettings",
    "LoggingSettings",
    "MetricsSettings",
    "ModelsSettings",
    "MultiBookTopicSettings",
    "PathSettings",
    "ProgressSettings",
    "PromptSettings",
    "RAGSettings",
    "SingleBookTopicSettings",
    "StreamingSettings",
    "TaskModelSettings",
    "TextLimitsSettings",
    "ThinkingConfig",
    "ThinkingSettings",
    "TopicModelSettings",
    "_parse_analysis_settings",
    "_parse_api_settings",
    "_parse_chunking_settings",
    "_parse_database_settings",
    "_parse_diagnosis_settings",
    "_parse_embedding_model_settings",
    "_parse_logging_settings",
    "_parse_metrics_settings",
    "_parse_models_settings",
    "_parse_path_settings",
    "_parse_progress_settings",
    "_parse_prompt_settings",
    "_parse_rag_settings",
    "_parse_streaming_settings",
    "_parse_task_model_settings",
    "_parse_thinking_settings",
    "_parse_topic_model_settings",
]
