"""
诊断查询组装器。

创建时间: 2026-04-23
创建者: Codex
任务: p1-api-route-service-decouple
说明: 承载 diagnosis 相关查询组装逻辑。
"""

from __future__ import annotations

from src.api.models.responses import DiagnosisResult
from src.storage.repositories import StatsRepository

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
    alias_map: dict[str, str] | None = None,
) -> DiagnosisResult | None:
    """从数据库获取诊断结果。"""
    data = stats_repo.fetch_cloud_analysis(novel_id, run_id)
    if not data:
        return None

    arc_scores_raw = _parse_json_field(data.get("arc_scores"))
    arc_scores_normalized = _normalize_arc_scores(arc_scores_raw, alias_map)
    topic_labels_raw = _parse_json_field(data.get("topic_labels"))
    topic_labels_normalized = (
        _normalize_name_list(topic_labels_raw, alias_map) if isinstance(topic_labels_raw, list) else topic_labels_raw
    )

    protagonist_raw = data.get("protagonist")
    protagonist_normalized = _normalize_name(protagonist_raw, alias_map)

    main_characters_raw = _parse_json_field(data.get("main_characters"))
    main_characters_normalized = (
        _normalize_name_list(main_characters_raw, alias_map)
        if isinstance(main_characters_raw, list)
        else main_characters_raw
    )

    core_cast_raw = _parse_json_field(data.get("core_cast"))
    core_cast_normalized = (
        _normalize_name_list(core_cast_raw, alias_map) if isinstance(core_cast_raw, list) else core_cast_raw
    )

    return DiagnosisResult(
        foreshadow_rate=data.get("foreshadow_rate"),
        arc_scores=arc_scores_normalized,
        narrative_type=data.get("narrative_type"),
        topic_labels=topic_labels_normalized,
        diagnosis=_normalize_text_by_alias_map(data.get("diagnosis"), alias_map),
        value_logic_type=data.get("value_logic_type"),
        value_logic_reason=_normalize_text_by_alias_map(data.get("value_logic_reason"), alias_map),
        power_stance_score=_parse_int_field(data.get("power_stance_score")),
        power_stance_reason=_normalize_text_by_alias_map(data.get("power_stance_reason"), alias_map),
        common_people_dignity=_parse_int_field(data.get("common_people_dignity")),
        dignity_reason=_normalize_text_by_alias_map(data.get("dignity_reason"), alias_map),
        cultural_depth_score=data.get("cultural_depth_score"),
        cultural_depth_reason=_normalize_text_by_alias_map(data.get("cultural_depth_reason"), alias_map),
        narrative_arc_type=data.get("narrative_arc_type"),
        protagonist=protagonist_normalized,
        main_characters=main_characters_normalized,
        core_cast=core_cast_normalized,
        theme_color=(theme_color.strip() if (theme_color := data.get("theme_color")) else None),
    )
