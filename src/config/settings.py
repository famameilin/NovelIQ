"""
创建时间: 2025-03-11
创建者: TraeAI
任务: 用户可配置项 - 从 settings.json 加载配置

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 项目文件结构整理与拆解 - 重构为使用配置数据类模块
- 将配置数据类拆分到 schemas 子模块
- 保持原有接口不变，确保向后兼容
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schemas import (
    AnalysisSettings,
    APISettings,
    ChunkingSettings,
    DatabaseSettings,
    LoggingSettings,
    MetricsSettings,
    ModelsSettings,
    PathSettings,
    PromptSettings,
    RAGSettings,
    TopicModelSettings,
    DiagnosisSettings,
    ThinkingSettings,
    _parse_analysis_settings,
    _parse_api_settings,
    _parse_chunking_settings,
    _parse_database_settings,
    _parse_diagnosis_settings,
    _parse_logging_settings,
    _parse_metrics_settings,
    _parse_models_settings,
    _parse_path_settings,
    _parse_prompt_settings,
    _parse_rag_settings,
    _parse_topic_model_settings,
    _parse_thinking_settings,
)


@dataclass
class Settings:
    """
    统一配置入口

    修改时间: 2026-03-12
    修改者: TraeAI
    修改内容: 添加 thinking 配置字段
    """

    models: ModelsSettings = field(default_factory=ModelsSettings)
    thinking: ThinkingSettings = field(default_factory=ThinkingSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    chunking: ChunkingSettings = field(default_factory=ChunkingSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    paths: PathSettings = field(default_factory=PathSettings)
    api: APISettings = field(default_factory=APISettings)
    analysis: AnalysisSettings = field(default_factory=AnalysisSettings)
    topic_model: TopicModelSettings = field(default_factory=TopicModelSettings)
    diagnosis: DiagnosisSettings = field(default_factory=DiagnosisSettings)
    metrics: MetricsSettings = field(default_factory=MetricsSettings)
    rag: RAGSettings = field(default_factory=RAGSettings)
    prompts: PromptSettings = field(default_factory=PromptSettings)

    @classmethod
    def from_json(cls, path: Path | None = None) -> "Settings":
        """从JSON文件加载配置"""
        config_path = path or Path("config/settings.json")
        if not config_path.exists():
            return cls()
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return cls._parse_from_dict(data)

    @classmethod
    def from_env(cls) -> "Settings":
        """从环境变量加载配置（覆盖JSON配置）"""
        base = cls.from_json()
        if os.getenv("CHUNK_MAX_CHARS"):
            base.chunking.max_chars = int(os.getenv("CHUNK_MAX_CHARS", "2000"))
        if os.getenv("CHUNK_OVERLAP"):
            base.chunking.overlap = int(os.getenv("CHUNK_OVERLAP", "200"))
        if os.getenv("DB_TIMEOUT_S"):
            base.database.timeout_s = float(os.getenv("DB_TIMEOUT_S", "30.0"))
        if os.getenv("UPLOAD_DIR"):
            base.paths.upload_dir = Path(os.getenv("UPLOAD_DIR", "data/uploads"))
        if os.getenv("RESULTS_DIR"):
            base.paths.results_dir = Path(os.getenv("RESULTS_DIR", "outputs"))
        if os.getenv("LOG_DIR"):
            base.paths.log_dir = Path(os.getenv("LOG_DIR", "logs"))
        if os.getenv("API_CORS_ORIGINS"):
            base.api.cors_origins = os.getenv("API_CORS_ORIGINS", "*").split(",")
        if os.getenv("DISAMBIG_INTERVAL"):
            base.analysis.incremental_disambig_interval = int(os.getenv("DISAMBIG_INTERVAL", "10"))
        return base

    @classmethod
    def _parse_from_dict(cls, data: dict[str, Any]) -> "Settings":
        """从字典解析配置"""
        return cls(
            models=_parse_models_settings(data.get("models")),
            thinking=_parse_thinking_settings(data.get("thinking")),
            logging=_parse_logging_settings(data.get("logging")),
            chunking=_parse_chunking_settings(data.get("chunking")),
            database=_parse_database_settings(data.get("database")),
            paths=_parse_path_settings(data.get("paths")),
            api=_parse_api_settings(data.get("api")),
            analysis=_parse_analysis_settings(data.get("analysis")),
            topic_model=_parse_topic_model_settings(data.get("topic_model")),
            diagnosis=_parse_diagnosis_settings(data.get("diagnosis")),
            metrics=_parse_metrics_settings(data.get("metrics")),
            rag=_parse_rag_settings(data.get("rag")),
            prompts=_parse_prompt_settings(data.get("prompts")),
        )


settings = Settings.from_env()
