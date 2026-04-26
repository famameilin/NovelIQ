"""
结果查询共享工具。

创建时间: 2026-04-23
创建者: Codex
任务: p1-api-route-service-decouple
说明: 承载 route/service 共享的解析、归一化与评分工具，避免 service 反向依赖 route。
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.api.models.responses import CharacterStats
from src.config.constants import (
    ALLOWED_PREV_CJK_CHARS,
    LIKELY_NAME_PREFIX_CHARS,
    TITLE_ALIAS_SUFFIXES,
)


def _parse_json_field(value: Any) -> Any:
    """解析 JSON 字段，处理可能的异常。"""
    if value is None:
        return None
    if isinstance(value, dict | list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def _parse_int_field(value: Any) -> int | None:
    """解析整数字段，处理可能的异常。"""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _normalize_name(name: str | None, alias_map: dict[str, str] | None) -> str | None:
    """对单个人名应用别名归一化。"""
    if name is None:
        return None
    if alias_map and name in alias_map:
        return alias_map[name]
    return name


def _normalize_name_list(values: list[str] | None, alias_map: dict[str, str] | None) -> list[str] | None:
    """对名称列表应用别名归一化并去重，保持原有顺序。"""
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
    """对自由文本中的人物别名做谨慎归一化。"""
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


def _calculate_protagonist_scores(
    characters: list[CharacterStats],
    arc_scores: dict[str, float],
    main_characters: list[str],
) -> list[CharacterStats]:
    """计算主角评分并判定是否为主角。"""
    if not characters:
        return characters

    max_appearance = max(c.appearance_count for c in characters)

    for char in characters:
        appearance_norm = char.appearance_count / max_appearance if max_appearance > 0 else 0.0
        subject_count = char.role_function_distribution.get("主体", 0)
        subject_ratio = subject_count / char.appearance_count if char.appearance_count > 0 else 0.0
        arc_score = arc_scores.get(char.name, 0.0)
        arc_norm = arc_score / 10.0 if arc_score > 0 else 0.0
        in_main_cast = 1.0 if char.name in main_characters else 0.0
        protagonist_score = 0.25 * appearance_norm + 0.25 * subject_ratio + 0.25 * arc_norm + 0.25 * in_main_cast
        char.protagonist_score = round(protagonist_score, 4)

    top_character = max(
        characters,
        key=lambda item: (
            item.protagonist_score if item.protagonist_score is not None else float("-inf"),
            item.appearance_count,
        ),
    )
    top_score = top_character.protagonist_score

    for char in characters:
        char.is_protagonist = False

    if top_score is not None and top_score >= 0.6:
        top_character.is_protagonist = True

    return characters


def _normalize_arc_scores(
    arc_scores: Any,
    alias_map: dict[str, str] | None,
    *,
    character_order: list[str] | None = None,
) -> dict[str, float] | None:
    """
    对 arc_scores 的人物名称进行归一化，并收口为命名字典。

    修改时间: 2026-04-26
    修改者: Codex
    任务: fix-diagnosis-followup-review-findings
    修改原因: 结果 API 与前端页面都按“角色名 -> 分数”消费 arc_scores；
    旧 run 若仍存数组形态，这里要优先按人物顺序还原成命名字典，
    无法可靠还原时返回 None，避免把 `0/1/2` 这种索引误当成角色名对外暴露。
    """
    if not arc_scores:
        return None

    normalized: dict[str, float] = {}

    if isinstance(arc_scores, list):
        if not character_order:
            return None
        source_items = zip(character_order, arc_scores, strict=False)
    elif isinstance(arc_scores, dict):
        source_items = arc_scores.items()
    else:
        return None

    for raw_name, score in source_items:
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        try:
            normalized_score = float(score)
        except (TypeError, ValueError):
            continue

        canonical_name = alias_map.get(raw_name, raw_name) if alias_map else raw_name
        previous = normalized.get(canonical_name)
        normalized[canonical_name] = normalized_score if previous is None else max(previous, normalized_score)

    return normalized or None
