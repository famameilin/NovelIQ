"""阶段二：多维置信度评分

参考 simple_read_pro 的评分设计：confidence 从 1.0 起，逐维度乘法叠加：
标题长度、行首锚定、编号严格性、虚词开头、编号连续性、同类密度。
"""

from __future__ import annotations

import re

from src.chapters.constants import _CN_NUMERALS, ChapterConfig
from src.chapters.models import ChapterCandidate, ChapterLevel

_CN_NUMERAL_RE = re.compile(f"[{_CN_NUMERALS}]")
_STRICTNESS_LEVELS = {
    ChapterLevel.CHAPTER,
    ChapterLevel.SECTION,
    ChapterLevel.HUI,
    ChapterLevel.ESSAY,
}


def score_candidates(
    candidates: list[ChapterCandidate],
    config: ChapterConfig | None = None,
) -> list[ChapterCandidate]:
    """对候选执行全部评分维度（原地调整 confidence）"""
    config = config or ChapterConfig()
    for candidate in candidates:
        _score_basic(candidate, config)
    _apply_number_continuity(candidates, config)
    _apply_level_density(candidates, config)
    return candidates


def _score_basic(candidate: ChapterCandidate, config: ChapterConfig) -> None:
    """标题长度 / 行首 / 编号严格性 / 虚词开头"""
    confidence = 1.0

    title_length = len(candidate.display_title)
    if title_length < config.min_title_length:
        confidence *= config.score_short_title
    elif title_length > config.max_title_length:
        confidence *= config.score_long_title
    else:
        confidence *= config.score_normal_title

    confidence *= config.score_line_start

    if candidate.level in _STRICTNESS_LEVELS:
        label = candidate.label
        if _CN_NUMERAL_RE.search(label) and "第" not in label:
            confidence *= config.score_no_leading_word

    if candidate.display_title.startswith(config.filler_prefix_chars):
        confidence *= config.score_filler_prefix

    if (
        candidate.level in (ChapterLevel.ESSAY, ChapterLevel.VOLUME, ChapterLevel.PART)
        and candidate.number is None
    ):
        confidence *= config.score_named_volume

    candidate.confidence = confidence


def _apply_number_continuity(
    candidates: list[ChapterCandidate],
    config: ChapterConfig,
) -> None:
    """编号连续性：同层相邻候选编号递增且不超过阈值加分，递减降权"""
    for group in _group_by_level(candidates).values():
        for previous, current in zip(group, group[1:], strict=False):
            if previous.number is None or current.number is None:
                continue
            delta = current.number - previous.number
            if 1 <= delta <= config.max_expected_number_delta:
                current.confidence *= config.score_number_increment
            elif delta < 0:
                current.confidence *= config.score_number_decrement


def _apply_level_density(
    candidates: list[ChapterCandidate],
    config: ChapterConfig,
) -> None:
    """同类密度：同层候选间隔均匀时加分，参差时降权"""
    for group in _group_by_level(candidates).values():
        if len(group) < 3:
            continue
        intervals = [
            next_candidate.start_char - current.start_char
            for current, next_candidate in zip(group, group[1:], strict=False)
        ]
        mean = sum(intervals) / len(intervals)
        if mean <= 0:
            continue
        mean_abs_deviation = sum(abs(x - mean) for x in intervals) / len(intervals)
        ratio = mean_abs_deviation / mean
        if ratio < 0.5:
            factor = config.score_density_even
        elif ratio < 1.0:
            factor = config.score_density_normal
        else:
            factor = config.score_density_irregular
        for candidate in group:
            candidate.confidence *= factor


def _group_by_level(candidates: list[ChapterCandidate]) -> dict[ChapterLevel, list[ChapterCandidate]]:
    """按层级分组（保持位置顺序）"""
    groups: dict[ChapterLevel, list[ChapterCandidate]] = {}
    for candidate in candidates:
        groups.setdefault(candidate.level, []).append(candidate)
    return groups
