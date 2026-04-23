"""
小说类型自动检测模块

根据领域词表命中模式自动识别小说类型。

支持的类型:
- xianxia: 修仙/仙侠类
- urban: 都市/言情类
- power: 权谋/宫斗类
- shuwen: 爽文/快节奏类
- general: 通用/无法确定

创建时间: 2026-04-06
创建者: GLM-5
任务: 词表与张力信号系统重构 - Task 10

修改时间: 2026-04-06
修改者: GLM-5
任务: 类型检测模块修复
修改内容:
  - P0: indicators 纳入得分计算，权重为词表的 2 倍
  - P1: 新增分段检测功能，支持类型序列输出

修改时间: 2026-04-06
修改者: GLM-5
任务: 代码审查问题修复
修改内容: 添加低置信度检测日志输出，便于后续调优
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from src.lexicons.genre_detector_rules import (
    DOMAIN_KEYWORDS,
    INDICATOR_WEIGHT,
    MIN_CONFIDENCE,
    get_recommended_lexicons,
)
from src.lexicons.genre_detector_sampling import (
    build_text_segments,
    read_text_with_fallback,
)
from src.lexicons.genre_detector_weighted import (
    WeightedGenreResult,
)
from src.lexicons.genre_detector_weighted import (
    detect_genre_weighted as detect_genre_weighted_impl,
)
from src.lexicons.genre_detector_weighted import (
    get_weighted_lexicon_config as get_weighted_lexicon_config_impl,
)
from src.lexicons.registry import LexiconRegistry
from src.utils.text_utils import tokenize_words

if TYPE_CHECKING:
    from pathlib import Path


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
    检测小说类型。

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


def detect_genre_from_file(
    file_path: Path,
    sample_size: int = 5000,
    registry: LexiconRegistry | None = None,
) -> GenreDetectionResult:
    """
    从文件检测小说类型。

    Args:
        file_path: 小说文件路径
        sample_size: 采样字数
        registry: 词表注册中心

    Returns:
        类型检测结果
    """
    content = read_text_with_fallback(file_path, limit=sample_size)
    if content is None:
        return GenreDetectionResult(
            genre="general",
            confidence=0.0,
            scores={},
            top_indicators=[],
        )

    return detect_genre(content, registry)


def detect_genre_sequence(
    text: str,
    segment_size: int = 5000,
    overlap: int = 500,
    registry: LexiconRegistry | None = None,
) -> GenreSequenceResult:
    """
    分段检测小说类型，输出类型序列。

    用于处理"前期都市后期修仙"等类型变化的场景。

    Args:
        text: 完整文本
        segment_size: 每段字数
        overlap: 段间重叠字数
        registry: 词表注册中心

    Returns:
        类型序列检测结果
    """
    if registry is None:
        registry = LexiconRegistry()
        registry.load()

    segments: list[SegmentGenreResult] = []
    for idx, (start, end, segment_text) in enumerate(build_text_segments(text, segment_size, overlap)):
        result = detect_genre(segment_text, registry)

        segments.append(
            SegmentGenreResult(
                segment_index=idx,
                start_char=start,
                end_char=end,
                genre=result.genre,
                confidence=result.confidence,
                scores=result.scores,
                top_indicators=result.top_indicators,
            )
        )

    genre_counts: dict[str, int] = {}
    for seg in segments:
        genre_counts[seg.genre] = genre_counts.get(seg.genre, 0) + 1

    total_segments = len(segments)
    genre_distribution = {g: c / total_segments for g, c in genre_counts.items() if total_segments > 0}

    dominant_genre = max(genre_distribution.keys(), key=lambda k: genre_distribution[k])

    transitions: list[tuple[int, str, str]] = []
    for i in range(1, len(segments)):
        prev_genre = segments[i - 1].genre
        curr_genre = segments[i].genre
        if prev_genre != curr_genre:
            transitions.append((segments[i].start_char, prev_genre, curr_genre))

    return GenreSequenceResult(
        segments=segments,
        genre_distribution=genre_distribution,
        dominant_genre=dominant_genre,
        genre_transitions=transitions,
    )


def detect_genre_sequence_from_file(
    file_path: Path,
    segment_size: int = 5000,
    overlap: int = 500,
    registry: LexiconRegistry | None = None,
) -> GenreSequenceResult:
    """
    从文件分段检测小说类型。

    Args:
        file_path: 小说文件路径
        segment_size: 每段字数
        overlap: 段间重叠字数
        registry: 词表注册中心

    Returns:
        类型序列检测结果
    """
    content = read_text_with_fallback(file_path)
    if content is None:
        return GenreSequenceResult(
            segments=[],
            genre_distribution={},
            dominant_genre="general",
            genre_transitions=[],
        )

    return detect_genre_sequence(content, segment_size, overlap, registry)


def get_dynamic_lexicons(
    text: str,
    registry: LexiconRegistry | None = None,
) -> dict[str, set[str]]:
    """
    根据文本内容动态检测类型并加载对应词表。

    用于处理"前期都市后期修仙"等类型变化的场景。

    Args:
        text: 待分析文本
        registry: 词表注册中心

    Returns:
        动态加载的词表集合
    """
    if registry is None:
        registry = LexiconRegistry()
        registry.load()

    result = detect_genre(text, registry)
    config = get_recommended_lexicons(result.genre)

    lexicons: dict[str, set[str]] = {
        "pos_terms": set(),
        "neg_terms": set(),
        "fight_terms": set(),
    }

    for domain in config.get("pos_domains", []):
        terms = registry.get_with_domains("emotion.positive", [domain])
        lexicons["pos_terms"].update(terms)

    for domain in config.get("neg_domains", []):
        terms = registry.get_with_domains("emotion.negative", [domain])
        lexicons["neg_terms"].update(terms)

    for domain in config.get("fight_domains", []):
        terms = registry.get_with_domains("tension.action_terms", [domain])
        lexicons["fight_terms"].update(terms)

    base_pos = registry.get("emotion.positive")
    base_neg = registry.get("emotion.negative")
    base_fight = registry.get("tension.action_terms")

    lexicons["pos_terms"].update(base_pos)
    lexicons["neg_terms"].update(base_neg)
    lexicons["fight_terms"].update(base_fight)

    return lexicons


def get_dynamic_lexicons_for_chunk(
    chunk_text: str,
    chunk_index: int,
    registry: LexiconRegistry | None = None,
) -> tuple[dict[str, set[str]], str]:
    """
    为单个 chunk 动态加载词表。

    Args:
        chunk_text: chunk 文本
        chunk_index: chunk 索引
        registry: 词表注册中心

    Returns:
        (词表集合, 检测到的类型)
    """
    if registry is None:
        registry = LexiconRegistry()
        registry.load()

    result = detect_genre(chunk_text, registry)
    lexicons = get_dynamic_lexicons(chunk_text, registry)

    return lexicons, result.genre

def detect_genre_weighted(
    chunk_texts: list[tuple[int, str]],
    sample_ratio: float = 0.1,
    min_samples: int = 10,
    registry: LexiconRegistry | None = None,
) -> WeightedGenreResult:
    """
    多类型加权检测：均匀采样 chunk，返回加权类型列表。

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

    创建时间: 2026-04-06
    创建者: GLM-5
    任务: 多类型加权混合词表方案
    修改时间: 2026-04-06
    修改者: GLM-5
    修改内容: 移除 max_samples 限制，min_samples 提升到 10
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


