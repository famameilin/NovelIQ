"""
分块查询组装器

说明: 承载 chunks 相关查询组装逻辑
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from loguru import logger

from src.api.exceptions import GraphReadinessError
from src.api.models.responses import (
    ChunkAnnotation,
    ChunkCharacter,
    ChunkCurvePoint,
    ChunkDialogue,
    ChunkRelation,
    ChunkStyle,
)
from src.knowledge.authority import ExportGraphAuthorityView, KnowledgeGraphAuthorityService
from src.models.local.character_reference_policy import decide_character_reference
from src.storage.repositories import AnnotationRepository, ChunkRepository, StatsRepository

from .common import _normalize_name


def _build_chunk_curve_points(rows: Sequence[Any]) -> list[ChunkCurvePoint]:
    """统一构建 chunk curve DTO"""
    return [
        ChunkCurvePoint(
            chunk_id=row.chunk_id,
            pos_density=row.pos_density,
            neg_density=row.neg_density,
            net_density=row.net_density,
            smoothed_density=row.smoothed_density,
            tension_proxy=row.tension_proxy,
            tension_composite=row.tension_composite,
            surface_tension=getattr(row, "surface_tension", None),
        )
        for row in rows
    ]


def _fetch_raw_chunk_curves(run_id: str, stats_repo: StatsRepository) -> list[ChunkCurvePoint]:
    """获取数据库中持久化的原始 chunk_curves"""
    rows = stats_repo.fetch_chunk_curves_full(run_id)
    return _build_chunk_curve_points(rows)


def _fetch_chunk_curves(
    run_id: str,
    stats_repo: StatsRepository,
    annotation_repo: AnnotationRepository,
    chunk_repo: ChunkRepository,
) -> list:
    """获取分块曲线数据（情绪 + 节奏）"""
    from src.metrics.emotion_curve_fusion import build_display_emotion_curve
    from src.metrics.rhythm_curve_fusion import build_display_surface_tension

    rows = stats_repo.fetch_chunk_curves_full(run_id)
    style_rows = chunk_repo.fetch_chunk_styles_full(run_id)
    surface_tension_by_chunk = build_display_surface_tension(rows, style_rows)
    fused_rows = build_display_emotion_curve(
        curve_rows=rows,
        annotation_rows=annotation_repo.fetch_chunk_annotations_full(run_id),
        style_rows=style_rows,
        dialogue_rows=annotation_repo.fetch_chunk_dialogues_full(run_id),
        surface_tension_by_chunk=surface_tension_by_chunk,
    )
    return _build_chunk_curve_points(fused_rows)


def _fetch_chunk_styles(run_id: str, chunk_repo: ChunkRepository) -> list:
    """获取分块风格数据"""
    rows = chunk_repo.fetch_chunk_styles_full(run_id)
    return [
        ChunkStyle(
            chunk_id=row.chunk_id,
            mtld=row.mtld,
            ttr=row.ttr,
            avg_sent_len=row.avg_sent_len,
            d_value=row.d_value,
            pause_density=row.pause_density,
            fight_density=row.fight_density,
            dialogue_ratio=row.dialogue_ratio,
            sensory_density=row.sensory_density,
            metaphor_density=row.metaphor_density,
            imagery_lexicon_density=row.imagery_lexicon_density,
        )
        for row in rows
    ]


def _fetch_chunk_annotations(
    run_id: str,
    annotation_repo: AnnotationRepository,
    alias_map: dict[str, str] | None = None,
    valid_character_names: set[str] | None = None,
    export_graph_view: ExportGraphAuthorityView | None = None,
    require_graph_projection: bool = True,
) -> list:
    """
    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: chunk results 读取层需要过滤未解析代词引用，避免“我”等局部引用泄漏为全局角色。

    获取分块标注数据
    """
    annotations_raw = annotation_repo.fetch_chunk_annotations_full(run_id)
    characters_raw = annotation_repo.fetch_chunk_characters_full(run_id)
    dialogues_raw = annotation_repo.fetch_chunk_dialogues_full(run_id)

    if export_graph_view is None:
        authority_service = KnowledgeGraphAuthorityService.from_session(annotation_repo.session)
        if require_graph_projection:
            export_graph_view = authority_service.build_export_view(run_id)
        else:
            try:
                export_graph_view = authority_service.build_export_view(run_id)
            except GraphReadinessError:
                export_graph_view = ExportGraphAuthorityView()

    if require_graph_projection and not export_graph_view.relation_events:
        pending_relations = annotation_repo.fetch_pending_chunk_relations(run_id, limit=1)
        if pending_relations:
            raise RuntimeError(
                "graph relation events are empty while pending relations still exist; "
                "run graph projection before exporting results."
            )

    characters_by_chunk: dict[int, list[ChunkCharacter]] = defaultdict(list)
    for row in characters_raw:
        chunk_id = row.chunk_id
        raw_name = str(getattr(row, "surface_name", None) or row.name)
        decision = decide_character_reference(
            raw_name,
            alias_map=alias_map,
            resolved_global_name=getattr(row, "resolved_global_name", None),
        )
        character_name = decision.resolved_global_name
        if character_name is None:
            logger.warning("跳过分块角色中的未解析局部引用: chunk_id={}, name={}", chunk_id, raw_name)
            continue
        if valid_character_names is not None and character_name not in valid_character_names:
            logger.warning("跳过分块角色中的悬空引用: chunk_id={}, name={}", chunk_id, character_name)
            continue
        characters_by_chunk[chunk_id].append(
            ChunkCharacter(
                name=character_name,
                surface_name=raw_name,
                reference_kind=getattr(row, "reference_kind", None) or decision.reference_kind,
                reference_slot=getattr(row, "reference_slot", None) or decision.reference_slot,
                resolved_global_name=character_name,
                global_skip_reason=decision.global_skip_reason,
                role_function=str(row.role_function) if row.role_function else None,
                action=str(row.action) if row.action else None,
                emotion_score=str(row.emotion_score) if row.emotion_score else None,
            )
        )

    relations_by_chunk: dict[int, list[ChunkRelation]] = defaultdict(list)
    for relation_event in export_graph_view.relation_events:
        chunk_id = relation_event.chunk_id
        from_char = _normalize_name(relation_event.from_name, alias_map) or relation_event.from_name
        to_char = _normalize_name(relation_event.to_name, alias_map) or relation_event.to_name
        if valid_character_names is not None and (
            from_char not in valid_character_names or to_char not in valid_character_names
        ):
            logger.warning(
                "跳过分块关系中的悬空引用: chunk_id={}, from_char={}, to_char={}",
                chunk_id,
                from_char,
                to_char,
            )
            continue
        relations_by_chunk[chunk_id].append(
            ChunkRelation(
                from_char=from_char,
                to_char=to_char,
                from_reference_kind=getattr(relation_event, "from_reference_kind", None),
                to_reference_kind=getattr(relation_event, "to_reference_kind", None),
                resolved_from_global_name=from_char,
                resolved_to_global_name=to_char,
                reference_skip_reason=None,
                type=relation_event.relation_type,
                change=relation_event.change_type,
            )
        )

    dialogues_by_chunk: dict[int, list[ChunkDialogue]] = defaultdict(list)
    for row in dialogues_raw:
        chunk_id = row.chunk_id
        speakers = row.speaker or []
        if not speakers:
            continue
        valid_speakers = []
        speaker_reference_by_surface: dict[str, dict[str, Any]] = {}
        for item in getattr(row, "speaker_references", None) or []:
            if not isinstance(item, dict):
                continue
            surface_name = str(item.get("surface_name") or "").strip()
            if surface_name:
                speaker_reference_by_surface[surface_name] = item
        speaker_references: list[dict[str, Any]] = []
        for speaker in speakers:
            reference_payload = speaker_reference_by_surface.get(str(speaker).strip(), {})
            decision = decide_character_reference(
                speaker,
                alias_map=alias_map,
                resolved_global_name=reference_payload.get("resolved_global_name"),
            )
            speaker_references.append(
                {
                    "surface_name": decision.surface_name,
                    "reference_kind": decision.reference_kind,
                    "reference_slot": reference_payload.get("reference_slot") or decision.reference_slot,
                    "resolved_global_name": decision.resolved_global_name,
                    "can_enter_global_character": decision.can_enter_global_character,
                    "global_skip_reason": decision.global_skip_reason,
                }
            )
            normalized_speaker = decision.resolved_global_name
            if normalized_speaker is None:
                logger.warning("将分块对话中的未解析局部 speaker 置空: chunk_id={}, speaker={}", chunk_id, speaker)
                continue
            if (
                normalized_speaker
                and valid_character_names is not None
                and normalized_speaker not in valid_character_names
            ):
                logger.warning("将分块对话中的悬空 speaker 置空: chunk_id={}, speaker={}", chunk_id, normalized_speaker)
                continue
            if normalized_speaker:
                valid_speakers.append(normalized_speaker)
        if not valid_speakers:
            continue
        dialogues_by_chunk[chunk_id].append(
            ChunkDialogue(
                speaker=valid_speakers,
                speaker_references=speaker_references,
                length=int(row.length) if row.length is not None else None,
            )
        )

    result: list[ChunkAnnotation] = []
    for row in annotations_raw:
        chunk_id = int(row.chunk_id)
        result.append(
            ChunkAnnotation(
                chunk_id=chunk_id,
                emotional_valence=str(row.emotional_valence) if row.emotional_valence else None,
                event_type=str(row.event_type) if row.event_type else None,
                pivot_moment=bool(row.pivot_moment) if row.pivot_moment is not None else None,
                cliffhanger=bool(row.cliffhanger) if row.cliffhanger is not None else None,
                has_foreshadowing=bool(row.has_foreshadowing) if row.has_foreshadowing is not None else None,
                is_strong_setup=(
                    bool(row.is_strong_setup) if getattr(row, "is_strong_setup", None) is not None else None
                ),
                foreshadowing_type=str(row.foreshadowing_type) if row.foreshadowing_type else None,
                setup_kind=str(row.setup_kind) if getattr(row, "setup_kind", None) else None,
                foreshadowing_desc=str(row.foreshadowing_desc) if row.foreshadowing_desc else None,
                setup_summary=str(row.setup_summary) if getattr(row, "setup_summary", None) else None,
                why_unresolved_now=(
                    str(row.why_unresolved_now) if getattr(row, "why_unresolved_now", None) else None
                ),
                expected_payoff_family=(
                    str(row.expected_payoff_family) if getattr(row, "expected_payoff_family", None) else None
                ),
                payoff_likelihood=(
                    str(row.payoff_likelihood) if getattr(row, "payoff_likelihood", None) else None
                ),
                linked_setup_id=(
                    str(row.linked_setup_id) if getattr(row, "linked_setup_id", None) else None
                ),
                characters=characters_by_chunk.get(chunk_id, []),
                relations=relations_by_chunk.get(chunk_id, []),
                dialogues=dialogues_by_chunk.get(chunk_id, []),
            )
        )

    return result
