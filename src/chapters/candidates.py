"""阶段一：候选收集

按固定优先级全量扫描各层级正则，提取编号/标题/正文起点；
同一行同时命中多个层级时只保留优先级最高的候选。
"""

from __future__ import annotations

import re

from src.chapters.cn2int import extract_number
from src.chapters.constants import (
    CHAPTER_RE,
    ESSAY_RE,
    EXTRA_RE,
    HUI_RE,
    LEVEL_UNITS,
    NAMED_ESSAY_RE,
    NAMED_PART_RE,
    NAMED_VOLUME_RE,
    PART_RE,
    SECTION_RE,
    SENTENCE_END_CHARS,
    TITLE_BREAK_CHARS,
    VOLUME_EN_RE,
    VOLUME_RE,
    ChapterConfig,
)
from src.chapters.models import ChapterCandidate, ChapterLevel

# 按优先级排列的层级正则：(层级, 正则, 标签组号, 编号组号, 内容组号)
_LEVEL_PATTERNS: list[tuple[ChapterLevel, re.Pattern[str], int, int | None, int]] = [
    (ChapterLevel.PART, PART_RE, 1, None, 2),
    (ChapterLevel.VOLUME, VOLUME_RE, 1, None, 2),
    (ChapterLevel.VOLUME, VOLUME_EN_RE, 1, None, 2),
    (ChapterLevel.ESSAY, ESSAY_RE, 1, None, 2),
    (ChapterLevel.HUI, HUI_RE, 1, None, 2),
    (ChapterLevel.CHAPTER, CHAPTER_RE, 1, None, 2),
    (ChapterLevel.SECTION, SECTION_RE, 1, None, 2),
    (ChapterLevel.EXTRA, EXTRA_RE, 1, 2, 3),
    # 纯名称卷（无编号，如"少年篇/风起卷/上部"）：放末尾兜底，
    # 保证"第一篇/特别篇"等仍优先命中编号正则或 EXTRA 层级
    (ChapterLevel.ESSAY, NAMED_ESSAY_RE, 1, None, 1),
    (ChapterLevel.VOLUME, NAMED_VOLUME_RE, 1, None, 1),
    (ChapterLevel.PART, NAMED_PART_RE, 1, None, 1),
]


def collect_candidates(
    text: str,
    skip_range: tuple[int, int] | None = None,
    config: ChapterConfig | None = None,
) -> list[ChapterCandidate]:
    """收集全部候选并按位置排序；skip_range 内的候选（目录页）不参与"""
    config = config or ChapterConfig()
    candidates: list[ChapterCandidate] = []

    for level, pattern, label_group, number_group, content_group in _LEVEL_PATTERNS:
        for match in pattern.finditer(text):
            start_char = match.start()
            if skip_range is not None and skip_range[0] <= start_char < skip_range[1]:
                continue
            line_end = text.find("\n", start_char)
            if line_end == -1:
                line_end = len(text)
            raw_line = text[start_char:line_end]
            label = match.group(label_group) or ""
            if number_group is not None:
                label += match.group(number_group) or ""
            content = match.group(content_group) or ""
            number = extract_number(label)

            candidates.append(
                ChapterCandidate(
                    level=level,
                    title=raw_line.strip(),
                    label=label,
                    display_title=_resolve_display_title(content, raw_line, start_char, line_end, config),
                    display_index_label=_build_display_index_label(level, number),
                    number=number,
                    start_char=start_char,
                    body_start_char=_fix_title_body_same_line(
                        raw_line,
                        content,
                        match.start(content_group) - start_char,
                        start_char,
                        line_end,
                        config,
                    ),
                )
            )

    return _deduplicate(sorted(candidates, key=lambda c: c.start_char))


def _build_display_index_label(level: ChapterLevel, number: int | None) -> str | None:
    """按层级与编号拼接展示序号（番外/彩蛋等无序号）"""
    unit = LEVEL_UNITS.get(level.value)
    if number is None or unit is None:
        return None
    return f"第{number}{unit}"


def _resolve_display_title(
    content: str,
    raw_line: str,
    start_char: int,
    line_end: int,
    config: ChapterConfig,
) -> str:
    """解析展示标题：标题正文同行时与正文起点截断保持一致"""
    _, display_title = _resolve_same_line_break(raw_line, content, 0, start_char, line_end, config)
    return display_title


def _fix_title_body_same_line(
    raw_line: str,
    content: str,
    content_offset: int,
    start_char: int,
    line_end: int,
    config: ChapterConfig,
) -> int:
    """标题正文同行修复：返回正文起点（绝对偏移）

    标题内容过长或含句末标点时，认为该行混入了正文，
    在第一个断点处截断标题，正文从断点后继续，避免丢正文。
    """
    body_start, _ = _resolve_same_line_break(raw_line, content, content_offset, start_char, line_end, config)
    return body_start


def _resolve_same_line_break(
    raw_line: str,
    content: str,
    content_offset: int,
    start_char: int,
    line_end: int,
    config: ChapterConfig,
) -> tuple[int, str]:
    """标题正文同行修复：返回 (正文起点绝对偏移, 截断后的展示标题)

    content_offset 为 content 在 raw_line 内的起始偏移（基于 match.span 计算，
    避免 content 恰为标题 label 子串时 find 定位到标题内部）。
    """
    display_title = content.strip()
    if not content:
        return line_end, display_title

    needs_fix = len(content) > config.max_reasonable_title_length or (
        len(content) > config.title_body_min_chars
        and any(ch in content for ch in SENTENCE_END_CHARS)
    )
    if not needs_fix:
        return line_end, display_title

    break_index = min(
        (content.find(ch) for ch in TITLE_BREAK_CHARS if ch in content),
        default=-1,
    )
    if break_index <= 0:
        return line_end, display_title

    truncated = content[:break_index].strip()
    if not truncated:
        return line_end, display_title

    body_start = start_char + content_offset + break_index + 1
    return body_start, truncated


def _deduplicate(candidates: list[ChapterCandidate]) -> list[ChapterCandidate]:
    """同一行命中多个层级时只保留优先级最高（扫描顺序靠前）的候选"""
    unique: list[ChapterCandidate] = []
    for candidate in candidates:
        if not unique or unique[-1].start_char != candidate.start_char:
            unique.append(candidate)
    return unique
