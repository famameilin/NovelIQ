"""
结果查询共享工具

说明: 承载 route/service 共享的解析、归一化与评分工具，避免 service 反向依赖 route
"""

from __future__ import annotations

import json
from typing import Any

from src.api.models.responses import CharacterStats


def _parse_json_field(value: Any) -> Any:
    """解析 JSON 字段，处理可能的异常"""
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
    """解析整数字段，处理可能的异常"""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _normalize_name_list(values: list[str] | None) -> list[str] | None:
    """2026-08-06 用于清理名称列表中的重复项并保持原有顺序"""
    if not values:
        return values

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)

    return normalized


def _calculate_narrative_focus_scores(
    characters: list[CharacterStats],
    arc_scores: dict[str, float],
    focus_characters: list[str],
    main_characters: list[str],
) -> list[CharacterStats]:
    if not characters:
        return characters

    max_appearance = max(c.appearance_count for c in characters)
    focus_character_set = set(focus_characters)

    for char in characters:
        appearance_norm = char.appearance_count / max_appearance if max_appearance > 0 else 0.0
        subject_count = char.role_function_distribution.get("主体", 0)
        subject_ratio = subject_count / char.appearance_count if char.appearance_count > 0 else 0.0
        arc_score = arc_scores.get(char.name, 0.0)
        arc_norm = arc_score / 10.0 if arc_score > 0 else 0.0
        in_main_cast = 1.0 if char.name in main_characters else 0.0
        narrative_focus_score = 0.25 * appearance_norm + 0.25 * subject_ratio + 0.25 * arc_norm + 0.25 * in_main_cast
        char.narrative_focus_score = round(narrative_focus_score, 4)
        char.is_focus_character = char.name in focus_character_set

    return characters


def _normalize_arc_scores(
    arc_scores: Any,
) -> dict[str, float] | None:
    """2026-08-06 用于把诊断角色弧评分收口为命名浮点字典"""
    if not arc_scores:
        return None

    if not isinstance(arc_scores, dict):
        return None
    normalized: dict[str, float] = {}

    for raw_name, score in arc_scores.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        try:
            normalized_score = float(score)
        except (TypeError, ValueError):
            continue

        normalized[raw_name] = normalized_score

    return normalized or None
