"""
小说类型自动检测模块

根据领域词表命中模式自动识别小说类型

当前检测代码会产出两类候选:
- 主题材候选: xianxia / fantasy / urban / scifi / historical / mystery / general
- 第二标签候选: power / shuwen

说明:
- `power` / `shuwen` 仍是底层 detector 的可返回 code，
  但在 diagnosis 正式合同里不再落到 `genre_labels`，而是作为第二标签提示参与 `style_labels` 生成


"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from src.lexicons.genre_detector_rules import (
    DOMAIN_KEYWORDS,
    INDICATOR_WEIGHT,
    MIN_CONFIDENCE,
)
from src.lexicons.genre_detector_weighted import (
    WeightedGenreResult,
)
from src.lexicons.genre_detector_weighted import (
    detect_genre_weighted as detect_genre_weighted_impl,
)
from src.lexicons.registry import LexiconRegistry
from src.utils.text_utils import tokenize_words


@dataclass
class GenreDetectionResult:
    """类型检测结果"""

    genre: str
    confidence: float
    scores: dict[str, float]
    top_indicators: list[str]


@dataclass
class SegmentGenreResult:
    """分段类型检测结果"""

    segment_index: int
    start_char: int
    end_char: int
    genre: str
    confidence: float
    scores: dict[str, float]
    top_indicators: list[str]


@dataclass
class GenreSequenceResult:
    """类型序列检测结果"""

    segments: list[SegmentGenreResult]
    genre_distribution: dict[str, float]
    dominant_genre: str
    genre_transitions: list[tuple[int, str, str]]


def detect_genre(
    text: str,
    registry: LexiconRegistry | None = None,
    min_confidence: float = MIN_CONFIDENCE,
) -> GenreDetectionResult:
    """
    检测小说类型

    Args:
        text: 待检测文本（建议使用前 5000-10000 字）
        registry: 词表注册中心（可选，默认使用全局单例）
        min_confidence: 最低置信度阈值

    Returns:
        类型检测结果
    """
    if registry is None:
        registry = LexiconRegistry()
        registry.load()

    tokens = tokenize_words(text)
    token_count = max(len(tokens), 1)

    scores: dict[str, float] = {}
    indicators_found: dict[str, list[str]] = {}

    for genre, config in DOMAIN_KEYWORDS.items():
        domain_hits = 0
        found_indicators = []

        if "positive" in config:
            for domain in config["positive"]:
                terms = registry.get_with_domains("emotion.positive", [domain])
                domain_hits += sum(1 for t in tokens if t in terms)

        if "negative" in config:
            for domain in config["negative"]:
                terms = registry.get_with_domains("emotion.negative", [domain])
                domain_hits += sum(1 for t in tokens if t in terms)

        for indicator in config.get("indicators", []):
            if indicator in text:
                found_indicators.append(indicator)

        indicator_hits = len(found_indicators) * INDICATOR_WEIGHT
        scores[genre] = (domain_hits + indicator_hits) / token_count
        indicators_found[genre] = found_indicators

    total_score = sum(scores.values())
    if total_score > 0:
        normalized_scores = {k: v / total_score for k, v in scores.items()}
    else:
        normalized_scores = dict.fromkeys(scores, 0.0)

    best_genre = max(normalized_scores.keys(), key=lambda k: normalized_scores[k])
    best_confidence = normalized_scores[best_genre]

    if best_confidence < min_confidence:
        logger.debug(
            f"Low confidence genre detection: best_genre={best_genre}, "
            f"confidence={best_confidence:.2%}, scores={normalized_scores}, "
            f"falling back to 'general'"
        )
        best_genre = "general"
        best_confidence = 0.0

    top_indicators = indicators_found.get(best_genre, [])[:5]

    return GenreDetectionResult(
        genre=best_genre,
        confidence=best_confidence,
        scores=normalized_scores,
        top_indicators=top_indicators,
    )


def detect_genre_weighted(
    chunk_texts: list[tuple[int, str]],
    sample_ratio: float = 0.1,
    min_samples: int = 10,
    registry: LexiconRegistry | None = None,
) -> WeightedGenreResult:
    """
    多类型加权检测：均匀采样 chunk，返回加权类型列表

    策略:
      1. 均匀采样 sample_ratio 比例的 chunk（至少 min_samples）
      2. 对每个采样 chunk 检测类型
      3. 按置信度累加排序，取前 N 个直到权重和 ≥ 1.0
      4. 权重归一化

    Args:
        chunk_texts: chunk 列表，格式 [(chunk_id, text), ...]
        sample_ratio: 采样比例，默认 10%
        min_samples: 最少采样数，默认 10
        registry: 词表注册中心

    Returns:
        WeightedGenreResult: 包含加权类型列表、采样数、原始得分

    """
    if registry is None:
        registry = LexiconRegistry()
        registry.load()

    return detect_genre_weighted_impl(
        chunk_texts,
        detect_genre_fn=lambda text: detect_genre(text, registry),
        sample_ratio=sample_ratio,
        min_samples=min_samples,
    )
