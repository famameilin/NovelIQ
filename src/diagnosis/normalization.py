"""所属领域的字段契约与结果处理"""

from __future__ import annotations

from typing import Any, Literal

from src.fact_graph.character_reference_policy import filter_global_character_names


def normalize_name_list(values: list[str] | None) -> list[str] | None:
    """清理名称列表中的重复项并保持原有顺序"""
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


def normalize_arc_scores(arc_scores: Any) -> dict[str, float] | None:
    """把诊断角色弧评分收口为命名浮点字典"""
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


def filter_character_list_against_arc_scores(
    values: list[str] | None,
    arc_scores: dict[str, float] | None,
) -> list[str] | None:
    """按有效角色弧线分数过滤全局角色名单"""
    if values is None:
        return None
    if not arc_scores:
        return []
    valid_names = set(arc_scores.keys())
    return [name for name in filter_global_character_names(values) if name in valid_names]


def filter_global_arc_scores(arc_scores: dict[str, float] | None) -> dict[str, float] | None:
    """过滤未解析局部引用的角色弧线分数"""
    if not arc_scores:
        return None
    filtered = {name: score for name, score in arc_scores.items() if filter_global_character_names([name])}
    return filtered or None


def derive_focus_structure_from_characters(
    focus_characters: list[str] | None,
) -> Literal["single", "dual", "ensemble"] | None:
    """角色名单过滤后必须重新推导 focus_structure，避免 `dual` 与单人列表这样的矛盾合同对外暴露"""
    if not focus_characters:
        return None
    focus_count = len(focus_characters)
    if focus_count == 1:
        return "single"
    if focus_count == 2:
        return "dual"
    return "ensemble"


def normalize_controlled_label_list(
    values: list[str] | None,
    *,
    allowed_values: tuple[str, ...],
) -> list[str] | None:
    """规范化受控标签，非法或超过上限时返回空值"""
    if values is None:
        return None

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            return None
        label = value.strip()
        if not label or label in seen:
            continue
        if label not in allowed_values:
            return None
        seen.add(label)
        normalized.append(label)

    if len(normalized) > 3:
        return None
    return normalized


def normalize_topic_labels(values: object) -> dict[str, str] | None:
    """只读取按实际 topic_id 键控的诊断标签"""
    if not isinstance(values, dict):
        return None
    normalized: dict[str, str] = {}
    for raw_id, raw_label in values.items():
        if not isinstance(raw_id, str) or not raw_id.isascii() or not raw_id.isdecimal():
            return None
        if not isinstance(raw_label, str) or not raw_label.strip():
            return None
        normalized[str(int(raw_id))] = raw_label.strip()
    return normalized
