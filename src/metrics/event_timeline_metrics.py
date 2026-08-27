"""事件森林时间轴度量"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from loguru import logger
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from src.metrics.timeline_phase import (
    TimelinePhaseDTO,
    calculate_tension_percentile,
    compute_four_phases,
    convert_to_timeline_phases,
)
from src.storage.repositories.graph.event_forest import EventForestSnapshot


class ChapterRepositoryProtocol(Protocol):
    """2026-08-20 用于 build_event_timeline_plan 的章节仓储协议（需提供 fetch_chapter_texts）"""

    def fetch_chapter_texts(self, run_id: str) -> list[tuple[int, str]]: ...


class StatsRepositoryProtocol(Protocol):
    """2026-08-20 用于 build_event_timeline_plan 的统计仓储协议（需暴露 session）"""

    @property
    def session(self) -> Session: ...


@dataclass(slots=True)
class EventTimelineNodeDTO:
    """事件时间轴中的事件树节点"""

    tree_id: str
    root_event_id: str
    title: str
    summary: str
    anchor_chapter_id: int
    anchor_chapter_order: int
    start_chapter_id: int
    end_chapter_id: int
    start_progress: float
    end_progress: float
    progress: float
    chapter_ids: list[int]
    char_start: int
    char_end: int
    participants: list[dict[str, Any]]
    character_names: list[str]
    importance_score: float
    level: int
    phase_name: str
    main_chain: list[str]
    secondary_groups: list[dict[str, Any]]
    causal_in: int
    causal_out: int


@dataclass(slots=True)
class EventTimelinePlanBuildResult:
    """事件时间轴构建结果"""

    nodes: list[EventTimelineNodeDTO]
    phases: list[TimelinePhaseDTO]
    total_chapters: int
    tension_curve: list[float]
    phase_basis: str
    derived_event_order: list[str]


def _resolve_phase_name(chapter_id: int, phases: list[TimelinePhaseDTO]) -> str:
    for phase in phases:
        if phase.start <= chapter_id <= phase.end:
            return str(phase.name)
    if phases:
        return str(phases[-1].name)
    return "引入期"


def serialize_event_timeline_node(node: EventTimelineNodeDTO) -> dict[str, Any]:
    """将事件时间轴节点序列化为 API 载荷"""
    return {
        "tree_id": node.tree_id,
        "root_event_id": node.root_event_id,
        "title": node.title,
        "summary": node.summary,
        "anchor_chapter_id": node.anchor_chapter_id,
        "anchor_chapter_order": node.anchor_chapter_order,
        "start_chapter_id": node.start_chapter_id,
        "end_chapter_id": node.end_chapter_id,
        "start_progress": round(node.start_progress, 4),
        "end_progress": round(node.end_progress, 4),
        "progress": round(node.progress, 4),
        "chapter_ids": node.chapter_ids,
        "char_start": node.char_start,
        "char_end": node.char_end,
        "participants": node.participants,
        "character_names": node.character_names,
        "importance_score": round(node.importance_score, 2),
        "level": node.level,
        "phase_name": node.phase_name,
        "main_chain": node.main_chain,
        "secondary_groups": node.secondary_groups,
        "causal_in": node.causal_in,
        "causal_out": node.causal_out,
        "node_type": "event",
    }


def serialize_event_timeline_phases(phases: list[TimelinePhaseDTO]) -> list[dict[str, Any]]:
    """序列化时间轴阶段"""
    return [
        {
            "name": phase.name,
            "start": phase.start,
            "end": phase.end,
            "ratio": round(phase.ratio, 4),
        }
        for phase in phases
    ]


def build_event_timeline_plan(
    run_id: str,
    chapter_repo: ChapterRepositoryProtocol,
    stats_repo: StatsRepositoryProtocol,
    forest_snapshot: EventForestSnapshot | None,
) -> EventTimelinePlanBuildResult:
    """从事件森林快照构建时间轴规划"""
    chapter_texts: list[tuple[int, str]] = []
    try:
        chapter_texts = chapter_repo.fetch_chapter_texts(run_id)
    except (DBAPIError, ValueError, KeyError) as e:
        logger.warning("build_event_timeline_plan fetch_chapter_texts fallback for run {}: {}", run_id, e)
        chapter_texts = []
    chapter_ids: list[int] = [cid for cid, _ in chapter_texts]
    total_chapters = len(chapter_ids)
    chapter_id_to_order: dict[int, int] = {cid: idx + 1 for idx, cid in enumerate(chapter_ids)}

    if total_chapters == 0:
        if forest_snapshot is not None:
            total_chapters = forest_snapshot.visible_through_chapter_order

    tension_by_chapter: dict[int, float] = {}
    tension_scores: list[float] = []
    positions: list[float] | None = None
    try:
        from src.storage.repositories.paragraph_repository import ParagraphRepository

        rows = ParagraphRepository(stats_repo.session).fetch_chapter_tension_scores(run_id)
        tension_by_chapter = {int(cid): float(v) for cid, v in rows}
        tension_scores = [tension_by_chapter.get(cid, 0.5) for cid in chapter_ids]
        from src.metrics.aggregate.fetchers import _fetch_chapter_progress_map

        progress_map = _fetch_chapter_progress_map(stats_repo.session, run_id)
        if total_chapters <= 1:
            positions = [0.0] * total_chapters
        else:
            positions = []
            for idx, cid in enumerate(chapter_ids):
                positions.append(progress_map.get(cid, idx / (total_chapters - 1)))
            for i in range(1, len(positions)):
                if positions[i] <= positions[i - 1]:
                    positions[i] = min(1.0, positions[i - 1] + 1e-6)
    except (DBAPIError, ValueError, KeyError) as e:
        logger.warning("build_event_timeline_plan tension fallback for run {}: {}", run_id, e)
        tension_scores = [0.5] * total_chapters if total_chapters else []
        positions = [i / max(total_chapters - 1, 1) for i in range(total_chapters)] if total_chapters else []

    phases: list[TimelinePhaseDTO] = []
    phase_basis = "tension"
    if chapter_ids and tension_scores:
        narrative_phases = compute_four_phases(tension_scores, chapter_ids, positions)
        phases = convert_to_timeline_phases(narrative_phases)
        phase_basis = "fixed_percentage" if total_chapters < 20 else "tension"
    elif total_chapters:
        dummy_tensions = [0.5] * total_chapters
        dummy_positions = [i / max(total_chapters - 1, 1) for i in range(total_chapters)]
        narrative_phases = compute_four_phases(dummy_tensions, chapter_ids, dummy_positions)
        phases = convert_to_timeline_phases(narrative_phases)
        phase_basis = "fixed_percentage"

    derived_event_order: list[str] = []
    if forest_snapshot is not None:
        derived_event_order = list(forest_snapshot.derived_event_order)

    if forest_snapshot is None or not forest_snapshot.event_trees:
        return EventTimelinePlanBuildResult(
            nodes=[],
            phases=phases,
            total_chapters=total_chapters,
            tension_curve=tension_scores,
            phase_basis=phase_basis,
            derived_event_order=derived_event_order,
        )

    out_degree_by_event: dict[str, int] = {}
    in_degree_by_event: dict[str, int] = {}
    for edge in forest_snapshot.causal_edges:
        out_degree_by_event[edge.source_event_id] = out_degree_by_event.get(edge.source_event_id, 0) + 1
        in_degree_by_event[edge.target_event_id] = in_degree_by_event.get(edge.target_event_id, 0) + 1

    node_by_event_id: dict[str, Any] = {n.event_id: n for n in forest_snapshot.event_nodes}

    raw_nodes: list[EventTimelineNodeDTO] = []
    scores: list[float] = []
    for tree in forest_snapshot.event_trees:
        root_node = node_by_event_id.get(tree.root_event_id)
        if root_node is None:
            for eid in tree.main_chain:
                if eid in node_by_event_id:
                    root_node = node_by_event_id[eid]
                    break
        if root_node is None:
            continue
        anchor_chapter_id = int(root_node.chapter_id)
        anchor_chapter_order = int(root_node.chapter_order)
        if anchor_chapter_id not in chapter_id_to_order:
            chapter_id_to_order[anchor_chapter_id] = anchor_chapter_order
            if anchor_chapter_order > total_chapters:
                total_chapters = anchor_chapter_order

        start_chapter_id = min(tree.chapter_ids) if tree.chapter_ids else anchor_chapter_id
        end_chapter_id = max(tree.chapter_ids) if tree.chapter_ids else anchor_chapter_id
        start_order = chapter_id_to_order.get(start_chapter_id, anchor_chapter_order)
        end_order = chapter_id_to_order.get(end_chapter_id, anchor_chapter_order)
        total_for_progress = max(total_chapters, 1)
        start_progress = start_order / total_for_progress
        end_progress = end_order / total_for_progress
        progress = anchor_chapter_order / total_for_progress
        start_progress = max(0.0, min(1.0, start_progress))
        end_progress = max(0.0, min(1.0, end_progress))
        progress = max(0.0, min(1.0, progress))

        participants: list[dict[str, Any]] = []
        for eid in tree.main_chain:
            n = node_by_event_id.get(eid)
            if n is not None:
                participants.extend(list(n.participants))
        for grp in tree.secondary_groups:
            for eid in grp.branch:
                n = node_by_event_id.get(eid)
                if n is not None:
                    participants.extend(list(n.participants))
        character_names: list[str] = []
        seen_chars: set[str] = set()
        for p in participants:
            name = str(p.get("name") or "").strip()
            entity_type = str(p.get("entity_type") or "")
            if not name or name in seen_chars:
                continue
            if entity_type and entity_type != "character":
                continue
            seen_chars.add(name)
            character_names.append(name)

        secondary_count = sum(len(g.branch) for g in tree.secondary_groups)
        tension_score = tension_by_chapter.get(anchor_chapter_id, 0.5)
        tension_percentile = calculate_tension_percentile(tension_score, tension_scores) if tension_scores else 50
        tree_event_ids = set(tree.main_chain)
        for g in tree.secondary_groups:
            tree_event_ids.update(g.branch)
        causal_out = sum(out_degree_by_event.get(eid, 0) for eid in tree_event_ids)
        causal_in = sum(in_degree_by_event.get(eid, 0) for eid in tree_event_ids)

        importance = len(tree.main_chain) * 0.4 + secondary_count * 0.2 + tension_percentile * 0.3 + causal_out * 0.1
        scores.append(importance)

        title = str(root_node.description[:30]) if root_node.description else tree.tree_id
        summary = str(root_node.description)
        phase_name = _resolve_phase_name(anchor_chapter_id, phases)

        secondary_groups_serialized = [
            {"target_event_id": g.target_event_id, "branch": list(g.branch)} for g in tree.secondary_groups
        ]

        raw_nodes.append(
            EventTimelineNodeDTO(
                tree_id=tree.tree_id,
                root_event_id=tree.root_event_id,
                title=title,
                summary=summary,
                anchor_chapter_id=anchor_chapter_id,
                anchor_chapter_order=anchor_chapter_order,
                start_chapter_id=start_chapter_id,
                end_chapter_id=end_chapter_id,
                start_progress=start_progress,
                end_progress=end_progress,
                progress=progress,
                chapter_ids=list(tree.chapter_ids),
                char_start=int(tree.char_start),
                char_end=int(tree.char_end),
                participants=participants,
                character_names=character_names,
                importance_score=round(importance, 2),
                level=3,
                phase_name=phase_name,
                main_chain=list(tree.main_chain),
                secondary_groups=secondary_groups_serialized,
                causal_in=causal_in,
                causal_out=causal_out,
            )
        )

    if raw_nodes:
        sorted_scores = sorted(scores)
        n = len(sorted_scores)
        if n >= 3:
            q_high = sorted_scores[int(n * 0.66)] if n * 0.66 < n else sorted_scores[-1]
            q_low = sorted_scores[int(n * 0.33)] if n * 0.33 < n else sorted_scores[0]
        else:
            q_high = sorted_scores[-1]
            q_low = sorted_scores[0]
        for node in raw_nodes:
            if node.importance_score >= q_high:
                node.level = 1
            elif node.importance_score >= q_low:
                node.level = 2
            else:
                node.level = 3
        if q_high == q_low and len(raw_nodes) > 1:
            max_node = max(raw_nodes, key=lambda n: n.importance_score)
            for node in raw_nodes:
                node.level = 1 if node is max_node else 2

    if derived_event_order:
        order_index: dict[str, int] = {eid: idx for idx, eid in enumerate(derived_event_order)}
        raw_nodes.sort(
            key=lambda x: (
                order_index.get(x.root_event_id, order_index.get(x.tree_id, float("inf"))),
                x.progress,
                x.anchor_chapter_order,
                x.char_start,
                x.char_end,
                x.tree_id,
            )
        )
    else:
        raw_nodes.sort(key=lambda x: (x.progress, x.anchor_chapter_order, x.char_start, x.char_end, x.tree_id))

    return EventTimelinePlanBuildResult(
        nodes=raw_nodes,
        phases=phases,
        total_chapters=total_chapters,
        tension_curve=tension_scores,
        phase_basis=phase_basis,
        derived_event_order=derived_event_order,
    )
