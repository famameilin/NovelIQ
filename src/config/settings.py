
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.runtime_env import load_model_environment

from .schemas import (
    LoggingSettings,
    MetricsSettings,
    ModelsSettings,
    ParagraphSettings,
    PathSettings,
    ProgressSettings,
    TopicModelSettings,
    _parse_logging_settings,
    _parse_metrics_settings,
    _parse_models_settings,
    _parse_paragraph_settings,
    _parse_path_settings,
    _parse_progress_settings,
    _parse_topic_model_settings,
)
from .schemas.model import apply_model_environment


@dataclass
class Settings:
    """
    统一配置入口
    """

    models: ModelsSettings = field(default_factory=ModelsSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    paths: PathSettings = field(default_factory=PathSettings)
    progress: ProgressSettings = field(default_factory=ProgressSettings)
    topic_model: TopicModelSettings = field(default_factory=TopicModelSettings)
    metrics: MetricsSettings = field(default_factory=MetricsSettings)
    # 2026-08-14：段落事实源配置（max_chars/版本号），见 schemas.analysis.ParagraphSettings
    paragraphs: ParagraphSettings = field(default_factory=ParagraphSettings)
    # 2026-08-14 D9：prompts 死配置已移除（旧 phase 合同退役，提示词硬编码于 agents/*/prompts.py）

    @classmethod
    def from_json(cls, path: Path | None = None) -> Settings:
        """从JSON文件加载配置"""
        config_path = path or Path("config/settings.json")
        if not config_path.exists():
            return cls()
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return cls._parse_from_dict(data)

    @classmethod
    def from_env(cls) -> Settings:
        """
        2026-08-03 用于加载四对象环境契约中的模型配置
        """

        base = cls.from_json()
        apply_model_environment(
            base.models,
            load_model_environment("MODEL"),
            load_model_environment("EMBEDDING_MODEL"),
        )
        return base

    @classmethod
    def _parse_from_dict(cls, data: dict[str, Any]) -> Settings:
        """从字典解析配置"""
        return cls(
            models=_parse_models_settings(data.get("models")),
            logging=_parse_logging_settings(data.get("logging")),
            paths=_parse_path_settings(data.get("paths")),
            progress=_parse_progress_settings(data.get("progress")),
            topic_model=_parse_topic_model_settings(data.get("topic_model")),
            metrics=_parse_metrics_settings(data.get("metrics")),
            paragraphs=_parse_paragraph_settings(data.get("paragraphs")),
        )


settings = Settings.from_env()
