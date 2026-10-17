"""诊断结果查询及归一化；返回领域读模型

2026-10-16 全库 3NF 改造（35 表冻结结构）：读侧从 diagnosis_reports 报告头及
analysis_assessments 的标签/名单/评分条目重组，novel_id 从运行取，
foreshadow_expectation 从正式伏笔链与阶段声明绑定投影；对 API 的中文字段语义、
空值与顺序保持与旧 payload 一致。
"""

from __future__ import annotations

from typing import Any, Literal

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

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
from src.event_trees.storage_map import run_execution_ids
from src.utils.parsing import parse_int_field, parse_json_field


def _declaration_bindings(session: Session, run_id: str) -> dict[str, str]:
    """正式声明绑定：阶段版本绑定声明，完整事件→声明，供伏笔预期沿绑定取事件身份"""
    from src.storage.models import CompleteEvent, EventRevision

    stmt = (
        select(EventRevision.declaration_id, EventRevision.event_id)
        .join(CompleteEvent, CompleteEvent.event_id == EventRevision.event_id)
        .where(
            EventRevision.declaration_id.is_not(None),
            CompleteEvent.producer_execution_id.in_(run_execution_ids(run_id)),
        )
    )
    return {str(declaration_id): str(event_id) for declaration_id, event_id in session.execute(stmt)}


def fetch_diagnosis_payload(session: Session, run_id: str) -> dict[str, Any] | None:
    """正式诊断报告的扁平投影；无报告返回 None（与旧产物读取语义一致）"""
    from src.storage.models import (
        AnalysisAssessment,
        AnalysisRun,
        DiagnosisReport,
        Execution,
        GraphEntity,
    )

    report = session.scalars(
        select(DiagnosisReport)
        .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
        .where(Execution.session_run_id == run_id)
        .order_by(DiagnosisReport.created_at.desc(), DiagnosisReport.report_id.desc())
        .limit(1)
    ).first()
    if report is None:
        return None
    report_id = report.report_id

    def _labels(column: Any) -> list[str]:
        return list(
            session.scalars(
                select(column)
                .where(AnalysisAssessment.report_id == report_id, column.is_not(None))
                .order_by(AnalysisAssessment.ordinal)
            )
        )

    def _members(cast_role: str) -> list[str]:
        stmt = (
            select(GraphEntity.canonical_name)
            .join(AnalysisAssessment, AnalysisAssessment.cast_entity_id == GraphEntity.entity_id)
            .where(
                AnalysisAssessment.report_id == report_id,
                AnalysisAssessment.cast_role == cast_role,
            )
            .order_by(AnalysisAssessment.ordinal)
        )
        return list(session.scalars(stmt))

    topic_labels = {
        str(row.topic_id): row.topic_label
        for row in session.scalars(
            select(AnalysisAssessment)
            .where(AnalysisAssessment.report_id == report_id, AnalysisAssessment.topic_label.is_not(None))
            .order_by(AnalysisAssessment.topic_id)
        )
    }
    arc_scores = {
        str(name): float(score)
        for name, score in session.execute(
            select(GraphEntity.canonical_name, AnalysisAssessment.character_score)
            .join(AnalysisAssessment, AnalysisAssessment.scored_entity_id == GraphEntity.entity_id)
            .where(
                AnalysisAssessment.report_id == report_id,
                AnalysisAssessment.character_score.is_not(None),
            )
        )
    }
    from src.event_trees.read.foreshadowing import calculate_foreshadow_expectation

    payload: dict[str, Any] = {
        "run_id": run_id,
        "novel_id": session.scalar(select(AnalysisRun.novel_id).where(AnalysisRun.run_id == run_id)),
        "foreshadow_expectation": calculate_foreshadow_expectation(
            session, run_id, declaration_bindings=_declaration_bindings(session, run_id)
        ),
        "arc_scores": arc_scores,
        "genre_labels": _labels(AnalysisAssessment.genre_label),
        "style_labels": _labels(AnalysisAssessment.style_label),
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


def query_diagnosis(
    run_id: str,
    novel_id: str,
    stats_repo: Any,
) -> DiagnosisReadResult | None:
    """
    从数据库获取诊断结果
    """
    session: Session = stats_repo.session
    data = fetch_diagnosis_payload(session, run_id)
    if not data:
        return None
    global_stats = stats_repo.fetch_global_stats_dict(run_id)

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
        focus_characters_normalized if isinstance(focus_characters_normalized, list) else None,
        arc_scores_normalized,
    )
    main_characters_filtered = filter_character_list_against_arc_scores(
        main_characters_normalized if isinstance(main_characters_normalized, list) else None,
        arc_scores_normalized,
    )
    core_cast_filtered = filter_character_list_against_arc_scores(
        core_cast_normalized if isinstance(core_cast_normalized, list) else None,
        arc_scores_normalized,
    )
    normalized_focus_structure = derive_focus_structure_from_characters(focus_characters_filtered)
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
