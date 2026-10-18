"""诊断结果查询及归一化；返回领域读模型

2026-10-16 全库 3NF 改造（35 表冻结结构）：读侧从 diagnosis_reports 报告头及
analysis_assessments 的标签/名单/评分条目重组，novel_id 从运行取，
foreshadow_expectation 从正式伏笔链与阶段声明绑定投影；对 API 的中文字段语义、
空值与顺序保持与旧 payload 一致。
"""

from __future__ import annotations

from typing import Any, Literal

from loguru import logger

from src.diagnosis.normalization import (
    derive_focus_structure_from_characters,
    filter_character_list_against_arc_scores,
    filter_global_arc_scores,
    normalize_arc_scores,
    normalize_controlled_label_list,
    normalize_name_list,
    normalize_topic_labels,
)
from src.diagnosis.read_models import DiagnosisReadResult
from src.diagnosis.vocabulary import GENRE_LABEL_VALUES, STYLE_LABEL_VALUES
from src.storage import Storage
from src.utils.parsing import parse_int_field, parse_json_field


def _declaration_bindings(session: Storage, run_id: str) -> dict[str, str]:
    """正式声明绑定：阶段版本绑定声明，完整事件→声明，供伏笔预期沿绑定取事件身份"""
    return {
        str(_stored_row_1.declaration_id): str(_stored_row_1.event_id)
        for _stored_row_1 in session.reads.final_diagnosis_read_declaration_bindings_1(run_id)
    }


def fetch_diagnosis_payload(session: Storage, run_id: str) -> dict[str, Any] | None:
    """正式诊断报告的扁平投影；无报告返回 None（与旧产物读取语义一致）"""
    report = session.reads.diagnosis_read_fetch_diagnosis_payload_2(run_id)
    if report is None:
        return None
    report_id = report.report_id

    def _labels(column: Any) -> list[str]:
        return list(session.reads.diagnosis_read_labels_1(column, report_id))

    def _members(cast_role: str) -> list[str]:
        return list(session.reads.diagnosis_read_members_1(cast_role, report_id))

    topic_labels = {
        str(row.topic_id): row.topic_label for row in session.reads.diagnosis_read_fetch_diagnosis_payload_3(report_id)
    }
    arc_scores = {
        str(_stored_row_2.canonical_name): float(_stored_row_2.character_score)
        for _stored_row_2 in session.reads.diagnosis_read_fetch_diagnosis_payload_4(report_id)
    }
    from src.event_trees.read.foreshadowing import calculate_foreshadow_expectation

    payload: dict[str, Any] = {
        "run_id": run_id,
        "novel_id": session.reads.diagnosis_read_fetch_diagnosis_payload_1(run_id),
        "foreshadow_expectation": calculate_foreshadow_expectation(
            session, run_id, declaration_bindings=_declaration_bindings(session, run_id)
        ),
        "arc_scores": arc_scores,
        "genre_labels": _labels("genre_label"),
        "style_labels": _labels("style_label"),
        "topic_labels": topic_labels,
        "diagnosis": report.diagnosis,
        "value_logic_type": report.value_logic_type,
        "value_logic_reason": report.value_logic_reason,
        "power_stance_score": report.power_stance_score,
        "power_stance_reason": report.power_stance_reason,
        "common_people_dignity": report.common_people_dignity,
        "dignity_reason": report.dignity_reason,
        "cultural_depth_score": report.cultural_depth_score,
        "cultural_depth_reason": report.cultural_depth_reason,
        "narrative_arc_type": report.narrative_arc_type,
        "focus_structure": report.focus_structure,
        "focus_characters": _members("focus"),
        "main_characters": _members("main"),
        "core_cast": _members("core"),
        "theme_color": report.theme_color,
    }
    return payload


