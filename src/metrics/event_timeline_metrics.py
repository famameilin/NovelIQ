"""
事件森林时间轴域（一树一节点）

2026-08-20：新建事件时间轴度量，不依赖旧 timeline_metrics 的 authority 合同。
"""

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


class AnnotationRepositoryProtocol(Protocol):
    """2026-08-20 用于 build_event_timeline_plan 的标注仓储协议（当前仅占位，保留扩展）"""

    @property
    def session(self) -> Session: ...


@dataclass(slots=True)
class EventTimelineNodeDTO:
    """2026-08-20 用于事件时间轴单节点（一树一节点）"""

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
    """2026-08-20 用于事件时间轴构建结果"""

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
    """2026-08-20 用于序列化事件时间轴节点为 API 载荷"""
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
    """2026-08-20 用于序列化阶段"""
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
    annotation_repo: AnnotationRepositoryProtocol,
    stats_repo: StatsRepositoryProtocol,
    forest_snapshot: EventForestSnapshot | None,
) -> EventTimelinePlanBuildResult:
    """2026-08-20 用于从事件森林快照构建时间轴规划

    progress 统一用 chapter_id_to_order/total_chapters
    importance_score = len(tree.main_chain)*0.4 + len(secondary)*0.2 + tension_percentile*0.3 + causal_out_degree*0.1
    level 1-3 按 score 分位数
    phase_name 按 anchor_chapter_order 映射到 phases
    """
    # 章节顺序与总量
    chapter_texts: list[tuple[int, str]] = []
    try:
        chapter_texts = chapter_repo.fetch_chapter_texts(run_id)
    except (DBAPIError, ValueError, KeyError) as e:
        logger.warning("build_event_timeline_plan fetch_chapter_texts fallback for run {}: {}", run_id, e)
        chapter_texts = []
    chapter_ids: list[int] = [cid for cid, _ in chapter_texts]
    total_chapters = len(chapter_ids)
    chapter_id_to_order: dict[int, int] = {cid: idx + 1 for idx, cid in enumerate(chapter_ids)}

    # 若无章节，直接返回空
    if total_chapters == 0:
        # 尝试从 snapshot 的 chapter_order 推断 total
        if forest_snapshot is not None:
            total_chapters = forest_snapshot.visible_through_chapter_order
        else:
            total_chapters = 0

    # 张力曲线
    tension_by_chapter: dict[int, float] = {}
    tension_scores: list[float] = []
    positions: list[float] | None = None
    try:
        from src.storage.repositories.paragraph_repository import ParagraphRepository

        rows = ParagraphRepository(stats_repo.session).fetch_chapter_tension_scores(run_id)
        tension_by_chapter = {int(cid): float(v) for cid, v in rows}
        tension_scores = [tension_by_chapter.get(cid, 0.5) for cid in chapter_ids]
        # positions 用 progress_map 或等间隔
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

    # 四阶段
    phases: list[TimelinePhaseDTO] = []
    phase_basis = "tension"
    if chapter_ids and tension_scores:
        narrative_phases = compute_four_phases(tension_scores, chapter_ids, positions)
        phases = convert_to_timeline_phases(narrative_phases)
        phase_basis = "fixed_percentage" if total_chapters < 20 else "tension"
    elif total_chapters:
        # 无张力时用固定百分比兜底，compute_four_phases 已处理 <20 情况
        # 若 tension_scores 空，构造等值 tension 触发固定百分比逻辑
        dummy_tensions = [0.5] * total_chapters
        dummy_positions = [i / max(total_chapters - 1, 1) for i in range(total_chapters)]
        narrative_phases = compute_four_phases(dummy_tensions, chapter_ids, dummy_positions)
        phases = convert_to_timeline_phases(narrative_phases)
        phase_basis = "fixed_percentage"

    derived_event_order: list[str] = []
    if forest_snapshot is not None:
        derived_event_order = list(forest_snapshot.derived_event_order)

    # 无快照或无树，直接返回空节点
    if forest_snapshot is None or not forest_snapshot.event_trees:
        return EventTimelinePlanBuildResult(
            nodes=[],
            phases=phases,
            total_chapters=total_chapters,
            tension_curve=tension_scores,
            phase_basis=phase_basis,
            derived_event_order=derived_event_order,
        )

    # 预计算边度数
    # causal_out/in 基于 snapshot.causal_edges（已含 inactive）
    out_degree_by_event: dict[str, int] = {}
    in_degree_by_event: dict[str, int] = {}
    for edge in forest_snapshot.causal_edges:
        out_degree_by_event[edge.source_event_id] = out_degree_by_event.get(edge.source_event_id, 0) + 1
        in_degree_by_event[edge.target_event_id] = in_degree_by_event.get(edge.target_event_id, 0) + 1

    # event_id -> node 映射，用于聚合 participants
    node_by_event_id: dict[str, Any] = {n.event_id: n for n in forest_snapshot.event_nodes}

    # 构建节点并计算 importance
    raw_nodes: list[EventTimelineNodeDTO] = []
    scores: list[float] = []
    for tree in forest_snapshot.event_trees:
        root_node = node_by_event_id.get(tree.root_event_id)
        # anchor 取 root 节点，若缺失则取树内首节点排序
        if root_node is None:
            # 兜底：取 main_chain 首个存在的 event
            for eid in tree.main_chain:
                if eid in node_by_event_id:
                    root_node = node_by_event_id[eid]
                    break
        if root_node is None:
            # 树内无对应事件节点，跳过
            continue
        anchor_chapter_id = int(root_node.chapter_id)
        anchor_chapter_order = int(root_node.chapter_order)
        # 若 chapter_id_to_order 缺失，用 root_node 的 chapter_order
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
        # 限制到 [0,1]
        start_progress = max(0.0, min(1.0, start_progress))
        end_progress = max(0.0, min(1.0, end_progress))
        progress = max(0.0, min(1.0, progress))

        # participants 聚合：树内所有节点的 participants 原样合并
        participants: list[dict[str, Any]] = []
        for eid in tree.main_chain:
            n = node_by_event_id.get(eid)
            if n is not None:
                participants.extend(list(n.participants))
        # 次因分支事件也纳入
        for grp in tree.secondary_groups:
            for eid in grp.branch:
                n = node_by_event_id.get(eid)
                if n is not None:
                    participants.extend(list(n.participants))
        # 去重保留首次出现：仅收 character（未标注时视同角色，非 character 过滤）
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

        # 统计 secondary 数量：所有分支的 event 数之和
        secondary_count = sum(len(g.branch) for g in tree.secondary_groups)
        # tension percentile
        tension_score = tension_by_chapter.get(anchor_chapter_id, 0.5)
        # 若 tension_scores 全为 0.5 且无真实数据，则 percentile 为 50
        tension_percentile = calculate_tension_percentile(tension_score, tension_scores) if tension_scores else 50
        # causal degree：树内所有 event 的 out-degree 之和
        tree_event_ids = set(tree.main_chain)
        for g in tree.secondary_groups:
            tree_event_ids.update(g.branch)
        causal_out = sum(out_degree_by_event.get(eid, 0) for eid in tree_event_ids)
        causal_in = sum(in_degree_by_event.get(eid, 0) for eid in tree_event_ids)

        importance = len(tree.main_chain) * 0.4 + secondary_count * 0.2 + tension_percentile * 0.3 + causal_out * 0.1
        scores.append(importance)

        # title/summary 取 root 描述
        title = str(root_node.description[:30]) if root_node.description else tree.tree_id
        summary = str(root_node.description)

        # phase
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
                level=3,  # 占位，后续按分位数重算
                phase_name=phase_name,
                main_chain=list(tree.main_chain),
                secondary_groups=secondary_groups_serialized,
                causal_in=causal_in,
                causal_out=causal_out,
            )
        )

    # 按分位数定 level 1-3
    if raw_nodes:
        sorted_scores = sorted(scores)
        n = len(sorted_scores)
        # 分位数阈值：66% 与 33%
        # 若 n <3，则最高为 1，其余递增
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
        # 若全部相等，q_high==q_low，需调整：仅最高分节点为 1，其余为 2（与注释一致，全等时唯一 maxScore 为 1）
        if q_high == q_low and len(raw_nodes) > 1:
            max_node = max(raw_nodes, key=lambda n: n.importance_score)
            for node in raw_nodes:
                node.level = 1 if node is max_node else 2

    # 按派生顺序排序（derived_event_order 已按 (chapter_order, char_start, char_end, event_id) 细粒度排好）
    if derived_event_order:
        order_index: dict[str, int] = {eid: idx for idx, eid in enumerate(derived_event_order)}
        # tree 维度：以 root_event_id 在派生顺序中的位置为序，找不到则以 tree_id 兜底，再回退到 progress
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
