"""
诊断查询组装器。

创建时间: 2026-04-23
创建者: Codex
任务: p1-api-route-service-decouple
说明: 承载 diagnosis 相关查询组装逻辑。
"""

from __future__ import annotations

from src.api.models.responses import DiagnosisResult
from src.storage.repositories import AnnotationRepository, StatsRepository

from .common import (
    _normalize_arc_scores,
    _normalize_name,
    _normalize_name_list,
    _normalize_text_by_alias_map,
    _parse_int_field,
    _parse_json_field,
)


def _fetch_diagnosis(
    run_id: str,
    novel_id: str,
    stats_repo: StatsRepository,
    annotation_repo: AnnotationRepository | None = None,
    alias_map: dict[str, str] | None = None,
) -> DiagnosisResult | None:
    """
    从数据库获取诊断结果。

    修改时间: 2026-04-26
    修改者: Codex
    任务: fix-diagnosis-followup-review-findings
    修改原因: `arc_scores` 对外契约已收口为命名字典；
    这里需要先拿到人物顺序，再把旧 run 的数组形态尽量还原成角色名映射。
    """
    data = stats_repo.fetch_cloud_analysis(novel_id, run_id)
    if not data:
        if annotation_repo is None:
            return None
        foreshadow_expectation = annotation_repo.calculate_foreshadow_expectation(run_id)
        if foreshadow_expectation is None:
            return None
        return DiagnosisResult(foreshadow_expectation=foreshadow_expectation)

    main_characters_raw = _parse_json_field(data.get("main_characters")) if data else None
    main_characters_normalized = (
        _normalize_name_list(main_characters_raw, alias_map)
        if isinstance(main_characters_raw, list)
        else main_characters_raw
    )

    core_cast_raw = _parse_json_field(data.get("core_cast")) if data else None
    core_cast_normalized = (
        _normalize_name_list(core_cast_raw, alias_map) if isinstance(core_cast_raw, list) else core_cast_raw
    )

    protagonist_raw = data.get("protagonist") if data else None
    protagonist_normalized = _normalize_name(protagonist_raw, alias_map)

    arc_scores_raw = _parse_json_field(data.get("arc_scores")) if data else None
    character_order_candidates = [
        main_characters_normalized if isinstance(main_characters_normalized, list) else None,
        core_cast_normalized if isinstance(core_cast_normalized, list) else None,
        [protagonist_normalized] if isinstance(protagonist_normalized, str) and protagonist_normalized else None,
    ]
    character_order = None
    if isinstance(arc_scores_raw, list):
        for candidate in character_order_candidates:
            if candidate and len(candidate) >= len(arc_scores_raw):
                character_order = candidate
                break
    else:
        for candidate in character_order_candidates:
            if candidate:
                character_order = candidate
                break
    arc_scores_normalized = _normalize_arc_scores(
        arc_scores_raw,
        alias_map,
        character_order=character_order,
    )

    topic_labels_raw = _parse_json_field(data.get("topic_labels")) if data else None
    topic_labels_normalized = (
        _normalize_name_list(topic_labels_raw, alias_map) if isinstance(topic_labels_raw, list) else topic_labels_raw
    )

    return DiagnosisResult(
        foreshadow_expectation=data.get("foreshadow_expectation") if data else None,
        arc_scores=arc_scores_normalized,
        narrative_type=data.get("narrative_type") if data else None,
        topic_labels=topic_labels_normalized,
        diagnosis=_normalize_text_by_alias_map(data.get("diagnosis") if data else None, alias_map),
        value_logic_type=data.get("value_logic_type") if data else None,
        value_logic_reason=_normalize_text_by_alias_map(data.get("value_logic_reason") if data else None, alias_map),
        power_stance_score=_parse_int_field(data.get("power_stance_score") if data else None),
        power_stance_reason=_normalize_text_by_alias_map(data.get("power_stance_reason") if data else None, alias_map),
        common_people_dignity=_parse_int_field(data.get("common_people_dignity") if data else None),
        dignity_reason=_normalize_text_by_alias_map(data.get("dignity_reason") if data else None, alias_map),
        cultural_depth_score=data.get("cultural_depth_score") if data else None,
        cultural_depth_reason=_normalize_text_by_alias_map(
            data.get("cultural_depth_reason") if data else None,
            alias_map,
        ),
        narrative_arc_type=data.get("narrative_arc_type") if data else None,
        protagonist=protagonist_normalized,
        main_characters=main_characters_normalized,
        core_cast=core_cast_normalized,
        theme_color=(theme_color.strip() if (data and (theme_color := data.get("theme_color"))) else None),
    )
