"""
叙事时间轴核心算法模块。

创建时间: 2026-03-30
创建者: CodeBuddy
任务: refactor-session-management
说明: 提供时间轴节点重要性计算、四阶段划分、节点筛选功能

修改内容:
- 定义独立 DTO，解耦 API 模型依赖
- 使用 Literal 类型强化类型安全
- 修复四阶段边界逻辑
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast

from loguru import logger

from src.metrics.narrative_metrics import find_global_peak

# Literal 类型定义
TimelineNodeType = Literal["plot", "character_entry", "character_exit", "relation_change"]
TimelinePhaseName = Literal["引入期", "发展期", "高潮期", "收束期"]
ImportanceLevel = Literal[1, 2, 3]


# ==================== DTO 定义 ====================


@dataclass
class RelationChangeEventDTO:
    """关系变化事件 DTO"""

    from_char: str
    to_char: str
    relation_type: str
    change_type: str
    evidence: str | None = None


@dataclass
class TimelinePhaseDTO:
    """时间轴阶段 DTO"""

    name: TimelinePhaseName
    start: int
    end: int
    ratio: float


@dataclass
class TimelineNodeDTO:
    """时间轴节点 DTO"""

    chunk_id: int
    progress: float
    importance_score: float
    level: ImportanceLevel
    event: str
    characters: list[str] = field(default_factory=list)
    is_pivot: bool = False
    is_cliffhanger: bool = False
    tension_percentile: int = 50
    node_type: TimelineNodeType = "plot"
    relation_changes: list[RelationChangeEventDTO] | None = None
    character_entries: list[str] | None = None
    character_exits: list[str] | None = None


# ==================== 内部数据结构 ====================


@dataclass
class NarrativePhase:
    """叙事阶段内部数据结构"""

    name: str
    start: int
    end: int
    ratio: float


@dataclass
class TimelineCandidate:
    """时间轴候选节点内部数据结构"""

    chunk_id: int
    progress: float
    importance_score: float
    level: ImportanceLevel
    event: str
    characters: list[str]
    is_pivot: bool
    is_cliffhanger: bool
    tension_percentile: int
    node_type: TimelineNodeType
    relation_changes: list[RelationChangeEventDTO] | None = None
    character_entries: list[str] | None = None
    character_exits: list[str] | None = None


# ==================== 核心函数 ====================


def compute_importance_score(
    pivot_moment: bool,
    cliffhanger: bool,
    tension_composite: float,
    all_tensions: list[float],
    event_type: str,
    emotional_valence: str,
    has_relation_change: bool = False,
    has_character_entry: bool = False,
    has_character_exit: bool = False,
    is_major_character: bool = False,
) -> tuple[float, ImportanceLevel]:
    """
    计算节点重要性分数。

    分数构成:
    - 转折点: +3
    - 悬念: +2
    - 张力百分位: 0-2 (基于百分位排名 × 2)
    - 冲突事件: +1
    - 极端情感: +1
    - 关系变化: +2
    - 主要角色登场/退场: +2

    分级阈值:
    - ≥ 7 分: level 1 (重要)
    - 4-6 分: level 2 (较重要)
    - 0-3 分: level 3 (不重要)

    Args:
        pivot_moment: 是否为转折点
        cliffhanger: 是否为悬念点
        tension_composite: 张力综合分数
        all_tensions: 所有 chunk 的张力分数列表（用于计算百分位）
        event_type: 事件类型
        emotional_valence: 情感倾向
        has_relation_change: 是否有关系变化
        has_character_entry: 是否有角色登场
        has_character_exit: 是否有角色退场
        is_major_character: 是否为主要角色

    Returns:
        (importance_score, level): 重要性分数 (0-11) 和级别 (1-3)
    """
    score = 0.0

    if pivot_moment:
        score += 3
    if cliffhanger:
        score += 2

    if all_tensions:
        # 计算百分位排名
        percentile = sum(1 for t in all_tensions if t <= tension_composite) / len(all_tensions)
        score += percentile * 2

    if event_type == "冲突":
        score += 1
    if emotional_valence in ["strong_positive", "strong_negative"]:
        score += 1

    if has_relation_change:
        score += 2
    if (has_character_entry or has_character_exit) and is_major_character:
        score += 2

    # 分级
    if score >= 7:
        level: ImportanceLevel = 1
    elif score >= 4:
        level = 2
    else:
        level = 3

    return score, level


def compute_four_phases(
    tension_scores: list[float],
    chunk_ids: list[int],
) -> list[NarrativePhase]:
    """
    计算四阶段划分。

    基于 Freytag 金字塔理论，将叙事划分为四个阶段:
    - 引入期: 从开始到张力谷底
    - 发展期: 从谷底到高潮峰值前
    - 高潮期: 峰值周围区域
    - 收束期: 高潮后到结束

    边界保护:
    - MIN_PHASE_LENGTH = 1: 每个阶段至少 1 个 chunk
    - 高潮期半径: 至少 3 个 chunk，最多 5%（但不超过总长度的 10%）
    - 小说太短时 (< 20 chunks): 使用固定比例 15%-35%-30%-20%

    Args:
        tension_scores: 张力分数列表（与 chunk_ids 一一对应）
        chunk_ids: chunk ID 列表（按顺序排列，可能不连续）

    Returns:
        NarrativePhase 列表，按顺序包含引入期、发展期、高潮期、收束期
        始终返回 4 个阶段（极端情况下某些阶段可能为空，ratio=0）
    """
    if not tension_scores or not chunk_ids:
        return []

    total = len(tension_scores)
    MIN_PHASE_LENGTH = 1

    # 短小说固定比例划分
    if total < 20:
        # 计算边界索引（确保各阶段至少 1 个 chunk 且不越界）
        # b3 最大为 total - 2，因为后面要访问 chunk_ids[b3 + 1]
        b1 = max(1, min(int(total * 0.15), total - 3))  # 引入期结束
        b2 = max(b1 + 1, min(int(total * 0.50), total - 2))  # 发展期结束
        b3 = max(b2 + 1, min(int(total * 0.80), total - 2))  # 高潮期结束
        return [
            NarrativePhase("引入期", chunk_ids[0], chunk_ids[b1], (b1 + 1) / total),
            NarrativePhase("发展期", chunk_ids[b1 + 1], chunk_ids[b2], (b2 - b1) / total),
            NarrativePhase("高潮期", chunk_ids[b2 + 1], chunk_ids[b3], (b3 - b2) / total),
            NarrativePhase("收束期", chunk_ids[b3 + 1], chunk_ids[-1], (total - b3 - 1) / total),
        ]

    # 长小说基于张力曲线动态划分
    peak_idx = find_global_peak(tension_scores)

    if peak_idx == 0:
        valley_idx = max(MIN_PHASE_LENGTH, int(total * 0.15))
    else:
        before_peak = tension_scores[:peak_idx]
        valley_idx = max(MIN_PHASE_LENGTH, min(range(len(before_peak)), key=lambda i: before_peak[i]))

    # 高潮期半径：至少 3 个，最多 5%（但不超过总长度的 10%）
    max_climax_radius = int(total * 0.10)
    climax_radius = min(max(3, int(total * 0.05)), max_climax_radius)
    climax_start = max(valley_idx + MIN_PHASE_LENGTH, peak_idx - climax_radius)
    climax_end = min(total - 1 - MIN_PHASE_LENGTH, peak_idx + climax_radius)

    # 确保 valley_idx < climax_start，保留至少 MIN_PHASE_LENGTH 给发展期
    valley_idx = min(valley_idx, climax_start - MIN_PHASE_LENGTH)
    valley_idx = max(valley_idx, MIN_PHASE_LENGTH)

    phases: list[NarrativePhase] = []

    # 引入期（始终存在）
    phases.append(NarrativePhase("引入期", chunk_ids[0], chunk_ids[valley_idx], (valley_idx + 1) / total))

    # 发展期
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
        logger.warning(f"发展期被跳过: valley_idx={valley_idx}, climax_start={climax_start}, total={total}")
        # 退化处理：在引入期和高潮期之间插入空发展期
        phases.append(NarrativePhase("发展期", chunk_ids[valley_idx], chunk_ids[valley_idx], 0.0))

    # 高潮期（始终存在）
    phases.append(
        NarrativePhase(
            "高潮期",
            chunk_ids[climax_start],
            chunk_ids[climax_end],
            (climax_end - climax_start + 1) / total,
        )
    )

    # 收束期（始终存在，即使长度为0）
    if climax_end < total - 1 - MIN_PHASE_LENGTH:
        phases.append(
            NarrativePhase(
                "收束期",
                chunk_ids[climax_end + 1],
                chunk_ids[-1],
                (total - climax_end - 1) / total,
            )
        )
    else:
        # 退化处理：高潮期直接到结尾，收束期为空
        phases.append(NarrativePhase("收束期", chunk_ids[climax_end], chunk_ids[climax_end], 0.0))

    return phases


def select_timeline_nodes(
    candidates: list[TimelineCandidate],
    chunk_ids: list[int],
    tension_scores: list[float],
    major_character_entries: list[tuple[str, int]],  # [(char_name, first_chunk_idx), ...]
    relation_break_events: list[tuple[int, RelationChangeEventDTO]],  # [(chunk_idx, event), ...]
    min_nodes: int = 10,
    max_nodes: int = 20,
) -> list[TimelineCandidate]:
    """
    筛选时间轴节点。

    筛选规则:
    - 必选: 故事开始、故事结局、全局高潮、主要角色登场（去重）
    - 可选: 转折点、悬念点（限5个）、关系断裂
    - 补充: 当节点数不足 min_nodes 时，按重要性补充

    数量控制:
    - 最少 min_nodes 个节点（默认 10）
    - 最多 max_nodes 个节点（默认 20）
    - 必选节点超过 max_nodes 时，按重要性排序保留

    Args:
        candidates: 所有候选节点列表
        chunk_ids: chunk ID 列表（与 candidates 一一对应）
        tension_scores: 张力分数列表
        major_character_entries: 主要角色登场信息 [(角色名, 首次出现索引), ...]
        relation_break_events: 关系断裂事件 [(chunk索引, 事件), ...]
        min_nodes: 最少节点数
        max_nodes: 最多节点数

    Returns:
        筛选后的 TimelineCandidate 列表（按 progress 排序）
    """
    if not candidates:
        return []

    # 创建 chunk_id 到 candidate 的映射
    chunk_to_candidate: dict[int, TimelineCandidate] = {}
    for c in candidates:
        chunk_to_candidate[c.chunk_id] = c

    must_keep_chunks: set[int] = set()

    # 1. 故事开始（最高优先级）
    must_keep_chunks.add(chunk_ids[0])

    # 2. 故事结局
    must_keep_chunks.add(chunk_ids[-1])

    # 3. 全局高潮
    peak_idx = find_global_peak(tension_scores)
    must_keep_chunks.add(chunk_ids[peak_idx])

    # 4. 主要角色登场（去重：如果 chunk 已在必选集合中，跳过）
    for _char_name, first_idx in major_character_entries:
        real_chunk_id = chunk_ids[first_idx]
        if real_chunk_id not in must_keep_chunks:
            must_keep_chunks.add(real_chunk_id)

    # 5. 关系断裂节点
    break_chunk_ids: set[int] = set()
    for chunk_idx, _ in relation_break_events:
        break_chunk_ids.add(chunk_ids[chunk_idx])

    # 收集必选节点
    selected: list[TimelineCandidate] = []
    for chunk_id in must_keep_chunks:
        if chunk_id in chunk_to_candidate:
            selected.append(chunk_to_candidate[chunk_id])

    # 添加关系断裂节点（如果不超限）
    for chunk_id in break_chunk_ids:
        if chunk_id in chunk_to_candidate and chunk_id not in must_keep_chunks:
            if len(selected) < max_nodes:
                selected.append(chunk_to_candidate[chunk_id])

    # 添加转折点（按重要性排序）
    pivot_candidates = [c for c in candidates if c.is_pivot and c.chunk_id not in {s.chunk_id for s in selected}]
    pivot_candidates.sort(key=lambda x: x.importance_score, reverse=True)

    for c in pivot_candidates:
        if len(selected) >= max_nodes:
            break
        selected.append(c)

    # 添加悬念点（限 5 个，按重要性排序）
    cliffhanger_candidates = [
        c for c in candidates if c.is_cliffhanger and c.chunk_id not in {s.chunk_id for s in selected}
    ]
    cliffhanger_candidates.sort(key=lambda x: x.importance_score, reverse=True)

    for i, c in enumerate(cliffhanger_candidates):
        if i >= 5 or len(selected) >= max_nodes:
            break
        selected.append(c)

    # 补充节点（如果不足 min_nodes）
    if len(selected) < min_nodes:
        remaining = [c for c in candidates if c.chunk_id not in {s.chunk_id for s in selected}]
        remaining.sort(key=lambda x: x.importance_score, reverse=True)

        for c in remaining:
            if len(selected) >= min_nodes:
                break
            selected.append(c)

    # 保护逻辑：如果必选节点超过 max_nodes，按重要性排序保留
    if len(must_keep_chunks) > max_nodes:
        must_keep_list = list(must_keep_chunks)
        must_keep_candidates: list[TimelineCandidate] = [
            chunk_to_candidate[cid] for cid in must_keep_list if cid in chunk_to_candidate
        ]
        must_keep_candidates.sort(key=lambda x: x.importance_score, reverse=True)

        # 只保留前 max_nodes 个
        keep_chunk_ids = {c.chunk_id for c in must_keep_candidates[:max_nodes]}
        selected = [c for c in selected if c.chunk_id in keep_chunk_ids]

    # 按 progress 排序
    selected.sort(key=lambda x: x.progress)

    return selected


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

    count_le = sum(1 for t in all_tensions if t <= tension_score)
    percentile = int((count_le / len(all_tensions)) * 100)
    return min(percentile, 100)


def get_major_characters_by_span(
    entities: list[Any],
    top_n: int = 3,
) -> list[Any]:
    """
    基于活跃跨度获取主要角色。

    活跃跨度 = 角色在 chunk 序列中的最大索引 - 最小索引 + 1
    （注意：活跃跨度 ≠ 出现次数）

    Args:
        entities: GraphEntity 列表（或其他具有 first_seen_chunk/last_seen_chunk 属性的对象）
        top_n: 返回前 N 个主要角色

    Returns:
        按活跃跨度排序的主要角色列表
    """
    valid_entities = [
        e
        for e in entities
        if hasattr(e, "first_seen_chunk")
        and hasattr(e, "last_seen_chunk")
        and e.first_seen_chunk is not None
        and e.last_seen_chunk is not None
    ]

    # 计算活跃跨度
    def get_span(entity: Any) -> int:
        return entity.last_seen_chunk - entity.first_seen_chunk + 1

    sorted_entities = sorted(valid_entities, key=get_span, reverse=True)
    return sorted_entities[:top_n]


def convert_to_timeline_phases(phases: list[NarrativePhase]) -> list[TimelinePhaseDTO]:
    """
    将内部 NarrativePhase 转换为 TimelinePhaseDTO。

    Args:
        phases: NarrativePhase 列表

    Returns:
        TimelinePhaseDTO 列表
    """
    result: list[TimelinePhaseDTO] = []
    for p in phases:
        if p.name in ("引入期", "发展期", "高潮期", "收束期"):
            name = cast(TimelinePhaseName, p.name)
        else:
            name = "引入期"  # fallback
        result.append(
            TimelinePhaseDTO(
                name=name,
                start=p.start,
                end=p.end,
                ratio=round(p.ratio, 4),
            )
        )
    return result


def convert_to_timeline_nodes(candidates: list[TimelineCandidate]) -> list[TimelineNodeDTO]:
    """
    将内部 TimelineCandidate 转换为 TimelineNodeDTO。

    Args:
        candidates: TimelineCandidate 列表

    Returns:
        TimelineNodeDTO 列表
    """
    return [
        TimelineNodeDTO(
            chunk_id=c.chunk_id,
            progress=round(c.progress, 4),
            importance_score=round(c.importance_score, 2),
            level=c.level,
            event=c.event,
            characters=c.characters,
            is_pivot=c.is_pivot,
            is_cliffhanger=c.is_cliffhanger,
            tension_percentile=c.tension_percentile,
            node_type=c.node_type,
            relation_changes=c.relation_changes,
            character_entries=c.character_entries,
            character_exits=c.character_exits,
        )
        for c in candidates
    ]


def build_timeline_candidates(
    run_id: str,
    chunk_repo: Any,
    annotation_repo: Any,
    stats_repo: Any,
) -> tuple[
    list[TimelineCandidate],
    list[float],
    list[int],
    int,
    list[TimelinePhaseDTO],
    list[tuple[str, int]],
    list[tuple[int, RelationChangeEventDTO]],
]:
    """
    构建时间轴候选节点（共享函数）。

    统一 timeline.py 路由和 results_export_service.py 的数据获取 + 候选构建逻辑，
    消除两处 ~150 行的重复代码。

    数据获取全部通过 Repository 方法，不使用裸 session.query()。
    chunk_id 查找使用预构建 dict，O(1) 替代 list.index() O(N)。

    Args:
        run_id: 运行ID
        chunk_repo: ChunkRepository 实例
        annotation_repo: AnnotationRepository 实例
        stats_repo: StatsRepository 实例

    Returns:
        (candidates, tension_scores, chunk_ids, total_chunks, phases,
         major_character_entries, relation_break_events)
        调用方可据此继续执行 select_timeline_nodes + convert_to_timeline_nodes。

    Raises:
        ValueError: 无 chunk 数据时
    """
    from src.storage.repositories import GraphRepository

    graph_repo = GraphRepository(chunk_repo.session)

    # 获取 chunk 文本列表
    chunk_texts = chunk_repo.fetch_chunk_texts(run_id)
    if not chunk_texts:
        raise ValueError(f"No chunks found for run {run_id}")

    chunk_ids = [cid for cid, _ in chunk_texts]
    total_chunks = len(chunk_ids)

    # Fix-3: 预构建 chunk_id → index 映射，O(1) 替代 O(N)
    chunk_id_to_idx: dict[int, int] = {cid: idx for idx, cid in enumerate(chunk_ids)}

    # 获取张力曲线
    chunk_curves = stats_repo.fetch_chunk_curves_full(run_id)
    tension_scores = (
        [row.tension_proxy if row else 0.0 for row in chunk_curves] if chunk_curves else [0.5] * total_chunks
    )

    # 确保张力数据长度匹配
    if len(tension_scores) < total_chunks:
        tension_scores.extend([0.5] * (total_chunks - len(tension_scores)))
    elif len(tension_scores) > total_chunks:
        tension_scores = tension_scores[:total_chunks]

    # 获取分块摘要
    summary_map = {row.chunk_id: row.summary for row in chunk_repo.fetch_chunk_summaries(run_id)}

    # 获取标注数据
    raw_annotations = annotation_repo.fetch_chunk_annotations_full(run_id)

    class Annotation:
        __slots__ = ("chunk_id", "event_type", "cliffhanger", "pivot_moment", "emotional_valence")

        def __init__(self, row):
            self.chunk_id = row.chunk_id
            self.event_type = row.event_type if row.event_type else ""
            self.cliffhanger = row.cliffhanger if row.cliffhanger is not None else False
            self.pivot_moment = row.pivot_moment if row.pivot_moment is not None else False
            self.emotional_valence = row.emotional_valence if row.emotional_valence else ""

    annotation_map = {ann.chunk_id: ann for ann in [Annotation(r) for r in raw_annotations]} if raw_annotations else {}

    # 获取知识图谱数据
    entities = graph_repo.fetch_entities(run_id, entity_type="character")

    # 预构建实体ID到名称的映射
    entity_name_map: dict[int, str] = {e.entity_id: e.canonical_name for e in entities if e.entity_id is not None}

    relation_events = graph_repo.fetch_relation_event_models(run_id)

    # 计算四阶段划分
    phases = compute_four_phases(tension_scores, chunk_ids)
    timeline_phases = convert_to_timeline_phases(phases)

    # 获取主要角色（基于活跃跨度）
    major_characters = get_major_characters_by_span(entities, top_n=3)
    major_character_entries: list[tuple[str, int]] = []
    for char in major_characters:
        if char.first_seen_chunk is not None:
            idx = chunk_id_to_idx.get(char.first_seen_chunk)
            if idx is not None:
                major_character_entries.append((char.canonical_name, idx))

    # 获取关系断裂事件
    relation_break_events: list[tuple[int, RelationChangeEventDTO]] = []
    for rel_event in relation_events:
        if rel_event.change_type == "断裂":
            idx = chunk_id_to_idx.get(rel_event.chunk_id)
            if idx is None:
                continue
            from_char = entity_name_map.get(rel_event.from_entity_id, str(rel_event.from_entity_id))
            to_char = entity_name_map.get(rel_event.to_entity_id, str(rel_event.to_entity_id))
            relation_break_events.append(
                (
                    idx,
                    RelationChangeEventDTO(
                        from_char=from_char,
                        to_char=to_char,
                        relation_type=rel_event.relation_type,
                        change_type=rel_event.change_type,
                        evidence=rel_event.evidence,
                    ),
                )
            )

    # 预构建 chunk_id → relation_events 映射（避免 O(E) 内层循环）
    chunk_relation_events: dict[int, list[Any]] = {}
    for event_data in relation_events:
        chunk_relation_events.setdefault(event_data.chunk_id, []).append(event_data)

    # 创建候选节点
    candidates: list[TimelineCandidate] = []
    for i, (chunk_id, text) in enumerate(chunk_texts):
        progress = i / (total_chunks - 1) if total_chunks > 1 else 0.0

        ann = annotation_map.get(chunk_id)
        pivot_moment = ann.pivot_moment if ann else False
        cliffhanger = ann.cliffhanger if ann else False
        event_type = ann.event_type if ann else ""
        emotional_valence = ann.emotional_valence if ann else ""

        event = summary_map.get(chunk_id, "")
        if not event:
            event = text[:30] + "..." if len(text) > 30 else text

        # 检查是否有角色登场/退场
        character_entries: list[str] = []
        character_exits: list[str] = []
        for char in entities:
            if char.first_seen_chunk == chunk_id:
                character_entries.append(char.canonical_name)
            if char.last_seen_chunk == chunk_id:
                character_exits.append(char.canonical_name)

        # 检查是否为关系变化节点
        relation_changes: list[RelationChangeEventDTO] = []
        for event_data in chunk_relation_events.get(chunk_id, []):
            from_char = entity_name_map.get(event_data.from_entity_id, str(event_data.from_entity_id))
            to_char = entity_name_map.get(event_data.to_entity_id, str(event_data.to_entity_id))
            relation_changes.append(
                RelationChangeEventDTO(
                    from_char=from_char,
                    to_char=to_char,
                    relation_type=event_data.relation_type,
                    change_type=event_data.change_type,
                    evidence=event_data.evidence,
                )
            )

        # 检查是否为主要角色相关
        is_major_character = bool(
            set(character_entries) | set(character_exits) & {c.canonical_name for c in major_characters}
        )

        # 计算重要性分数
        importance_score, level = compute_importance_score(
            pivot_moment=pivot_moment,
            cliffhanger=cliffhanger,
            tension_composite=tension_scores[i],
            all_tensions=tension_scores,
            event_type=event_type,
            emotional_valence=emotional_valence,
            has_relation_change=bool(relation_changes),
            has_character_entry=bool(character_entries),
            has_character_exit=bool(character_exits),
            is_major_character=is_major_character,
        )

        # 确定节点类型
        node_type: TimelineNodeType = "plot"
        if character_entries and is_major_character:
            node_type = "character_entry"
        elif character_exits and is_major_character:
            node_type = "character_exit"
        elif relation_changes:
            node_type = "relation_change"

        # 计算张力百分位
        tension_percentile = calculate_tension_percentile(tension_scores[i], tension_scores)

        # 获取涉及的角色
        characters = list(set(character_entries + character_exits))
        if relation_changes:
            for rc in relation_changes:
                characters.extend([rc.from_char, rc.to_char])
        characters = list(set(characters))

        candidates.append(
            TimelineCandidate(
                chunk_id=chunk_id,
                progress=progress,
                importance_score=importance_score,
                level=level,
                event=event,
                characters=characters,
                is_pivot=pivot_moment,
                is_cliffhanger=cliffhanger,
                tension_percentile=tension_percentile,
                node_type=node_type,
                relation_changes=relation_changes if relation_changes else None,
                character_entries=character_entries if character_entries else None,
                character_exits=character_exits if character_exits else None,
            )
        )

    return (
        candidates,
        tension_scores,
        chunk_ids,
        total_chunks,
        timeline_phases,
        major_character_entries,
        relation_break_events,
    )
