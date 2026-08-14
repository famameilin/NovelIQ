"""
本模块包含分析相关的配置数据类
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StageProgressRange:
    """
    阶段进度范围配置

    说明: 定义每个阶段的进度百分比范围 [start, end]
    """

    start: float = 0.0
    end: float = 100.0


@dataclass
class ProgressSettings:
    """
    分析进度配置
    """

    preprocess: StageProgressRange = field(default_factory=lambda: StageProgressRange(0, 10))
    annotate: StageProgressRange = field(default_factory=lambda: StageProgressRange(10, 80))
    aggregate: StageProgressRange = field(default_factory=lambda: StageProgressRange(80, 90))
    topic_model: StageProgressRange = field(default_factory=lambda: StageProgressRange(90, 95))
    diagnose: StageProgressRange = field(default_factory=lambda: StageProgressRange(95, 100))


@dataclass
class LdaSettings:
    """LDA 主题模型公共参数"""

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

    num_topics: int = 25
    passes: int = 10
    iterations: int = 500
    lda: LdaSettings = field(default_factory=LdaSettings)


@dataclass
class MetricsSettings:
    """
    指标计算配置
    """

    mtld_threshold: float = 0.72
    middle_collapse_min_chunks: int = 10
    character_max_iter: int = 100
    fourier_smooth_keep_ratio: float = 0.1


def _parse_stage_progress_range(
    data: dict[str, Any] | None,
    default_start: float,
    default_end: float,
) -> StageProgressRange:
    """
    解析阶段进度范围配置
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


def _parse_lda_settings(data: dict[str, Any] | None) -> LdaSettings:
    """解析 LDA 公共参数"""
    if not data:
        return LdaSettings()
    return LdaSettings(
        alpha=data.get("alpha", "auto"),
        eta=data.get("eta", "auto"),
        random_state=data.get("random_state", 42),
        chunksize=data.get("chunksize", 2000),
        minimum_probability=data.get("minimum_probability", 0.01),
        no_below=data.get("no_below", 5),
        no_above=data.get("no_above", 0.5),
    )


def _parse_topic_model_settings(data: dict[str, Any] | None) -> TopicModelSettings:
    """解析主题模型配置"""
    if not data:
        return TopicModelSettings()
    return TopicModelSettings(
        num_topics=data.get("num_topics", 25),
        passes=data.get("passes", 10),
        iterations=data.get("iterations", 500),
        lda=_parse_lda_settings(data.get("lda")),
    )


def _parse_metrics_settings(data: dict[str, Any] | None) -> MetricsSettings:
    """
    解析指标配置
    """
    if not data:
        return MetricsSettings()
    return MetricsSettings(
        mtld_threshold=data.get("mtld_threshold", 0.72),
        middle_collapse_min_chunks=data.get("middle_collapse_min_chunks", 10),
        character_max_iter=data.get("character_max_iter", 100),
        fourier_smooth_keep_ratio=data.get("fourier_smooth_keep_ratio", 0.1),
    )


@dataclass
class ParagraphSettings:
    """
    段落事实源配置

    说明: paragraphs 是 run 内段落身份的唯一事实源（设计文档《段落分析原子与章节汇总重设计方案》§5.1），
    段落切分参数与切分/分词版本号在此统一管理，版本号写入 paragraphs 行用于后续无效化判断
    """

    max_chars: int = 1500
    splitter_version: str = "1"
    tokenizer_version: str = "1"


def _parse_paragraph_settings(data: dict[str, Any] | None) -> ParagraphSettings:
    """
    解析段落事实源配置
    """
    if not data:
        return ParagraphSettings()
    return ParagraphSettings(
        max_chars=data.get("max_chars", 1500),
        splitter_version=data.get("splitter_version", "1"),
        tokenizer_version=data.get("tokenizer_version", "1"),
    )
