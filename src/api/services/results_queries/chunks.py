"""
分块查询组装器。

创建时间: 2026-04-23
创建者: Codex
任务: p1-api-route-service-decouple
说明: 承载 chunks 相关查询组装逻辑。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from loguru import logger

from src.api.models.responses import (
    ChunkAnnotation,
    ChunkCharacter,
    ChunkCurvePoint,
    ChunkDialogue,
    ChunkRelation,
    ChunkStyle,
)
from src.knowledge.authority import ExportGraphAuthorityView, KnowledgeGraphAuthorityService
from src.storage.repositories import AnnotationRepository, ChunkRepository, StatsRepository

from .common import _normalize_name


def _build_chunk_curve_points(rows: Sequence[Any]) -> list[ChunkCurvePoint]:
    """统一构建 chunk curve DTO。"""
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
    """获取数据库中持久化的原始 chunk_curves。"""
    rows = stats_repo.fetch_chunk_curves_full(run_id)
    return _build_chunk_curve_points(rows)


def _fetch_chunk_curves(
    run_id: str,
    stats_repo: StatsRepository,
    annotation_repo: AnnotationRepository,
    chunk_repo: ChunkRepository,
) -> list:
    """获取分块曲线数据（情绪 + 节奏）。"""
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
    """获取分块风格数据。"""
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
    获取分块标注数据。

    修改时间: 2026-04-26
    修改者: Codex
    任务: phase2-strong-foreshadowing
    修改内容: 新增 require_graph_projection 开关，让 `chunk-annotations`
    这类只关心 Phase2 结果的 consumer 可以在 graph projection 未完成时降级返回，
    同时保留 export 链路对 relation events 完整性的严格要求。
    """
    annotations_raw = annotation_repo.fetch_chunk_annotations_full(run_id)
    characters_raw = annotation_repo.fetch_chunk_characters_full(run_id)
    dialogues_raw = annotation_repo.fetch_chunk_dialogues_full(run_id)

    if export_graph_view is None:
        export_graph_view = KnowledgeGraphAuthorityService.from_session(annotation_repo.session).build_export_view(
            run_id
        )

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
        normalized_name = _normalize_name(str(row.name), alias_map)
        character_name = normalized_name if normalized_name else str(row.name)
        if valid_character_names is not None and character_name not in valid_character_names:
            logger.warning("跳过分块角色中的悬空引用: chunk_id={}, name={}", chunk_id, character_name)
            continue
        characters_by_chunk[chunk_id].append(
            ChunkCharacter(
                name=character_name,
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
        normalized_speakers = [_normalize_name(speaker, alias_map) for speaker in speakers]
        valid_speakers = []
        for normalized_speaker in normalized_speakers:
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
