from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from src.runtime_env import load_ltp_environment, load_model_environment

from .schemas import (
    LinguisticSettings,
    LoggingSettings,
    MetricsSettings,
    ModelsSettings,
    ParagraphSettings,
    PathSettings,
    ProgressSettings,
    TopicModelSettings,
    _parse_linguistic_settings,
    _parse_logging_settings,
    _parse_metrics_settings,
    _parse_models_settings,
    _parse_paragraph_settings,
    _parse_path_settings,
    _parse_topic_model_settings,
    apply_linguistic_environment,
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
    # 2026-08-28：语言结构基础数据阶段（LTP/固定短语/Word2Vec，§3.1 B/C 赛道）
    linguistic: LinguisticSettings = field(default_factory=LinguisticSettings)
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
        cls._apply_runtime_environment(base)
        return base

    @classmethod
    def from_config_dict(cls, data: dict[str, Any]) -> Settings:
        """2026-09-10 从配置字典构建完整 Settings（默认值 + 用户覆盖 + env 凭据叠加）

        与 from_env 的唯一差异是配置来源：文件 / 设置页提交的合并字典。
        供保存链路复用同一套解析校验与环境变量叠加顺序。
        """
        instance = cls._parse_from_dict(data)
        cls._apply_runtime_environment(instance)
        return instance

    @classmethod
    def parse_from_dict(cls, data: dict[str, Any]) -> Settings:
        """2026-09-10 解析配置字典（不含 env 叠加）

        供设置保存链路对"纯文件语义"的实例做稀疏 diff——env 注入值
        （凭据、LTP_MODEL_DIR）不得经 diff 落进 settings.json。
        """
        return cls._parse_from_dict(data)

    @classmethod
    def _apply_runtime_environment(cls, instance: Settings) -> None:
        """把环境变量凭据叠加到实例上（MODEL/EMBEDDING_MODEL/LTP 单一解析边界在 runtime_env）"""
        apply_model_environment(
            instance.models,
            load_model_environment("MODEL"),
            load_model_environment("EMBEDDING_MODEL"),
        )
        apply_linguistic_environment(instance.linguistic, load_ltp_environment())

    @classmethod
    def _parse_from_dict(cls, data: dict[str, Any]) -> Settings:
        """从字典解析配置"""
        return cls(
            models=_parse_models_settings(data.get("models")),
            logging=_parse_logging_settings(data.get("logging")),
            paths=_parse_path_settings(data.get("paths")),
            topic_model=_parse_topic_model_settings(data.get("topic_model")),
            linguistic=_parse_linguistic_settings(data.get("linguistic")),
            metrics=_parse_metrics_settings(data.get("metrics")),
            paragraphs=_parse_paragraph_settings(data.get("paragraphs")),
        )


settings = Settings.from_env()


def serialize_settings(instance: Settings) -> dict[str, Any]:
    """2026-09-10 Settings → 深层 dict（嵌套 dataclass 全展开），作为默认值/生效值的序列化出口

    Path 字段（paths 段）统一转 posix 字符串：asdict 不转换 Path，
    而 JSON 序列化与 diff 对比都需要 JSON 兼容值。
    """

    def _jsonify(node: Any) -> Any:
        if isinstance(node, Path):
            return node.as_posix()
        if isinstance(node, dict):
            return {key: _jsonify(value) for key, value in node.items()}
        if isinstance(node, list):
            return [_jsonify(item) for item in node]
        return node

    return _jsonify(asdict(instance))


def apply_settings_onto(target: Settings, source: Settings) -> None:
    """2026-09-10 把 source 的字段值原地写入 target（保持单例对象身份不变）

    全部消费方以 `from src.config import settings` 持有单例引用，
    热生效必须原地变更字段而非替换对象。
    """
    for field_info in fields(Settings):
        setattr(target, field_info.name, getattr(source, field_info.name))


def diff_user_overrides(effective: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """2026-09-10 计算与默认值的差异（稀疏覆盖集），用于把用户设置写回 settings.json

    只保留与 defaults 不同的叶子；嵌套 dict 递归对比；effective 中
    defaults 不存在的键直接丢弃（settings.json 只承载已知参数）。
    例外：defaults 侧为空 dict 时视为开放键空间（如 logging.modules 的
    模块名可增删），此时 effective 的键整体保留而非按"未知键"剔除。
    """
    result: dict[str, Any] = {}
    for key, value in effective.items():
        if key not in defaults:
            continue
        base = defaults[key]
        if isinstance(value, dict) and isinstance(base, dict):
            if not base:
                if value:
                    result[key] = value
            else:
                nested = diff_user_overrides(value, base)
                if nested:
                    result[key] = nested
        elif value != base:
            result[key] = value
    return result
