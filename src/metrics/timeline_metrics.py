"""
叙事时间轴核心算法模块。

创建时间: 2026-03-30
创建者: CodeBuddy
任务: refactor-session-management
说明: 提供时间轴节点重要性计算、四阶段划分、节点筛选功能

修改时间: 2026-04-27
修改者: Codex
任务: 时间轴合同重构
修改内容:
- 重写时间轴引擎，改为 TimelineAtom -> TimelineNodePlan 的新模型
- 统一 route / export 共用的预算与序列化逻辑
- 去除 “每个 chunk 只有一个时间轴节点” 与 “无变化关系也计分” 的旧语义
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from loguru import logger

from src.knowledge.authority import TIMELINE_AUTHORITY_DEPENDENCY_FIELDS, TimelineAuthorityView
from src.metrics.narrative_metrics import find_global_peak, find_local_peaks

TimelineNodeType = Literal["plot", "relation", "lifecycle"]
TimelineNodeSubtype = Literal["plot", "entry", "exit", "新建", "强化", "弱化", "断裂"]
TimelinePhaseName = Literal["引入期", "发展期", "高潮期", "收束期"]
ImportanceLevel = Literal[1, 2, 3]
LifecycleType = Literal["entry", "exit"]

PLOT_EVENT_TYPE_WEIGHTS: dict[str, float] = {
    "冲突": 1.2,
    "转折": 1.0,
    "铺垫": 0.4,
}
EMOTIONAL_VALENCE_WEIGHTS: dict[str, float] = {
    "strong_positive": 1.0,
    "strong_negative": 1.0,
    "mild_positive": 0.5,
    "mild_negative": 0.5,
    "neutral": 0.0,
}
RELATION_CHANGE_WEIGHTS: dict[str, float] = {
    "新建": 2.4,
    "强化": 1.8,
    "弱化": 1.6,
    "断裂": 2.6,
}


class TimelineDataUnavailableError(ValueError):
    """Raised when timeline source data is genuinely unavailable."""


class TimelineAuthorityContractError(RuntimeError):
    """Raised when the authority-backed timeline contract is violated."""


@dataclass(slots=True)
class RelationEventDTO:
    """时间轴关系事件 DTO。"""

    relation_event_id: int
    from_char: str
    to_char: str
    relation_type: str
    change_type: Literal["新建", "强化", "弱化", "断裂"]
    evidence: str | None = None
    confidence: float | None = None
    directionality: str | None = None


@dataclass(slots=True)
class LifecycleEventDTO:
    """时间轴生命周期事件 DTO。"""

    entity_id: int
    character_name: str
    lifecycle_type: LifecycleType


@dataclass(slots=True)
class PlotFlagsDTO:
    """剧情节点附加标记。"""

    is_pivot: bool
    is_cliffhanger: bool
    tension_percentile: int


@dataclass(slots=True)
class TimelinePhaseDTO:
    """时间轴阶段 DTO。"""

    name: TimelinePhaseName
    start: int
    end: int
    ratio: float


@dataclass(slots=True)
class TimelineNodeDTO:
    """时间轴节点 DTO。"""

    node_id: str
    anchor_chunk_id: int
    progress: float
    importance_score: float
    level: ImportanceLevel
    summary: str
    characters: list[str]
    phase_name: TimelinePhaseName
    node_type: TimelineNodeType
    node_subtype: TimelineNodeSubtype
    score_breakdown: dict[str, float]
    plot_flags: PlotFlagsDTO | None = None
    relation_events: list[RelationEventDTO] | None = None
    lifecycle_events: list[LifecycleEventDTO] | None = None


@dataclass(slots=True)
class NarrativePhase:
    """叙事阶段内部数据结构。"""

    name: str
    start: int
    end: int
    ratio: float


@dataclass(slots=True)
class TimelineAnnotationSnapshot:
    """时间轴候选节点使用的轻量标注快照。"""

    chunk_id: int
    event_type: str
    cliffhanger: bool
    pivot_moment: bool
    emotional_valence: str


@dataclass(slots=True)
class TimelineAuthorityData:
    """authority contract 校验后的时间轴只读输入。"""

    entity_lifecycles: list[Any]
    relation_events: list[Any]
    entity_name_map: dict[int, str]


@dataclass(slots=True)
class TimelineSourceData:
    """时间轴候选构建所需的数据上下文。"""

    chunk_texts: list[tuple[int, str]]
    chunk_ids: list[int]
    chunk_id_to_idx: dict[int, int]
    total_chunks: int
    tension_scores: list[float]
    summary_map: dict[int, str]
    annotation_map: dict[int, TimelineAnnotationSnapshot]


@dataclass(slots=True)
class TimelineBudget:
    """时间轴节点预算。"""

    min_nodes: int
    target_nodes: int
    max_nodes: int


@dataclass(slots=True)
class TimelinePlanBuildResult:
    """时间轴最终构建结果。"""

    nodes: list[TimelineNodeDTO]
    total_chunks: int
    phases: list[TimelinePhaseDTO]
    tension_curve: list[float]


@dataclass(slots=True)
class PlotAtom:
    """剧情原子信号。"""

    anchor_chunk_id: int
    progress: float
    summary: str
    phase_name: TimelinePhaseName
    characters: list[str]
    event_type: str
    emotional_valence: str
    tension_score: float
    tension_percentile: int
    is_pivot: bool
    is_cliffhanger: bool


@dataclass(slots=True)
class RelationAtom:
    """关系变化原子信号。"""

    anchor_chunk_id: int
    progress: float
    phase_name: TimelinePhaseName
    relation_event: RelationEventDTO
    characters: list[str]
    phase_rarity: float
    pair_importance: float


@dataclass(slots=True)
class LifecycleAtom:
    """角色生命周期原子信号。"""

    anchor_chunk_id: int
    progress: float
    phase_name: TimelinePhaseName
    lifecycle_event: LifecycleEventDTO
    character_importance: float


def calculate_tension_percentile(
    tension_score: float,
    all_tensions: list[float],
) -> int:
    """
    计算张力百分位排名。

    Args:
        tension_score: 当前张力分数
        all_tensions: 所有张力分数列表

    Returns:
        百分位排名 (0-100)
    """
    if not all_tensions:
        return 50

    count_le = sum(1 for tension in all_tensions if tension <= tension_score)
    percentile = int((count_le / len(all_tensions)) * 100)
    return min(percentile, 100)


# 2026-04-27，任务：时间轴合同重构
# 新建原因：时间轴节点数量不再固定 10/20，而是按小说篇幅自适应预算，
# 让 30 chunk 与 250 chunk 的时间轴不再共享同一硬上限。
def compute_timeline_node_budget(total_chunks: int) -> TimelineBudget:
    if total_chunks <= 40:
        return TimelineBudget(min_nodes=8, target_nodes=12, max_nodes=16)
    if total_chunks <= 120:
        return TimelineBudget(min_nodes=10, target_nodes=16, max_nodes=24)
    if total_chunks <= 240:
        return TimelineBudget(min_nodes=12, target_nodes=24, max_nodes=32)
    return TimelineBudget(min_nodes=14, target_nodes=30, max_nodes=40)


def compute_four_phases(
    tension_scores: list[float],
    chunk_ids: list[int],
) -> list[NarrativePhase]:
    """
    计算四阶段划分（多峰模型）。

    基于 Freytag 金字塔理论 + 网络小说多波次叠加结构，使用局部峰值
    检测确定高潮位置，而非单一全局峰值。
    """
    if not tension_scores or not chunk_ids:
        return []

    total = len(tension_scores)
    min_phase_length = 1

    if total < 20:
        boundary_1 = max(1, min(int(total * 0.15), total - 3))
        boundary_2 = max(boundary_1 + 1, min(int(total * 0.50), total - 2))
        boundary_3 = max(boundary_2 + 1, min(int(total * 0.80), total - 2))
        return [
            NarrativePhase("引入期", chunk_ids[0], chunk_ids[boundary_1], (boundary_1 + 1) / total),
            NarrativePhase(
                "发展期",
                chunk_ids[boundary_1 + 1],
                chunk_ids[boundary_2],
                (boundary_2 - boundary_1) / total,
            ),
            NarrativePhase(
                "高潮期",
                chunk_ids[boundary_2 + 1],
                chunk_ids[boundary_3],
                (boundary_3 - boundary_2) / total,
            ),
            NarrativePhase("收束期", chunk_ids[boundary_3 + 1], chunk_ids[-1], (total - boundary_3 - 1) / total),
        ]

    local_peaks = find_local_peaks(tension_scores, total)
    half_idx = total // 2

    if local_peaks:
        late_peaks = [peak for peak in local_peaks if peak >= half_idx]
        if late_peaks:
            peak_idx = max(late_peaks, key=lambda idx: tension_scores[idx])
        else:
            peak_idx = local_peaks[-1]
    else:
        logger.warning("No local peaks found in tension_scores, falling back to global peak")
        peak_idx = find_global_peak(tension_scores)

    if peak_idx == 0:
        valley_idx = max(min_phase_length, int(total * 0.15))
    else:
        before_peak = tension_scores[:peak_idx]
        valley_idx = max(min_phase_length, min(range(len(before_peak)), key=lambda idx: before_peak[idx]))

    max_climax_radius = int(total * 0.10)
    climax_radius = min(max(3, int(total * 0.05)), max_climax_radius)
    climax_start = max(valley_idx + min_phase_length, peak_idx - climax_radius)
    climax_end = min(total - 1 - min_phase_length, peak_idx + climax_radius)

    valley_idx = min(valley_idx, climax_start - min_phase_length)
    valley_idx = max(valley_idx, min_phase_length)

    phases: list[NarrativePhase] = []
    phases.append(NarrativePhase("引入期", chunk_ids[0], chunk_ids[valley_idx], (valley_idx + 1) / total))

    dev_start_idx = valley_idx + 1
    dev_end_idx = climax_start - 1
    if dev_end_idx >= dev_start_idx:
        phases.append(
            NarrativePhase(
                "发展期",
                chunk_ids[dev_start_idx],
                chunk_ids[dev_end_idx],
                (dev_end_idx - dev_start_idx + 1) / total,
            )
        )
    else:
        phases.append(NarrativePhase("发展期", chunk_ids[valley_idx], chunk_ids[valley_idx], 0.0))

    phases.append(
        NarrativePhase(
            "高潮期",
            chunk_ids[climax_start],
            chunk_ids[climax_end],
            (climax_end - climax_start + 1) / total,
        )
    )

    if climax_end < total - 1 - min_phase_length:
        phases.append(
            NarrativePhase(
                "收束期",
                chunk_ids[climax_end + 1],
                chunk_ids[-1],
                (total - climax_end - 1) / total,
            )
        )
    else:
        phases.append(NarrativePhase("收束期", chunk_ids[climax_end], chunk_ids[climax_end], 0.0))

    return phases


def convert_to_timeline_phases(phases: list[NarrativePhase]) -> list[TimelinePhaseDTO]:
    """将内部 NarrativePhase 转换为 TimelinePhaseDTO。"""
    result: list[TimelinePhaseDTO] = []
    for phase in phases:
        if phase.name in ("引入期", "发展期", "高潮期", "收束期"):
            name = cast(TimelinePhaseName, phase.name)
        else:
            name = "引入期"
        result.append(TimelinePhaseDTO(name=name, start=phase.start, end=phase.end, ratio=round(phase.ratio, 4)))
    return result


def compute_importance_score(score_breakdown: dict[str, float]) -> tuple[float, ImportanceLevel]:
    """
    根据分项得分计算节点总分与等级。

    Args:
        score_breakdown: 节点分项得分

    Returns:
        (importance_score, level): 总分与级别
    """
    score = round(sum(score_breakdown.values()), 2)
    if score >= 6.5:
        level: ImportanceLevel = 1
    elif score >= 4.0:
        level = 2
    else:
        level = 3
    return score, level


def _resolve_timeline_authority_contract(timeline_view: Any) -> tuple[list[Any], list[Any], dict[int, str]]:
    """
    Validate the authority-backed timeline contract before building timeline plans.
    """

    character_entities = list(timeline_view.character_entities)
    entity_lifecycles = list(timeline_view.entity_lifecycles)
    relation_events = list(timeline_view.relation_events)

    for slice_name, items in {
        "character_entities": character_entities,
        "entity_lifecycles": entity_lifecycles,
        "relation_events": relation_events,
    }.items():
        for item in items:
            missing_fields = [
                field_name
                for field_name in TIMELINE_AUTHORITY_DEPENDENCY_FIELDS[slice_name]
                if not hasattr(item, field_name)
            ]
            if missing_fields:
                raise TimelineAuthorityContractError(
                    f"TimelineAuthorityView.{slice_name} is missing required fields: {', '.join(missing_fields)}"
                )

    if any(entity.entity_type != "character" for entity in character_entities):
        raise TimelineAuthorityContractError(
            "TimelineAuthorityView.character_entities must contain only character entities"
        )

    entity_ids = [getattr(entity, "entity_id", None) for entity in character_entities]
    if any(entity_id is None for entity_id in entity_ids):
        raise TimelineAuthorityContractError("TimelineAuthorityView.character_entities must provide non-null entity_id")
    if len(set(entity_ids)) != len(entity_ids):
        raise TimelineAuthorityContractError("TimelineAuthorityView.character_entities must not duplicate entity_id")

    character_map = {
        int(entity.entity_id): entity for entity in character_entities if getattr(entity, "entity_id", None) is not None
    }
    lifecycle_ids = [getattr(lifecycle, "entity_id", None) for lifecycle in entity_lifecycles]
    if any(lifecycle_id is None for lifecycle_id in lifecycle_ids):
        raise TimelineAuthorityContractError("TimelineAuthorityView.entity_lifecycles must provide non-null entity_id")
    if len(set(lifecycle_ids)) != len(lifecycle_ids):
        raise TimelineAuthorityContractError("TimelineAuthorityView.entity_lifecycles must not duplicate entity_id")

    lifecycle_map = {int(lifecycle.entity_id): lifecycle for lifecycle in entity_lifecycles}
    character_ids = set(character_map)

    for lifecycle in entity_lifecycles:
        if lifecycle.entity_type != "character":
            raise TimelineAuthorityContractError(
                "TimelineAuthorityView.entity_lifecycles must contain only character lifecycles"
            )
        if lifecycle.entity_id not in character_ids:
            raise TimelineAuthorityContractError(
                "TimelineAuthorityView.entity_lifecycles must align with character_entities"
            )

    if set(lifecycle_map) != character_ids:
        raise TimelineAuthorityContractError(
            "TimelineAuthorityView.entity_lifecycles must exactly align with character_entities"
        )

    for entity_id, entity in character_map.items():
        lifecycle = lifecycle_map[entity_id]
        if lifecycle.name != entity.name:
            raise TimelineAuthorityContractError(
                "TimelineAuthorityView.entity_lifecycles names must match character_entities"
            )

    for event in relation_events:
        if event.from_entity_id not in character_ids or event.to_entity_id not in character_ids:
            raise TimelineAuthorityContractError(
                "TimelineAuthorityView.relation_events must stay inside the character subgraph"
            )
        if getattr(event, "change_type", None) not in RELATION_CHANGE_WEIGHTS:
            raise TimelineAuthorityContractError(
                "TimelineAuthorityView.relation_events must expose only meaningful relation changes"
            )

    return entity_lifecycles, relation_events, {entity_id: entity.name for entity_id, entity in character_map.items()}


# 2026-04-27，任务：时间轴合同重构
# 新建原因：把 authority contract 校验后的 view 收口成 timeline 专用输入，
# 避免 route/export 继续依赖 TimelineAuthorityView 的原始形状。
def _adapt_timeline_authority_view(timeline_view: TimelineAuthorityView) -> TimelineAuthorityData:
    entity_lifecycles, relation_events, entity_name_map = _resolve_timeline_authority_contract(timeline_view)
    return TimelineAuthorityData(
        entity_lifecycles=entity_lifecycles,
        relation_events=relation_events,
        entity_name_map=entity_name_map,
    )


# 2026-04-27，任务：时间轴合同重构
# 新建原因：把张力曲线长度校正逻辑独立出来，确保 timeline atom 计算只面对与 chunk 对齐的张力数组。
def _normalize_tension_scores(
    chunk_curves: list[Any] | None,
    total_chunks: int,
) -> list[float]:
    if chunk_curves:
        tension_scores = [
            row.tension_composite if row and row.tension_composite is not None else 0.5 for row in chunk_curves
        ]
    else:
        tension_scores = [0.5] * total_chunks

    if len(tension_scores) < total_chunks:
        tension_scores.extend([0.5] * (total_chunks - len(tension_scores)))
    elif len(tension_scores) > total_chunks:
        tension_scores = tension_scores[:total_chunks]

    return tension_scores


# 2026-04-27，任务：时间轴合同重构
# 新建原因：用具名快照替代函数内临时结构，明确标注数据到 plot atom 的适配边界。
def _build_timeline_annotation_map(raw_annotations: list[Any]) -> dict[int, TimelineAnnotationSnapshot]:
    if not raw_annotations:
        return {}

    annotation_map: dict[int, TimelineAnnotationSnapshot] = {}
    for row in raw_annotations:
        annotation_map[row.chunk_id] = TimelineAnnotationSnapshot(
            chunk_id=row.chunk_id,
            event_type=row.event_type if row.event_type else "",
            cliffhanger=row.cliffhanger if row.cliffhanger is not None else False,
            pivot_moment=row.pivot_moment if row.pivot_moment is not None else False,
            emotional_valence=row.emotional_valence if row.emotional_valence else "",
        )
    return annotation_map


# 2026-04-27，任务：时间轴合同重构
# 新建原因：统一装载 chunk / summary / annotation / tension 输入，避免 timeline 新引擎继续散落访问 repository。
def _load_timeline_source_data(
    run_id: str,
    chunk_repo: Any,
    annotation_repo: Any,
    stats_repo: Any,
) -> TimelineSourceData:
    chunk_texts = chunk_repo.fetch_chunk_texts(run_id)
    if not chunk_texts:
        raise TimelineDataUnavailableError(f"No chunks found for run {run_id}")

    chunk_ids = [chunk_id for chunk_id, _ in chunk_texts]
    total_chunks = len(chunk_ids)
    chunk_id_to_idx = {chunk_id: idx for idx, chunk_id in enumerate(chunk_ids)}

    chunk_curves = stats_repo.fetch_chunk_curves_full(run_id)
    tension_scores = _normalize_tension_scores(chunk_curves, total_chunks)
    summary_map = {row.chunk_id: row.summary for row in chunk_repo.fetch_chunk_summaries(run_id)}
    annotation_map = _build_timeline_annotation_map(annotation_repo.fetch_chunk_annotations_full(run_id))

    return TimelineSourceData(
        chunk_texts=chunk_texts,
        chunk_ids=chunk_ids,
        chunk_id_to_idx=chunk_id_to_idx,
        total_chunks=total_chunks,
        tension_scores=tension_scores,
        summary_map=summary_map,
        annotation_map=annotation_map,
    )


def _resolve_phase_name(chunk_id: int, phases: list[TimelinePhaseDTO]) -> TimelinePhaseName:
    for phase in phases:
        if phase.start <= chunk_id <= phase.end:
            return phase.name
    return phases[-1].name if phases else "引入期"


def _build_character_importance_map(
    source_data: TimelineSourceData,
    authority_data: TimelineAuthorityData,
) -> dict[int, float]:
    relation_counterpart_map: dict[int, set[int]] = {}
    relation_event_count_map: dict[int, int] = {}
    for event in authority_data.relation_events:
        relation_counterpart_map.setdefault(event.from_entity_id, set()).add(event.to_entity_id)
        relation_counterpart_map.setdefault(event.to_entity_id, set()).add(event.from_entity_id)
        relation_event_count_map[event.from_entity_id] = relation_event_count_map.get(event.from_entity_id, 0) + 1
        relation_event_count_map[event.to_entity_id] = relation_event_count_map.get(event.to_entity_id, 0) + 1

    importance_map: dict[int, float] = {}
    for lifecycle in authority_data.entity_lifecycles:
        if lifecycle.entity_id is None:
            continue
        first_seen_chunk = lifecycle.first_seen_chunk if lifecycle.first_seen_chunk is not None else 0
        last_seen_chunk = lifecycle.last_seen_chunk if lifecycle.last_seen_chunk is not None else first_seen_chunk
        span = max(last_seen_chunk - first_seen_chunk + 1, 1)
        span_score = span / max(source_data.total_chunks, 1) * 3.0
        degree_score = len(relation_counterpart_map.get(lifecycle.entity_id, set())) * 0.6
        relation_event_score = relation_event_count_map.get(lifecycle.entity_id, 0) * 0.35
        importance_map[lifecycle.entity_id] = round(span_score + degree_score + relation_event_score, 2)

    return importance_map


# 2026-04-27，任务：时间轴合同重构
# 新建原因：plot / relation / lifecycle 的选择逻辑完全不同，先拆成原子信号，
# 再进入统一节点规划层，避免再次退回 “每个 chunk 一个节点” 的旧模型。
def build_timeline_atoms(
    source_data: TimelineSourceData,
    authority_data: TimelineAuthorityData,
    phases: list[TimelinePhaseDTO],
) -> tuple[list[PlotAtom], list[RelationAtom], list[LifecycleAtom]]:
    phase_names_by_chunk = {
        chunk_id: _resolve_phase_name(chunk_id, phases)
        for chunk_id in source_data.chunk_ids
    }
    character_importance_map = _build_character_importance_map(source_data, authority_data)

    plot_atoms: list[PlotAtom] = []
    for index, (chunk_id, text) in enumerate(source_data.chunk_texts):
        annotation = source_data.annotation_map.get(chunk_id)
        summary = source_data.summary_map.get(chunk_id, "")
        if not summary:
            summary = text[:30] + "..." if len(text) > 30 else text

        characters = sorted(
            {
                lifecycle.name
                for lifecycle in authority_data.entity_lifecycles
                if lifecycle.first_seen_chunk == chunk_id or lifecycle.last_seen_chunk == chunk_id
            }
        )
        plot_atoms.append(
            PlotAtom(
                anchor_chunk_id=chunk_id,
                progress=index / (source_data.total_chunks - 1) if source_data.total_chunks > 1 else 0.0,
                summary=summary,
                phase_name=phase_names_by_chunk[chunk_id],
                characters=characters,
                event_type=annotation.event_type if annotation else "",
                emotional_valence=annotation.emotional_valence if annotation else "",
                tension_score=source_data.tension_scores[index],
                tension_percentile=calculate_tension_percentile(
                    source_data.tension_scores[index],
                    source_data.tension_scores,
                ),
                is_pivot=annotation.pivot_moment if annotation else False,
                is_cliffhanger=annotation.cliffhanger if annotation else False,
            )
        )

    relation_phase_counts: dict[str, int] = {}
    for relation_event in authority_data.relation_events:
        phase_name = phase_names_by_chunk.get(relation_event.chunk_id, "引入期")
        relation_phase_counts[phase_name] = relation_phase_counts.get(phase_name, 0) + 1

    max_phase_relation_count = max(relation_phase_counts.values(), default=1)
    relation_atoms: list[RelationAtom] = []
    for relation_event in authority_data.relation_events:
        chunk_index = source_data.chunk_id_to_idx.get(relation_event.chunk_id)
        if chunk_index is None:
            continue
        phase_name = phase_names_by_chunk.get(relation_event.chunk_id, "引入期")
        from_name = authority_data.entity_name_map.get(
            relation_event.from_entity_id,
            str(relation_event.from_entity_id),
        )
        to_name = authority_data.entity_name_map.get(
            relation_event.to_entity_id,
            str(relation_event.to_entity_id),
        )
        relation_event_dto = RelationEventDTO(
            relation_event_id=int(relation_event.relation_event_id),
            from_char=from_name,
            to_char=to_name,
            relation_type=relation_event.relation_type,
            change_type=cast(Literal["新建", "强化", "弱化", "断裂"], relation_event.change_type),
            evidence=relation_event.evidence,
            confidence=relation_event.confidence,
            directionality=relation_event.directionality,
        )
        phase_rarity = 1.0 - (
            relation_phase_counts.get(phase_name, 0) / max(max_phase_relation_count, 1)
        )
        pair_importance = round(
            (
                character_importance_map.get(relation_event.from_entity_id, 0.0)
                + character_importance_map.get(relation_event.to_entity_id, 0.0)
            )
            / 2,
            2,
        )
        relation_atoms.append(
            RelationAtom(
                anchor_chunk_id=relation_event.chunk_id,
                progress=chunk_index / (source_data.total_chunks - 1) if source_data.total_chunks > 1 else 0.0,
                phase_name=phase_name,
                relation_event=relation_event_dto,
                characters=sorted({from_name, to_name}),
                phase_rarity=round(phase_rarity, 2),
                pair_importance=pair_importance,
            )
        )

    lifecycle_atoms: list[LifecycleAtom] = []
    for lifecycle in authority_data.entity_lifecycles:
        if lifecycle.entity_id is None:
            continue
        if lifecycle.first_seen_chunk is not None:
            lifecycle_atoms.append(
                LifecycleAtom(
                    anchor_chunk_id=lifecycle.first_seen_chunk,
                    progress=(
                        source_data.chunk_id_to_idx.get(lifecycle.first_seen_chunk, 0) / (source_data.total_chunks - 1)
                        if source_data.total_chunks > 1
                        else 0.0
                    ),
                    phase_name=phase_names_by_chunk.get(lifecycle.first_seen_chunk, "引入期"),
                    lifecycle_event=LifecycleEventDTO(
                        entity_id=lifecycle.entity_id,
                        character_name=lifecycle.name,
                        lifecycle_type="entry",
                    ),
                    character_importance=character_importance_map.get(lifecycle.entity_id, 0.0),
                )
            )
        if lifecycle.last_seen_chunk is not None:
            lifecycle_atoms.append(
                LifecycleAtom(
                    anchor_chunk_id=lifecycle.last_seen_chunk,
                    progress=(
                        source_data.chunk_id_to_idx.get(lifecycle.last_seen_chunk, 0) / (source_data.total_chunks - 1)
                        if source_data.total_chunks > 1
                        else 0.0
                    ),
                    phase_name=phase_names_by_chunk.get(lifecycle.last_seen_chunk, "收束期"),
                    lifecycle_event=LifecycleEventDTO(
                        entity_id=lifecycle.entity_id,
                        character_name=lifecycle.name,
                        lifecycle_type="exit",
                    ),
                    character_importance=character_importance_map.get(lifecycle.entity_id, 0.0),
                )
            )

    return plot_atoms, relation_atoms, lifecycle_atoms


def _build_plot_score_breakdown(atom: PlotAtom) -> dict[str, float]:
    return {
        "pivot": 3.0 if atom.is_pivot else 0.0,
        "cliffhanger": 2.0 if atom.is_cliffhanger else 0.0,
        "tension": round(atom.tension_percentile / 50, 2),
        "event_type": PLOT_EVENT_TYPE_WEIGHTS.get(atom.event_type, 0.0),
        "emotional_valence": EMOTIONAL_VALENCE_WEIGHTS.get(atom.emotional_valence, 0.0),
    }


def _build_relation_score_breakdown(atom: RelationAtom) -> dict[str, float]:
    return {
        "change_type_weight": RELATION_CHANGE_WEIGHTS.get(atom.relation_event.change_type, 0.0),
        "pair_importance": atom.pair_importance,
        "phase_rarity": round(atom.phase_rarity, 2),
        "duplicate_penalty": 0.0,
    }


def _build_lifecycle_score_breakdown(atom: LifecycleAtom) -> dict[str, float]:
    return {
        "character_importance": round(atom.character_importance, 2),
        "entry_exit_bonus": 1.4 if atom.lifecycle_event.lifecycle_type == "entry" else 1.2,
    }


# 2026-04-27，任务：时间轴合同重构
# 新建原因：节点规划层负责把不同 atom 映射为统一节点 DTO，并显式生成稳定 node_id，
# 让 route / export / frontend 全部摆脱 chunk_id 唯一节点假设。
def compose_timeline_nodes(
    plot_atoms: list[PlotAtom],
    relation_atoms: list[RelationAtom],
    lifecycle_atoms: list[LifecycleAtom],
) -> list[TimelineNodeDTO]:
    nodes: list[TimelineNodeDTO] = []

    for atom in plot_atoms:
        score_breakdown = _build_plot_score_breakdown(atom)
        importance_score, level = compute_importance_score(score_breakdown)
        nodes.append(
            TimelineNodeDTO(
                node_id=f"plot:{atom.anchor_chunk_id}",
                anchor_chunk_id=atom.anchor_chunk_id,
                progress=round(atom.progress, 4),
                importance_score=importance_score,
                level=level,
                summary=atom.summary,
                characters=atom.characters,
                phase_name=atom.phase_name,
                node_type="plot",
                node_subtype="plot",
                score_breakdown=score_breakdown,
                plot_flags=PlotFlagsDTO(
                    is_pivot=atom.is_pivot,
                    is_cliffhanger=atom.is_cliffhanger,
                    tension_percentile=atom.tension_percentile,
                ),
            )
        )

    for relation_atom in relation_atoms:
        score_breakdown = _build_relation_score_breakdown(relation_atom)
        importance_score, level = compute_importance_score(score_breakdown)
        nodes.append(
            TimelineNodeDTO(
                node_id=f"relation:{relation_atom.relation_event.relation_event_id}",
                anchor_chunk_id=relation_atom.anchor_chunk_id,
                progress=round(relation_atom.progress, 4),
                importance_score=importance_score,
                level=level,
                summary=(
                    f"{relation_atom.relation_event.from_char}与{relation_atom.relation_event.to_char}"
                    f"{relation_atom.relation_event.change_type}{relation_atom.relation_event.relation_type}"
                ),
                characters=relation_atom.characters,
                phase_name=relation_atom.phase_name,
                node_type="relation",
                node_subtype=cast(TimelineNodeSubtype, relation_atom.relation_event.change_type),
                score_breakdown=score_breakdown,
                relation_events=[relation_atom.relation_event],
            )
        )

    for lifecycle_atom in lifecycle_atoms:
        score_breakdown = _build_lifecycle_score_breakdown(lifecycle_atom)
        importance_score, level = compute_importance_score(score_breakdown)
        lifecycle_type = lifecycle_atom.lifecycle_event.lifecycle_type
        nodes.append(
            TimelineNodeDTO(
                node_id=(
                    f"lifecycle:{lifecycle_type}:"
                    f"{lifecycle_atom.lifecycle_event.entity_id}:{lifecycle_atom.anchor_chunk_id}"
                ),
                anchor_chunk_id=lifecycle_atom.anchor_chunk_id,
                progress=round(lifecycle_atom.progress, 4),
                importance_score=importance_score,
                level=level,
                summary=(
                    f"{lifecycle_atom.lifecycle_event.character_name}首次登场"
                    if lifecycle_type == "entry"
                    else f"{lifecycle_atom.lifecycle_event.character_name}退场"
                ),
                characters=[lifecycle_atom.lifecycle_event.character_name],
                phase_name=lifecycle_atom.phase_name,
                node_type="lifecycle",
                node_subtype=cast(TimelineNodeSubtype, lifecycle_type),
                score_breakdown=score_breakdown,
                lifecycle_events=[lifecycle_atom.lifecycle_event],
            )
        )

    return nodes


def _node_sort_key(node: TimelineNodeDTO) -> tuple[float, int, str]:
    subtype_rank = {
        "plot": 0,
        "entry": 1,
        "新建": 2,
        "强化": 3,
        "弱化": 4,
        "断裂": 5,
        "exit": 6,
    }
    return (node.progress, node.anchor_chunk_id, f"{subtype_rank.get(node.node_subtype, 9)}:{node.node_id}")


def _select_best_plot_node(nodes: list[TimelineNodeDTO], anchor_chunk_id: int) -> TimelineNodeDTO | None:
    plot_nodes = [node for node in nodes if node.node_type == "plot" and node.anchor_chunk_id == anchor_chunk_id]
    if not plot_nodes:
        return None
    return max(plot_nodes, key=lambda node: node.importance_score)


def _relation_pair_signature(node: TimelineNodeDTO) -> tuple[str, str, str, str, str] | None:
    """
    2026-04-27，任务：fix-timeline-relation-dedup-signature
    修改原因：relation 节点的近邻去重既要压掉真正重复的同类事件，
    也不能把同一对角色在短距离内发生的不同变化（如新建->断裂、双向 directed 事件）误吞掉。
    """
    if not node.relation_events:
        return None
    event = node.relation_events[0]
    if event.directionality == "symmetric":
        left_name, right_name = tuple(sorted((event.from_char, event.to_char)))
    else:
        left_name, right_name = event.from_char, event.to_char
    return (
        left_name,
        right_name,
        event.relation_type,
        event.change_type,
        event.directionality or "unknown",
    )


def _lifecycle_signature(node: TimelineNodeDTO) -> tuple[int, str] | None:
    if not node.lifecycle_events:
        return None
    event = node.lifecycle_events[0]
    return (event.entity_id, event.lifecycle_type)


def _has_selection_conflict(candidate: TimelineNodeDTO, selected: list[TimelineNodeDTO]) -> bool:
    for existing in selected:
        if (
            candidate.node_type == "plot"
            and existing.node_type == "plot"
            and candidate.node_subtype == existing.node_subtype
            and abs(candidate.anchor_chunk_id - existing.anchor_chunk_id) <= 2
        ):
            return True

        if candidate.node_type == "relation" and existing.node_type == "relation":
            candidate_signature = _relation_pair_signature(candidate)
            existing_signature = _relation_pair_signature(existing)
            if (
                candidate_signature is not None
                and existing_signature is not None
                and candidate_signature == existing_signature
                and abs(candidate.anchor_chunk_id - existing.anchor_chunk_id) <= 3
            ):
                return True

        if candidate.node_type == "lifecycle" and existing.node_type == "lifecycle":
            candidate_lifecycle_signature = _lifecycle_signature(candidate)
            existing_lifecycle_signature = _lifecycle_signature(existing)
            if (
                candidate_lifecycle_signature is not None
                and existing_lifecycle_signature == candidate_lifecycle_signature
            ):
                return True

    return False


def _maybe_add_node(selected: list[TimelineNodeDTO], candidate: TimelineNodeDTO | None, max_nodes: int) -> bool:
    if candidate is None:
        return False
    if len(selected) >= max_nodes:
        return False
    if any(existing.node_id == candidate.node_id for existing in selected):
        return False
    if _has_selection_conflict(candidate, selected):
        return False
    selected.append(candidate)
    return True


def _pick_phase_coverage_nodes(
    nodes: list[TimelineNodeDTO],
    phases: list[TimelinePhaseDTO],
    selected: list[TimelineNodeDTO],
    max_nodes: int,
) -> None:
    type_priority = {"plot": 0, "relation": 1, "lifecycle": 2}
    for phase in phases:
        phase_nodes = [node for node in nodes if node.phase_name == phase.name]
        phase_nodes.sort(
            key=lambda node: (
                type_priority.get(node.node_type, 9),
                -node.importance_score,
                node.anchor_chunk_id,
            )
        )
        for node in phase_nodes:
            if _maybe_add_node(selected, node, max_nodes):
                break


def _type_quota_map(target_nodes: int) -> dict[TimelineNodeType, int]:
    plot_quota = max(3, round(target_nodes * 0.4))
    relation_quota = max(2, round(target_nodes * 0.35))
    lifecycle_quota = max(2, target_nodes - plot_quota - relation_quota)
    return {
        "plot": plot_quota,
        "relation": relation_quota,
        "lifecycle": lifecycle_quota,
    }


# 2026-04-27，任务：时间轴合同重构
# 新建原因：新的选择器需要同时满足 budget、phase 覆盖、类型配额与近距去重；
# 它不再围绕“每个 chunk 选一个 candidate”，而是直接对规划后的节点集合做筛选。
def select_timeline_nodes(
    nodes: list[TimelineNodeDTO],
    chunk_ids: list[int],
    tension_scores: list[float],
    phases: list[TimelinePhaseDTO],
    budget: TimelineBudget,
) -> list[TimelineNodeDTO]:
    if not nodes or not chunk_ids:
        return []

    selected: list[TimelineNodeDTO] = []
    peak_idx = find_global_peak(tension_scores) if tension_scores else 0
    start_chunk_id = chunk_ids[0]
    end_chunk_id = chunk_ids[-1]
    peak_chunk_id = chunk_ids[peak_idx]

    _maybe_add_node(selected, _select_best_plot_node(nodes, start_chunk_id), budget.max_nodes)
    _maybe_add_node(selected, _select_best_plot_node(nodes, end_chunk_id), budget.max_nodes)
    _maybe_add_node(selected, _select_best_plot_node(nodes, peak_chunk_id), budget.max_nodes)

    _pick_phase_coverage_nodes(nodes, phases, selected, budget.max_nodes)

    quota_map = _type_quota_map(budget.target_nodes)
    sorted_nodes = sorted(nodes, key=lambda node: (-node.importance_score, node.anchor_chunk_id, node.node_id))
    type_counts = {
        "plot": sum(1 for node in selected if node.node_type == "plot"),
        "relation": sum(1 for node in selected if node.node_type == "relation"),
        "lifecycle": sum(1 for node in selected if node.node_type == "lifecycle"),
    }
    for node in sorted_nodes:
        if len(selected) >= budget.target_nodes:
            break
        if type_counts[node.node_type] >= quota_map[node.node_type]:
            continue
        if _maybe_add_node(selected, node, budget.max_nodes):
            type_counts[node.node_type] += 1

    for node in sorted_nodes:
        if len(selected) >= budget.target_nodes:
            break
        _maybe_add_node(selected, node, budget.max_nodes)

    if len(selected) < budget.min_nodes:
        for node in sorted_nodes:
            if len(selected) >= budget.min_nodes:
                break
            if any(existing.node_id == node.node_id for existing in selected):
                continue
            selected.append(node)

    selected.sort(key=_node_sort_key)
    return selected[: budget.max_nodes]


def serialize_timeline_node(node: TimelineNodeDTO) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "node_id": node.node_id,
        "anchor_chunk_id": node.anchor_chunk_id,
        "progress": round(node.progress, 4),
        "importance_score": round(node.importance_score, 2),
        "level": node.level,
        "summary": node.summary,
        "characters": node.characters,
        "phase_name": node.phase_name,
        "node_type": node.node_type,
        "node_subtype": node.node_subtype,
        "score_breakdown": {key: round(value, 2) for key, value in node.score_breakdown.items()},
        "plot_flags": None,
        "relation_events": None,
        "lifecycle_events": None,
    }
    if node.plot_flags is not None:
        payload["plot_flags"] = {
            "is_pivot": node.plot_flags.is_pivot,
            "is_cliffhanger": node.plot_flags.is_cliffhanger,
            "tension_percentile": node.plot_flags.tension_percentile,
        }
    if node.relation_events is not None:
        payload["relation_events"] = [
            {
                "relation_event_id": event.relation_event_id,
                "from_char": event.from_char,
                "to_char": event.to_char,
                "relation_type": event.relation_type,
                "change_type": event.change_type,
                "evidence": event.evidence,
                "confidence": event.confidence,
                "directionality": event.directionality,
            }
            for event in node.relation_events
        ]
    if node.lifecycle_events is not None:
        payload["lifecycle_events"] = [
            {
                "entity_id": event.entity_id,
                "character_name": event.character_name,
                "lifecycle_type": event.lifecycle_type,
            }
            for event in node.lifecycle_events
        ]
    return payload


def serialize_timeline_phases(phases: list[TimelinePhaseDTO]) -> list[dict[str, Any]]:
    return [
        {
            "name": phase.name,
            "start": phase.start,
            "end": phase.end,
            "ratio": round(phase.ratio, 4),
        }
        for phase in phases
    ]


# 2026-04-27，任务：时间轴合同重构
# 新建原因：新的 timeline 共享入口直接返回“已选节点 + 阶段 + 曲线”，
# route 与 export 不再感知旧 candidate/select/convert 三段式内部实现。
def build_timeline_plan(
    run_id: str,
    chunk_repo: Any,
    annotation_repo: Any,
    stats_repo: Any,
    timeline_view: TimelineAuthorityView,
) -> TimelinePlanBuildResult:
    source_data = _load_timeline_source_data(run_id, chunk_repo, annotation_repo, stats_repo)
    authority_data = _adapt_timeline_authority_view(timeline_view)
    phases = convert_to_timeline_phases(compute_four_phases(source_data.tension_scores, source_data.chunk_ids))
    plot_atoms, relation_atoms, lifecycle_atoms = build_timeline_atoms(source_data, authority_data, phases)
    all_nodes = compose_timeline_nodes(plot_atoms, relation_atoms, lifecycle_atoms)
    budget = compute_timeline_node_budget(source_data.total_chunks)
    selected_nodes = select_timeline_nodes(
        nodes=all_nodes,
        chunk_ids=source_data.chunk_ids,
        tension_scores=source_data.tension_scores,
        phases=phases,
        budget=budget,
    )
    return TimelinePlanBuildResult(
        nodes=selected_nodes,
        total_chunks=source_data.total_chunks,
        phases=phases,
        tension_curve=source_data.tension_scores,
    )
