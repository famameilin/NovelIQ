"""
名称归一化工具

说明: 从 results_fetchers.py 拆分，包含名称归一化相关函数
"""

from __future__ import annotations

import re

from src.config.constants import (
    ALLOWED_PREV_CJK_CHARS,
    LIKELY_NAME_PREFIX_CHARS,
    TITLE_ALIAS_SUFFIXES,
)


def _normalize_name(name: str | None, alias_map: dict[str, str] | None) -> str | None:
    """
    别名归一化函数

    如果提供了 alias_map 且 name 存在于映射中，则返回规范名；
    否则返回原始名称

    Args:
        name: 待归一化的名称
        alias_map: 别名到规范名的映射字典

    Returns:
        归一化后的名称
    """
    if name is None:
        return None
    if alias_map and name in alias_map:
        return alias_map[name]
    return name


def _normalize_name_list(values: list[str] | None, alias_map: dict[str, str] | None) -> list[str] | None:
    """
    对名称列表应用别名归一化并去重，保持原有顺序

    Args:
        values: 待归一化的名称列表
        alias_map: 别名到规范名的映射字典

    Returns:
        归一化并去重后的名称列表
    """
    if not values:
        return values

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized_value = alias_map.get(value, value) if alias_map else value
        if normalized_value in seen:
            continue
        seen.add(normalized_value)
        normalized.append(normalized_value)

    return normalized


def _normalize_text_by_alias_map(text: str | None, alias_map: dict[str, str] | None) -> str | None:
    """
    对自由文本中的人物别名做谨慎归一化

    说明:
        仅对 alias_map 中 alias != canonical 的条目做精确替换，
        并按别名长度倒序处理，尽量避免较短别名误伤较长名称
    """
    if not text or not alias_map:
        return text

    replacements = sorted(
        ((alias, canonical) for alias, canonical in alias_map.items() if alias and canonical and alias != canonical),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    if not replacements:
        return text

    protected_ranges: list[tuple[int, int]] = []
    accepted_matches: list[tuple[int, int, str]] = []
    text_length = len(text)

    def _range_overlaps(start: int, end: int) -> bool:
        return any(start < existing_end and end > existing_start for existing_start, existing_end in protected_ranges)

    def _is_ascii_alias(value: str) -> bool:
        return bool(re.search(r"[A-Za-z0-9_]", value))

    def _is_cjk_char(char: str) -> bool:
        return bool(char) and bool(re.match(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", char))

    def _is_ascii_word_char(char: str) -> bool:
        return bool(char) and bool(re.match(r"[A-Za-z0-9_]", char))

    def _looks_like_title_alias(value: str) -> bool:
        return any(value.endswith(suffix) for suffix in TITLE_ALIAS_SUFFIXES)

    def _is_safe_match(value: str, start: int, end: int) -> bool:
        prev_char = text[start - 1] if start > 0 else ""
        next_char = text[end] if end < text_length else ""
        left_boundary = not prev_char or (not _is_cjk_char(prev_char) and not _is_ascii_word_char(prev_char))
        right_boundary = not next_char or (not _is_cjk_char(next_char) and not _is_ascii_word_char(next_char))

        if _is_ascii_alias(value):
            return left_boundary and right_boundary

        if _looks_like_title_alias(value):
            if left_boundary or right_boundary:
                return True
            return prev_char in ALLOWED_PREV_CJK_CHARS

        if len(value) <= 2 and prev_char in LIKELY_NAME_PREFIX_CHARS:
            return False

        return True

    for alias, canonical in replacements:
        search_start = 0
        while True:
            match_start = text.find(alias, search_start)
            if match_start < 0:
                break
            match_end = match_start + len(alias)
            if not _range_overlaps(match_start, match_end) and _is_safe_match(alias, match_start, match_end):
                accepted_matches.append((match_start, match_end, canonical))
                protected_ranges.append((match_start, match_end))
            search_start = match_start + 1

    if not accepted_matches:
        return text

    segments: list[str] = []
    cursor = 0
    accepted_matches.sort(key=lambda item: item[0])
    for match_start, match_end, canonical in accepted_matches:
        if cursor < match_start:
            segments.append(text[cursor:match_start])
        segments.append(canonical)
        cursor = match_end
    if cursor < text_length:
        segments.append(text[cursor:])
    return "".join(segments)
