"""
诊断查询组装器

说明: 承载 diagnosis 相关查询组装逻辑
"""

from __future__ import annotations

from typing import Literal

from loguru import logger

from src.api.models.responses import DiagnosisResult
from src.models.cloud.schema import GENRE_LABEL_VALUES, STYLE_LABEL_VALUES
from src.models.local.character_reference_policy import filter_global_character_names
from src.storage.repositories import StatsRepository

from .common import (
    _normalize_arc_scores,
    _normalize_name_list,
    _parse_int_field,
    _parse_json_field,
)


def _filter_character_list_against_arc_scores(
    values: list[str] | None,
    arc_scores: dict[str, float] | None,
) -> list[str] | None:
    """
    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: 过滤 arc_scores 时先排除未解析代词，避免旧 diagnosis 把局部引用当成焦点角色。

    说明: 结果读取层按 `arc_scores` 收口焦点人物、主要人物和核心角色，
    避免诊断名单继续携带不属于当前角色合同的名称
    """
    if values is None:
        return None
    if not arc_scores:
        return []
    valid_names = set(arc_scores.keys())
    return [name for name in filter_global_character_names(values) if name in valid_names]


def _filter_global_arc_scores(arc_scores: dict[str, float] | None) -> dict[str, float] | None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: diagnosis 读取层的 arc_scores 是角色合同源头，必须先剔除“我”等未解析局部引用。
    """
    if not arc_scores:
        return None
    filtered = {name: score for name, score in arc_scores.items() if filter_global_character_names([name])}
    return filtered or None


def _derive_focus_structure_from_characters(
    focus_characters: list[str] | None,
) -> Literal["single", "dual", "ensemble"] | None:
    """
    说明: 角色名单过滤后必须重新推导 focus_structure，
    避免把 `dual` 与单人列表这样的矛盾合同继续对外暴露
    """
    if not focus_characters:
        return None
    focus_count = len(focus_characters)
    if focus_count == 1:
        return "single"
    if focus_count == 2:
        return "dual"
    return "ensemble"


def _normalize_controlled_label_list(
    values: list[str] | None,
    *,
    allowed_values: tuple[str, ...],
) -> list[str] | None:
    """
    修改时间: 2026-04-29
    任务: split-genre-style-labels-review-fixes
    修改原因: diagnosis 读取层必须和 CloudAnalysisSchema 的受控标签合同保持一致；
              非法标签、超上限标签或全空白标签都应直接视为无效 diagnosis，而不是继续对外暴露。
    """
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


def _has_diagnosis_result(diagnosis: DiagnosisResult | None) -> bool:
    """2026-08-19 判断当前 run 是否存在诊断记录，不对字段完整性做版本门控"""
    return diagnosis is not None


def _fetch_diagnosis(
    run_id: str,
    novel_id: str,
    stats_repo: StatsRepository,
) -> DiagnosisResult | None:
    """
    从数据库获取诊断结果
    """
    data = stats_repo.fetch_cloud_analysis(novel_id, run_id)
    if not data:
        return None

    focus_characters_raw = _parse_json_field(data.get("focus_characters")) if data else None
    focus_characters_normalized = (
        _normalize_name_list(focus_characters_raw)
        if isinstance(focus_characters_raw, list)
        else focus_characters_raw
    )

    main_characters_raw = _parse_json_field(data.get("main_characters")) if data else None
    main_characters_normalized = (
        _normalize_name_list(main_characters_raw)
        if isinstance(main_characters_raw, list)
        else main_characters_raw
    )

    core_cast_raw = _parse_json_field(data.get("core_cast")) if data else None
    core_cast_normalized = (
        _normalize_name_list(core_cast_raw) if isinstance(core_cast_raw, list) else core_cast_raw
    )

    arc_scores_raw = _parse_json_field(data.get("arc_scores")) if data else None
    arc_scores_normalized = _filter_global_arc_scores(_normalize_arc_scores(arc_scores_raw))

    topic_labels_raw = _parse_json_field(data.get("topic_labels")) if data else None
    topic_labels_normalized = (
        _normalize_name_list(topic_labels_raw) if isinstance(topic_labels_raw, list) else topic_labels_raw
    )
    genre_labels_raw = _parse_json_field(data.get("genre_labels")) if data else None
    style_labels_raw = _parse_json_field(data.get("style_labels")) if data else None
    genre_labels_normalized = (
        _normalize_controlled_label_list(genre_labels_raw, allowed_values=GENRE_LABEL_VALUES)
        if isinstance(genre_labels_raw, list)
        else None
    )
    style_labels_normalized = (
        _normalize_controlled_label_list(style_labels_raw, allowed_values=STYLE_LABEL_VALUES)
        if isinstance(style_labels_raw, list)
        else None
    )
    focus_structure_raw = data.get("focus_structure") if data else None
    focus_structure: Literal["single", "dual", "ensemble"] | None
    if focus_structure_raw in {"single", "dual", "ensemble"}:
        focus_structure = focus_structure_raw
    else:
        focus_structure = None

    focus_characters_filtered = _filter_character_list_against_arc_scores(
        focus_characters_normalized if isinstance(focus_characters_normalized, list) else None,
        arc_scores_normalized,
    )
    main_characters_filtered = _filter_character_list_against_arc_scores(
        main_characters_normalized if isinstance(main_characters_normalized, list) else None,
        arc_scores_normalized,
    )
    core_cast_filtered = _filter_character_list_against_arc_scores(
        core_cast_normalized if isinstance(core_cast_normalized, list) else None,
        arc_scores_normalized,
    )
    normalized_focus_structure = _derive_focus_structure_from_characters(focus_characters_filtered)
    if focus_structure != normalized_focus_structure:
        logger.warning(
            "diagnosis focus contract changed after graph-name validation: run_id={} novel_id={} raw_structure={} "
            "normalized_structure={} raw_focus_characters={} normalized_focus_characters={}",
            run_id,
            novel_id,
            focus_structure,
            normalized_focus_structure,
            focus_characters_normalized,
            focus_characters_filtered,
        )

    return DiagnosisResult(
        foreshadow_expectation=data.get("foreshadow_expectation") if data else None,
        arc_scores=arc_scores_normalized,
        genre_labels=genre_labels_normalized,
        style_labels=style_labels_normalized,
        topic_labels=topic_labels_normalized,
        diagnosis=data.get("diagnosis") if data else None,
        value_logic_type=data.get("value_logic_type") if data else None,
        value_logic_reason=data.get("value_logic_reason") if data else None,
        power_stance_score=_parse_int_field(data.get("power_stance_score") if data else None),
        power_stance_reason=data.get("power_stance_reason") if data else None,
        common_people_dignity=_parse_int_field(data.get("common_people_dignity") if data else None),
        dignity_reason=data.get("dignity_reason") if data else None,
        cultural_depth_score=data.get("cultural_depth_score") if data else None,
        cultural_depth_reason=data.get("cultural_depth_reason") if data else None,
        narrative_arc_type=(
            narrative_arc_type_value.strip()
            if data
            and isinstance((narrative_arc_type_value := data.get("narrative_arc_type")), str)
            and narrative_arc_type_value.strip()
            else None
        ),
        focus_structure=normalized_focus_structure,
        focus_characters=focus_characters_filtered,
        main_characters=main_characters_filtered,
        core_cast=core_cast_filtered,
        theme_color=(theme_color.strip() if (data and (theme_color := data.get("theme_color"))) else None),
    )
