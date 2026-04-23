"""
类型检测 weighted config 辅助。

创建时间: 2026-04-23
任务: p1-genre-detector-split
说明: 拆出多类型加权检测和 weighted lexicon config 组装逻辑。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.lexicons.genre_detector_rules import get_recommended_lexicons
from src.lexicons.genre_detector_sampling import sample_weighted_chunk_indices


@dataclass
class WeightedGenreResult:
    """多类型加权检测结果。"""

    genre_weights: list[tuple[str, float]]
    sample_count: int
    raw_scores: dict[str, float]


def detect_genre_weighted(
    chunk_texts: list[tuple[int, str]],
    *,
    detect_genre_fn: Callable[[str], Any],
    sample_ratio: float = 0.1,
    min_samples: int = 10,
) -> WeightedGenreResult:
    """
    多类型加权检测。

    创建时间: 2026-04-23
    任务: p1-genre-detector-split
    说明: 将 weighted detect 从主模块中抽出，只保留一个 detect 回调依赖。
    """
    total_chunks = len(chunk_texts)
    if total_chunks == 0:
        return WeightedGenreResult(genre_weights=[("general", 1.0)], sample_count=0, raw_scores={})

    sample_indices = sample_weighted_chunk_indices(total_chunks, sample_ratio, min_samples)
    genre_scores: dict[str, float] = {}
    for idx in sample_indices:
        _, text = chunk_texts[idx]
        result = detect_genre_fn(text)
        for genre, score in result.scores.items():
            genre_scores[genre] = genre_scores.get(genre, 0.0) + score

    if not genre_scores:
        return WeightedGenreResult(
            genre_weights=[("general", 1.0)],
            sample_count=len(sample_indices),
            raw_scores={},
        )

    total_score = sum(genre_scores.values())
    if total_score == 0:
        return WeightedGenreResult(
            genre_weights=[("general", 1.0)],
            sample_count=len(sample_indices),
            raw_scores=genre_scores,
        )

    normalized_scores = {genre: score / total_score for genre, score in genre_scores.items()}
    sorted_genres = sorted(normalized_scores.items(), key=lambda item: -item[1])

    genre_weights: list[tuple[str, float]] = []
    accumulated = 0.0
    for genre, weight in sorted_genres:
        if accumulated >= 1.0:
            break
        genre_weights.append((genre, weight))
        accumulated += weight

    if genre_weights:
        total_weight = sum(weight for _, weight in genre_weights)
        genre_weights = [(genre, weight / total_weight) for genre, weight in genre_weights]
    if not genre_weights:
        genre_weights = [("general", 1.0)]

    return WeightedGenreResult(
        genre_weights=genre_weights,
        sample_count=len(sample_indices),
        raw_scores=normalized_scores,
    )


def get_weighted_lexicon_config(
    genre_weights: list[tuple[str, float]],
) -> list[tuple[str, dict[str, list[str]], float]]:
    """
    根据加权类型列表获取词表配置。

    创建时间: 2026-04-23
    任务: p1-genre-detector-split
    说明: 将 weighted config 组装独立出来，供主模块与其他调用方复用。
    """
    result: list[tuple[str, dict[str, list[str]], float]] = []
    for genre, weight in genre_weights:
        result.append((genre, get_recommended_lexicons(genre), weight))
    return result
