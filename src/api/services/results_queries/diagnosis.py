"""
诊断查询组装器。

创建时间: 2026-04-23
创建者: Codex
任务: p1-api-route-service-decouple
说明: 承载 diagnosis 相关查询组装逻辑。
"""

from __future__ import annotations

from typing import Literal, TypeGuard

from loguru import logger

from src.api.models.responses import DiagnosisResult
from src.storage.repositories import AnnotationRepository, StatsRepository

from .common import (
    _normalize_arc_scores,
    _normalize_name_list,
    _normalize_text_by_alias_map,
    _parse_int_field,
    _parse_json_field,
)


def _filter_character_list_against_arc_scores(
    values: list[str] | None,
    arc_scores: dict[str, float] | None,
) -> list[str] | None:
    """
    创建时间: 2026-04-27
    创建者: Codex
    任务: protagonist-focus-contract-followup-fixes
    说明: alias 归一化会把别名和规范名折叠到同一个角色名上；
    结果读取层必须在归一化后再次按 `arc_scores` 收口，避免焦点人物、
    主要人物、核心角色继续携带失效名称。
    """
    if values is None:
        return None
    if not arc_scores:
        return []
    valid_names = set(arc_scores.keys())
    return [name for name in values if name in valid_names]


def _derive_focus_structure_from_characters(
    focus_characters: list[str] | None,
) -> Literal["single", "dual", "ensemble"] | None:
    """
    创建时间: 2026-04-27
    创建者: Codex
    任务: protagonist-focus-contract-followup-fixes
    说明: alias 归一化后，焦点人物数量可能发生折叠；此时必须按归一化后的
    最终名单重新推导 focus_structure，不能把 `dual` + 单人列表这种矛盾合同继续对外暴露。
    """
    if not focus_characters:
        return None
    focus_count = len(focus_characters)
    if focus_count == 1:
        return "single"
    if focus_count == 2:
        return "dual"
    return "ensemble"


def _has_complete_focus_contract(
    arc_scores: dict[str, float] | None,
    focus_structure: Literal["single", "dual", "ensemble"] | None,
    focus_characters: list[str] | None,
    main_characters: list[str] | None = None,
    core_cast: list[str] | None = None,
    topic_labels: list[str] | None = None,
) -> bool:
    """
    创建时间: 2026-04-27
    创建者: Codex
    任务: protagonist-focus-contract-review-fixes
    说明: 当前分支已经明确“不兼容缺焦点合同的旧 diagnosis 行”；
    结果读取层必须把缺 `focus_structure` / `focus_characters` / `topic_labels` 的数据视为无效，
    统一走 rerun-required 分支，而不是继续向 API / export 暴露半成品对象。
    """
    if (
        not arc_scores
        or focus_structure is None
        or not focus_characters
        or not main_characters
        or not core_cast
        or not topic_labels
    ):
        return False
    return _derive_focus_structure_from_characters(focus_characters) == focus_structure


def _is_complete_diagnosis_result(diagnosis: DiagnosisResult | None) -> TypeGuard[DiagnosisResult]:
    """
    创建时间: 2026-04-27
    创建者: Codex
    任务: protagonist-focus-contract-review-fixes-round2
    说明: results/export/characters 都需要把“新焦点合同是否完整”当成统一真相源；
    这里收口到 DiagnosisResult 级别，避免每条链路各自重复判断。
    """
    if diagnosis is None or diagnosis.rerun_required:
        return False
    return _has_complete_focus_contract(
        diagnosis.arc_scores,
        diagnosis.focus_structure,
        diagnosis.focus_characters,
        diagnosis.main_characters,
        diagnosis.core_cast,
        diagnosis.topic_labels,
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

    修改时间: 2026-04-27
    修改者: Codex
    任务: protagonist-focus-contract
    修改原因: diagnosis 结果合同切到焦点结构后，这里只组装 `focus_structure` /
    `focus_characters` 等新字段，不再保留旧单主角兼容分支。
    """
    data = stats_repo.fetch_cloud_analysis(novel_id, run_id)
    if not data:
        return DiagnosisResult(
            rerun_required=True,
            rerun_reason="diagnosis_missing_focus_contract",
        )

    focus_characters_raw = _parse_json_field(data.get("focus_characters")) if data else None
    focus_characters_normalized = (
        _normalize_name_list(focus_characters_raw, alias_map)
        if isinstance(focus_characters_raw, list)
        else focus_characters_raw
    )

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

    arc_scores_raw = _parse_json_field(data.get("arc_scores")) if data else None
    arc_scores_normalized = _normalize_arc_scores(
        arc_scores_raw,
        alias_map,
    )

    topic_labels_raw = _parse_json_field(data.get("topic_labels")) if data else None
    topic_labels_normalized = (
        _normalize_name_list(topic_labels_raw, alias_map) if isinstance(topic_labels_raw, list) else topic_labels_raw
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
            "diagnosis focus contract changed after alias normalization: run_id={} novel_id={} raw_structure={} "
            "normalized_structure={} raw_focus_characters={} normalized_focus_characters={}",
            run_id,
            novel_id,
            focus_structure,
            normalized_focus_structure,
            focus_characters_normalized,
            focus_characters_filtered,
        )

    if not _has_complete_focus_contract(
        arc_scores_normalized,
        normalized_focus_structure,
        focus_characters_filtered,
        main_characters_filtered,
        core_cast_filtered,
        topic_labels_normalized if isinstance(topic_labels_normalized, list) else None,
    ):
        logger.warning(
            "diagnosis focus contract incomplete after normalization: run_id={} novel_id={} raw_structure={} "
            "normalized_structure={} raw_focus_characters={} normalized_focus_characters={}",
            run_id,
            novel_id,
            focus_structure,
            normalized_focus_structure,
            focus_characters_normalized,
            focus_characters_filtered,
        )
        return DiagnosisResult(
            rerun_required=True,
            rerun_reason="focus_contract_incomplete",
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
        focus_structure=normalized_focus_structure,
        focus_characters=focus_characters_filtered,
        main_characters=main_characters_filtered,
        core_cast=core_cast_filtered,
        theme_color=(theme_color.strip() if (data and (theme_color := data.get("theme_color"))) else None),
    )