def get_weighted_lexicon_config(
    genre_weights: list[tuple[str, float]],
) -> list[tuple[str, dict[str, list[str]], float]]:
    """
    根据加权类型列表获取词表配置。

    Args:
        genre_weights: 类型权重列表，格式 [(genre, weight), ...]

    Returns:
        词表配置列表，格式 [(genre, lexicon_config, weight), ...]

    创建时间: 2026-04-06
    创建者: GLM-5
    任务: 多类型加权混合词表方案
    """
    return get_weighted_lexicon_config_impl(genre_weights)


if __name__ == "__main__":
    from pathlib import Path

    novel_dir = Path("data/novel")
    novel_files = list(novel_dir.glob("*.txt"))

    print("=" * 60)
    print("小说类型自动检测（增强版）")
    print("=" * 60)

    for novel_file in novel_files[:2]:
        print(f"\n{'=' * 40}")
        print(f"文件: {novel_file.name}")
        print("=" * 40)

        result = detect_genre_from_file(novel_file, sample_size=5000)
        print("\n[整体检测]")
        print(f"  类型: {result.genre}")
        print(f"  置信度: {result.confidence:.2%}")
        print(f"  各类型得分: {result.scores}")
        if result.top_indicators:
            print(f"  关键指标: {result.top_indicators}")

        seq_result = detect_genre_sequence_from_file(novel_file, segment_size=5000, overlap=500)
        print(f"\n[分段检测] 共 {len(seq_result.segments)} 段")
        print(f"  类型分布: {seq_result.genre_distribution}")
        print(f"  主导类型: {seq_result.dominant_genre}")
        if seq_result.genre_transitions:
            print(f"  类型转变: {seq_result.genre_transitions}")
        else:
            print("  类型转变: 无")
