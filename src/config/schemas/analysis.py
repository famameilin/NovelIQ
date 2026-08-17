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
    # 段落 LDA 训练排除的短段 token 阈值（设计 §11.1，待标定）
    min_paragraph_train_tokens: int = 5
    # 2026-08-16 N2：num_topics 按训练文档数缩放
    num_topics_min: int = 3
    num_topics_max: int = 25
    num_topics_scaling_divisor: int = 30
    # 段落主题推断写入时的模型版本标识（§5.4）
    topic_model_version: str = "2"
    lda: LdaSettings = field(default_factory=LdaSettings)


@dataclass
class MetricsSettings:
    """
    指标计算配置
    """

    mtld_threshold: float = 0.72
    middle_collapse_min_chunks: int = 10
    character_max_iter: int = 100
    # 段落指标版本标识（§5.3 metric_version；v2=词表体系重设计 M1-M6 后语义：命中计数+共享否定层）
    metric_version: str = "2"
    # 段落曲线版本标识（§5.5 curve_version）
    curve_version: str = "1"
    # LOWESS 平滑参数（§9.3，默认 2% 带宽/最少 7 点，待真实小说标定）
    lowess_bandwidth: float = 0.02
    lowess_min_points: int = 7
    # 段落表层张力分量权重（§9.2，初始等权；键：fight/exclaim/question/dialogue/pause）
    surface_tension_weights: dict[str, float] = field(
        default_factory=lambda: {
            "fight": 0.2,
            "exclaim": 0.2,
            "question": 0.2,
            "dialogue": 0.2,
            "pause": 0.2,
        }
    )


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
        min_paragraph_train_tokens=data.get("min_paragraph_train_tokens", 5),
        num_topics_min=data.get("num_topics_min", 3),
        num_topics_max=data.get("num_topics_max", 25),
        num_topics_scaling_divisor=data.get("num_topics_scaling_divisor", 30),
        topic_model_version=data.get("topic_model_version", "2"),
        lda=_parse_lda_settings(data.get("lda")),
    )


def _parse_metrics_settings(data: dict[str, Any] | None) -> MetricsSettings:
    """
    解析指标配置
    """
    if not data:
        return MetricsSettings()
    surface_tension_weights = data.get("surface_tension_weights")
    lowess_bandwidth = data.get("lowess_bandwidth", 0.02)
    lowess_min_points = data.get("lowess_min_points", 7)
    # 2026-08-15 M3：非正带宽在平滑入口会快速失败（自适应扩窗 h *= 2.0 恒不变），
    # 配置层提前校验避免分析中途崩溃；带宽是全文比例，>1 已无窗口意义
    if isinstance(lowess_bandwidth, bool) or not isinstance(lowess_bandwidth, (int, float)):
        raise ValueError(f"lowess_bandwidth 必须是数值，当前值: {lowess_bandwidth!r}")
    if not 0 < lowess_bandwidth <= 1:
        raise ValueError(f"lowess_bandwidth 必须在 (0, 1] 区间内，当前值: {lowess_bandwidth}")
    if isinstance(lowess_min_points, bool) or not isinstance(lowess_min_points, int) or lowess_min_points < 1:
        raise ValueError(f"lowess_min_points 必须是 ≥1 的整数，当前值: {lowess_min_points!r}")
    return MetricsSettings(
        mtld_threshold=data.get("mtld_threshold", 0.72),
        middle_collapse_min_chunks=data.get("middle_collapse_min_chunks", 10),
        character_max_iter=data.get("character_max_iter", 100),
        metric_version=data.get("metric_version", "2"),
        curve_version=data.get("curve_version", "1"),
        lowess_bandwidth=lowess_bandwidth,
        lowess_min_points=lowess_min_points,
        surface_tension_weights=(
            surface_tension_weights if isinstance(surface_tension_weights, dict) else None
        )
        or MetricsSettings().surface_tension_weights,
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
