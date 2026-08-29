"""
本模块包含分析相关的配置数据类
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.config.constants import STAGE_PROGRESS_MILESTONES
from src.runtime_env import LtpEnvironment


@dataclass
class StageProgressRange:
    """
    阶段进度范围配置

    说明: 定义每个阶段的进度百分比范围 [start, end]
    """

    start: float = 0.0
    end: float = 100.0


def _stage_progress_range(stage: str) -> StageProgressRange:
    """从 STAGE_PROGRESS_MILESTONES 推导阶段区间：起点=上一阶段完成点，首阶段起点=0"""
    stages = list(STAGE_PROGRESS_MILESTONES)
    index = stages.index(stage)
    start = 0.0 if index == 0 else STAGE_PROGRESS_MILESTONES[stages[index - 1]]
    return StageProgressRange(start, STAGE_PROGRESS_MILESTONES[stage])


@dataclass
class ProgressSettings:
    """
    分析进度配置（默认值来自 constants.STAGE_PROGRESS_MILESTONES，不再从 settings.json 读取）
    """

    preprocess: StageProgressRange = field(default_factory=lambda: _stage_progress_range("preprocess"))
    annotate: StageProgressRange = field(default_factory=lambda: _stage_progress_range("annotate"))
    linguistic: StageProgressRange = field(default_factory=lambda: _stage_progress_range("linguistic"))
    aggregate: StageProgressRange = field(default_factory=lambda: _stage_progress_range("aggregate"))
    topic_model: StageProgressRange = field(default_factory=lambda: _stage_progress_range("topic_model"))
    diagnose: StageProgressRange = field(default_factory=lambda: _stage_progress_range("diagnose"))


@dataclass
class LdaSettings:
    """LDA 主题模型公共参数"""

    alpha: str = "auto"
    eta: str = "auto"
    random_state: int = 42
    lda_batch_size: int = 2000
    minimum_probability: float = 0.01
    no_below: int = 5
    no_above: float = 0.5


@dataclass
class TopicShiftSettings:
    """主题变化候选计算配置（《分析能力扩展路线图》§5.11/D2）

    窗口大小、平滑方式和阈值均为版本化配置，不在代码中写死；
    topic_shift_score 定义为以 2 为底、范围 [0, 1] 的 JS 散度。
    """

    window_size: int = 10
    min_tokens_per_window: int = 50
    score_threshold: float = 0.3
    max_candidates: int = 50


@dataclass
class LtpSettings:
    """LTP 语言结构服务配置（《分析能力扩展路线图》赛道 C1/C2）"""

    enabled: bool = True
    # 离线模型目录（仅由 LTP_MODEL_DIR 环境变量提供，不走 settings.json）；未配置时 LtpSession 加载报错
    model_dir: str | None = None
    max_length: int = 512
    # 依存坐标系：LTP 用 ROOT=0、词元索引 1 起（文档 §C2 统一坐标系）
    dep_root_index: int = 0


@dataclass
class Word2VecSettings:
    """词向量能力配置（《分析能力扩展路线图》赛道 C3）

    单流水线：预训练词向量初始化 + 本书语料微调（warm-start）。
    默认关闭；开启时 model_dir 必须指向预训练词向量目录，维度以
    预训练文件头为准。
    """

    enabled: bool = False
    model_dir: str | None = None  # 预训练词向量目录
    window: int = 5
    min_count: int = 2
    epochs: int = 5


@dataclass
class LinguisticSettings:
    """语言结构基础数据阶段配置（《分析能力扩展路线图》§3.1 B/C 赛道）"""

    ltp: LtpSettings = field(default_factory=LtpSettings)
    word2vec: Word2VecSettings = field(default_factory=Word2VecSettings)


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
    lda: LdaSettings = field(default_factory=LdaSettings)
    # 2026-08-28 主题变化候选配置（《分析能力扩展路线图》§5.11/D2 版本化参数）
    topic_shift: TopicShiftSettings = field(default_factory=TopicShiftSettings)


@dataclass
class MetricsSettings:
    """
    指标计算配置
    """

    mtld_threshold: float = 0.72
    middle_collapse_min_chunks: int = 10
    # 2026-08-16 P7/N6：短书不再输出伪精确值；比率/结构指标低于该章数返回 null
    small_sample_min_chapters: int = 10
    # 2026-08-16 N3：虚字指纹在短文本下是噪声，低于该字符数返回 null
    function_word_min_chars: int = 100_000
    character_max_iter: int = 100
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


def _parse_lda_settings(data: dict[str, Any] | None) -> LdaSettings:
    """解析 LDA 公共参数"""
    if not data:
        return LdaSettings()
    if "chunksize" in data:
        raise ValueError("topic_model.lda.chunksize 已移除，请使用 topic_model.lda.lda_batch_size")
    return LdaSettings(
        alpha=data.get("alpha", "auto"),
        eta=data.get("eta", "auto"),
        random_state=data.get("random_state", 42),
        lda_batch_size=data.get("lda_batch_size", 2000),
        minimum_probability=data.get("minimum_probability", 0.01),
        no_below=data.get("no_below", 5),
        no_above=data.get("no_above", 0.5),
    )


def _parse_topic_shift_settings(data: dict[str, Any] | None) -> TopicShiftSettings:
    """解析主题变化候选配置（带约束校验，非法值在配置加载期快速失败）"""
    if not data:
        return TopicShiftSettings()
    window_size = data.get("window_size", 10)
    if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 1:
        raise ValueError(f"topic_shift.window_size 必须是 ≥1 的整数，当前值: {window_size!r}")
    min_tokens = data.get("min_tokens_per_window", 50)
    if isinstance(min_tokens, bool) or not isinstance(min_tokens, int) or min_tokens < 1:
        raise ValueError(f"topic_shift.min_tokens_per_window 必须是 ≥1 的整数，当前值: {min_tokens!r}")
    threshold = data.get("score_threshold", 0.3)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError(f"topic_shift.score_threshold 必须是数值，当前值: {threshold!r}")
    if not 0 < threshold <= 1:
        raise ValueError(f"topic_shift.score_threshold 必须在 (0, 1] 区间内，当前值: {threshold}")
    max_candidates = data.get("max_candidates", 50)
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or max_candidates < 1:
        raise ValueError(f"topic_shift.max_candidates 必须是 ≥1 的整数，当前值: {max_candidates!r}")
    return TopicShiftSettings(
        window_size=window_size,
        min_tokens_per_window=min_tokens,
        score_threshold=float(threshold),
        max_candidates=max_candidates,
    )


def _parse_ltp_settings(data: dict[str, Any] | None) -> LtpSettings:
    """解析 LTP 语言结构服务配置"""
    if not data:
        return LtpSettings()
    enabled = data.get("enabled", True)
    if isinstance(enabled, bool) is False:
        raise ValueError(f"linguistic.ltp.enabled 必须是布尔值，当前值: {enabled!r}")
    return LtpSettings(
        enabled=enabled,
        max_length=data.get("max_length", 512),
        dep_root_index=data.get("dep_root_index", 0),
    )


def _parse_word2vec_settings(data: dict[str, Any] | None) -> Word2VecSettings:
    """解析词向量能力配置"""
    if not data:
        return Word2VecSettings()
    return Word2VecSettings(
        enabled=data.get("enabled", False),
        model_dir=data.get("model_dir"),
        window=data.get("window", 5),
        min_count=data.get("min_count", 2),
        epochs=data.get("epochs", 5),
    )


def _parse_linguistic_settings(data: dict[str, Any] | None) -> LinguisticSettings:
    """解析语言结构基础数据阶段配置"""
    if not data:
        return LinguisticSettings()
    return LinguisticSettings(
        ltp=_parse_ltp_settings(data.get("ltp")),
        word2vec=_parse_word2vec_settings(data.get("word2vec")),
    )


def apply_linguistic_environment(
    settings: LinguisticSettings,
    ltp_environment: LtpEnvironment | None,
) -> None:
    """
    2026-08-28 用于把 LTP 环境变量映射到语言结构配置；
    None 表示该组未配置，model_dir 保持为空（LTP 加载时报错）
    """

    if ltp_environment is not None:
        settings.ltp.model_dir = ltp_environment.model_dir


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
        lda=_parse_lda_settings(data.get("lda")),
        topic_shift=_parse_topic_shift_settings(data.get("topic_shift")),
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
        small_sample_min_chapters=data.get("small_sample_min_chapters", 10),
        function_word_min_chars=data.get("function_word_min_chars", 100_000),
        character_max_iter=data.get("character_max_iter", 100),
        lowess_bandwidth=lowess_bandwidth,
        lowess_min_points=lowess_min_points,
        surface_tension_weights=(surface_tension_weights if isinstance(surface_tension_weights, dict) else None)
        or MetricsSettings().surface_tension_weights,
    )


@dataclass
class ParagraphSettings:
    """
    段落事实源配置

    说明: paragraphs 是 run 内段落身份的唯一事实源
    """

    max_chars: int = 1500


def _parse_paragraph_settings(data: dict[str, Any] | None) -> ParagraphSettings:
    """
    解析段落事实源配置
    """
    if not data:
        return ParagraphSettings()
    return ParagraphSettings(
        max_chars=data.get("max_chars", 1500),
    )
