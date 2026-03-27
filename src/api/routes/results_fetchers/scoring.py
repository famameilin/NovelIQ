"""
评分计算函数

创建时间: 2026-03-28
创建者: TraeAI
任务: consolidate-codebase-architecture
说明: 从 results_fetchers.py 拆分，包含评分计算相关函数
"""

from __future__ import annotations

from typing import Any

from src.api.models.responses import CharacterStats


def _calculate_protagonist_scores(
    characters: list[CharacterStats],
    arc_scores: dict[str, float],
    main_characters: list[str],
) -> list[CharacterStats]:
    """
    计算主角评分并判定是否为主角

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: protagonist-score-fusion
    说明: 四维度融合计算 protagonist_score，并判定 is_protagonist

    Args:
        characters: 角色统计列表（已按出场次数排序）
        arc_scores: 角色弧线评分字典 {name: score}
        main_characters: 主要角色名称列表

    Returns:
        更新了 protagonist_score 和 is_protagonist 的角色列表
    """
    if not characters:
        return characters

    max_appearance = max(c.appearance_count for c in characters)
    max_arc_score = max(arc_scores.values()) if arc_scores else 0.0

    for char in characters:
        appearance_norm = char.appearance_count / max_appearance if max_appearance > 0 else 0.0

        subject_count = char.role_function_distribution.get("主体", 0)
        subject_ratio = subject_count / char.appearance_count if char.appearance_count > 0 else 0.0

        arc_score = arc_scores.get(char.name, 0.0)
        arc_norm = arc_score / max_arc_score if max_arc_score > 0 else 0.0

        in_main_cast = 1.0 if char.name in main_characters else 0.0

        protagonist_score = (
            0.25 * appearance_norm
            + 0.25 * subject_ratio
            + 0.25 * arc_norm
            + 0.25 * in_main_cast
        )

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


def _normalize_arc_scores(arc_scores: Any, alias_map: dict[str, str] | None) -> dict[str, float] | list[float]:
    """
    对 arc_scores 的人物名称进行归一化

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: fix-arc-scores-alias-inconsistency
    说明: 将 arc_scores 中的人物绰号替换为规范名，保持与角色表一致

    Args:
        arc_scores: 原始 arc_scores 数据，可能是 dict 或 list
        alias_map: 别名到规范名的映射字典

    Returns:
        归一化后的 arc_scores
    """
    if not arc_scores:
        return arc_scores

    if isinstance(arc_scores, list):
        return arc_scores

    if not isinstance(arc_scores, dict):
        return arc_scores

    if not alias_map:
        return arc_scores

    normalized: dict[str, float] = {}
    for name, score in arc_scores.items():
        if not isinstance(name, str):
            continue
        try:
            normalized_score = float(score)
        except (TypeError, ValueError):
            continue
        canonical_name = alias_map.get(name, name)
        previous = normalized.get(canonical_name)
        normalized[canonical_name] = normalized_score if previous is None else max(previous, normalized_score)

    return normalized