def query_diagnosis(run_id: str, novel_id: str, session: Storage) -> DiagnosisReadResult | None:
    """
    从数据库获取诊断结果
    """
    data = fetch_diagnosis_payload(session, run_id)
    if not data:
        return None
    global_stats = session.statistics.fetch_global_stats_dict(run_id)
    focus_characters_raw = parse_json_field(data.get("focus_characters")) if data else None
    focus_characters_normalized = (
        normalize_name_list(focus_characters_raw) if isinstance(focus_characters_raw, list) else focus_characters_raw
    )
    main_characters_raw = parse_json_field(data.get("main_characters")) if data else None
    main_characters_normalized = (
        normalize_name_list(main_characters_raw) if isinstance(main_characters_raw, list) else main_characters_raw
    )
    core_cast_raw = parse_json_field(data.get("core_cast")) if data else None
    core_cast_normalized = normalize_name_list(core_cast_raw) if isinstance(core_cast_raw, list) else core_cast_raw
    arc_scores_raw = parse_json_field(data.get("arc_scores")) if data else None
    arc_scores_normalized = filter_global_arc_scores(normalize_arc_scores(arc_scores_raw))
    topic_labels_raw = parse_json_field(data.get("topic_labels")) if data else None
    topic_labels_normalized = normalize_topic_labels(topic_labels_raw)
    genre_labels_raw = parse_json_field(data.get("genre_labels")) if data else None
    style_labels_raw = parse_json_field(data.get("style_labels")) if data else None
    genre_labels_normalized = (
        normalize_controlled_label_list(genre_labels_raw, allowed_values=GENRE_LABEL_VALUES)
        if isinstance(genre_labels_raw, list)
        else None
    )
    style_labels_normalized = (
        normalize_controlled_label_list(style_labels_raw, allowed_values=STYLE_LABEL_VALUES)
        if isinstance(style_labels_raw, list)
        else None
    )
    focus_structure_raw = data.get("focus_structure") if data else None
    focus_structure: Literal["single", "dual", "ensemble"] | None
    if focus_structure_raw in {"single", "dual", "ensemble"}:
        focus_structure = focus_structure_raw
    else:
        focus_structure = None
    focus_characters_filtered = filter_character_list_against_arc_scores(
        focus_characters_normalized if isinstance(focus_characters_normalized, list) else None, arc_scores_normalized
    )
    main_characters_filtered = filter_character_list_against_arc_scores(
        main_characters_normalized if isinstance(main_characters_normalized, list) else None, arc_scores_normalized
    )
    core_cast_filtered = filter_character_list_against_arc_scores(
        core_cast_normalized if isinstance(core_cast_normalized, list) else None, arc_scores_normalized
    )
    normalized_focus_structure = derive_focus_structure_from_characters(focus_characters_filtered)
    if focus_structure != normalized_focus_structure:
        logger.warning(
            (
                "diagnosis focus contract changed after graph-name validation: run_id={} nove"
                "l_id={} raw_structure={} normalized_structure={} raw_focus_characters={} nor"
                "malized_focus_characters={}"
            ),
            run_id,
            novel_id,
            focus_structure,
            normalized_focus_structure,
            focus_characters_normalized,
            focus_characters_filtered,
        )
    return DiagnosisReadResult(
        foreshadow_expectation=data.get("foreshadow_expectation") if data else None,
        arc_scores=arc_scores_normalized,
        genre_labels=genre_labels_normalized,
        style_labels=style_labels_normalized,
        topic_labels=topic_labels_normalized,
        emotion_avg=global_stats.get("emotion_avg"),
        lexicon_zero_hit_share=global_stats.get("lexicon_zero_hit_share"),
        diagnosis=data.get("diagnosis") if data else None,
        value_logic_type=data.get("value_logic_type") if data else None,
        value_logic_reason=data.get("value_logic_reason") if data else None,
        power_stance_score=parse_int_field(data.get("power_stance_score") if data else None),
        power_stance_reason=data.get("power_stance_reason") if data else None,
        common_people_dignity=parse_int_field(data.get("common_people_dignity") if data else None),
        dignity_reason=data.get("dignity_reason") if data else None,
        cultural_depth_score=data.get("cultural_depth_score") if data else None,
        cultural_depth_reason=data.get("cultural_depth_reason") if data else None,
        narrative_arc_type=narrative_arc_type_value.strip()
        if data
        and isinstance((narrative_arc_type_value := data.get("narrative_arc_type")), str)
        and narrative_arc_type_value.strip()
        else None,
        focus_structure=normalized_focus_structure,
        focus_characters=focus_characters_filtered,
        main_characters=main_characters_filtered,
        core_cast=core_cast_filtered,
        theme_color=theme_color.strip() if data and (theme_color := data.get("theme_color")) else None,
    )
