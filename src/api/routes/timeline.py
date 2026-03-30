"""
叙事时间轴 API 路由

创建时间: 2026-03-30
创建者: CodeBuddy
任务: 实现叙事时间轴功能
说明: 提供时间轴数据查询接口，支持四阶段划分、节点筛选和张力曲线
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlalchemy.orm import Session

from src.api.exceptions import AnalysisNotCompleteError, NovelNotFoundError
from src.api.models.responses import ErrorResponse
from src.api.models.timeline import (
    RelationChangeEvent,
    TimelineMeta,
    TimelineResponse,
)
from src.api.routes.novels import get_novel_service
from src.api.services.novel_service import NovelService
from src.metrics.timeline_metrics import (
    TimelineCandidate,
    calculate_tension_percentile,
    compute_four_phases,
    compute_importance_score,
    convert_to_timeline_nodes,
    convert_to_timeline_phases,
    get_major_characters_by_span,
    select_timeline_nodes,
)
from src.storage.db import get_session_factory
from src.storage.models import (
    ChunkSummary,
    GraphEntity,
    GraphRelationEvent,
)
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    RunRepository,
    StatsRepository,
)

router = APIRouter(prefix="/novels", tags=["timeline"])


def get_db_session():
    """获取数据库会话"""
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@router.get(
    "/{novel_id}/timeline",
    response_model=TimelineResponse,
    summary="获取叙事时间轴",
    description="""
📊 **叙事时间轴接口**

基于张力曲线、知识图谱和标注数据，生成小说的时间轴视图。

**功能：**
- 四阶段划分（引入期/发展期/高潮期/收束期）
- 重要节点识别（转折点、悬念点、角色登场/退场、关系变化）
- 张力曲线数据

**参数：**
- task_id: 分析任务ID（必需）
- include_curve: 是否包含张力曲线数据（默认 false）
- max_level: 显示重要性级别 ≤ 此值的节点（默认 3，即显示全部）
  - 1: 仅重要节点
  - 2: 重要 + 较重要节点
  - 3: 全部节点

**返回：**
- meta: 时间轴元信息
- phases: 四阶段划分
- nodes: 时间轴节点列表
- tension_curve: 张力曲线数据（可选）
""",
    responses={
        200: {
            "description": "时间轴数据",
            "content": {
                "application/json": {
                    "example": {
                        "meta": {
                            "novel_id": "novel_001",
                            "novel_name": "重明传",
                            "total_chunks": 500,
                        },
                        "phases": [
                            {"name": "引入期", "start": 1, "end": 75, "ratio": 0.15},
                            {"name": "发展期", "start": 76, "end": 350, "ratio": 0.55},
                            {"name": "高潮期", "start": 351, "end": 420, "ratio": 0.14},
                            {"name": "收束期", "start": 421, "end": 500, "ratio": 0.16},
                        ],
                        "nodes": [
                            {
                                "chunk_id": 1,
                                "progress": 0.0,
                                "importance_score": 6.0,
                                "level": 1,
                                "event": "贺重明在宗门试炼中展露天赋",
                                "characters": ["贺重明", "长老"],
                                "is_pivot": False,
                                "is_cliffhanger": False,
                                "tension_percentile": 45,
                                "node_type": "character_entry",
                                "relation_changes": None,
                                "character_entries": ["贺重明"],
                                "character_exits": None,
                            }
                        ],
                        "tension_curve": None,
                    }
                }
            },
        },
        404: {
            "description": "小说或任务未找到",
            "model": ErrorResponse,
        },
        400: {
            "description": "分析未完成",
            "model": ErrorResponse,
        },
    },
)
async def get_timeline(
    novel_id: str,
    task_id: str = Query(..., description="分析任务ID（8位短UUID）"),
    include_curve: bool = Query(False, description="是否包含张力曲线数据"),
    max_level: int = Query(3, ge=1, le=3, description="显示重要性级别 ≤ 此值的节点"),
    session: Session = Depends(get_db_session),
    service: NovelService = Depends(get_novel_service),
) -> TimelineResponse:
    """获取叙事时间轴数据"""

    # 1. 验证小说存在
    novels = service.list_novels()
    novel_info = next((n for n in novels if n.get("novel_id") == novel_id), None)
    if novel_info is None:
        raise NovelNotFoundError(f"小说不存在: {novel_id}")

    novel_name = novel_info.get("filename", "未知")

    # 2. 获取 run_id (task_id 是 run_id 的前 8 位)
    run_repo = RunRepository(session)
    run_data = run_repo.get_run_by_run_id_prefix(task_id)
    if run_data is None:
        raise NovelNotFoundError(f"任务不存在: {task_id}")

    # 验证 run 是否属于该 novel
    if run_data.get("novel_id") != novel_id:
        raise NovelNotFoundError(f"任务 {task_id} 不属于小说 {novel_id}")

    run_id = run_data["run_id"]

    # 3. 检查分析是否完成
    if run_data["status"] not in ("completed", "aggregated", "diagnosed"):
        raise AnalysisNotCompleteError(f"分析尚未完成，当前状态: {run_data['status']}")

    # 4. 获取数据
    chunk_repo = ChunkRepository(session)
    annotation_repo = AnnotationRepository(session)
    stats_repo = StatsRepository(session)

    # 获取 chunk 文本列表
    chunk_texts = chunk_repo.fetch_chunk_texts(run_id)
    if not chunk_texts:
        logger.warning(f"No chunks found for run {run_id}")
        return TimelineResponse(
            meta=TimelineMeta(
                novel_id=novel_id,
                novel_name=novel_name,
                total_chunks=0,
            ),
            phases=[],
            nodes=[],
            tension_curve=None,
        )

    chunk_ids = [cid for cid, _ in chunk_texts]
    total_chunks = len(chunk_ids)

    # 获取张力曲线
    rhythm_curve = stats_repo.fetch_rhythm_curve(run_id)
    tension_scores = [row[0] if row else 0.0 for row in rhythm_curve] if rhythm_curve else [0.5] * total_chunks

    # 确保张力数据长度匹配
    if len(tension_scores) < total_chunks:
        tension_scores.extend([0.5] * (total_chunks - len(tension_scores)))
    elif len(tension_scores) > total_chunks:
        tension_scores = tension_scores[:total_chunks]

    # 获取分块摘要
    summaries_data = (
        session.query(ChunkSummary.chunk_id, ChunkSummary.summary)
        .filter(ChunkSummary.run_id == run_id)
        .order_by(ChunkSummary.chunk_id)
        .all()
    )
    summary_map = {row[0]: row[1] for row in summaries_data}

    # 获取标注数据
    annotations = annotation_repo.fetch_chunk_annotations(run_id)
    annotation_map = {ann.chunk_id: ann for ann in annotations} if annotations else {}

    # 获取知识图谱数据
    entities = (
        session.query(GraphEntity)
        .filter(GraphEntity.run_id == run_id, GraphEntity.entity_type == "character")
        .all()
    )

    # 预构建实体ID到名称的映射，避免N+1查询问题
    entity_name_map: dict[int, str] = {
        e.entity_id: e.canonical_name for e in entities if e.entity_id is not None
    }

    relation_events = (
        session.query(GraphRelationEvent)
        .filter(GraphRelationEvent.run_id == run_id)
        .all()
    )

    # 5. 计算四阶段划分
    phases = compute_four_phases(tension_scores, chunk_ids)
    timeline_phases = convert_to_timeline_phases(phases)

    # 6. 获取主要角色（基于活跃跨度）
    major_characters = get_major_characters_by_span(entities, top_n=3)
    major_character_entries: list[tuple[str, int]] = []
    for char in major_characters:
        if char.first_seen_chunk is not None:
            # 找到 first_seen_chunk 在 chunk_ids 中的索引
            try:
                idx = chunk_ids.index(char.first_seen_chunk)
                major_character_entries.append((char.canonical_name, idx))
            except ValueError:
                pass

    # 7. 获取关系断裂事件（使用预构建的 entity_name_map 避免 N+1 查询）
    relation_break_events: list[tuple[int, RelationChangeEvent]] = []
    for rel_event in relation_events:
        if rel_event.change_type == "断裂":
            try:
                idx = chunk_ids.index(rel_event.chunk_id)
                # 从预构建的映射获取角色名称，避免循环内查询数据库
                from_char = entity_name_map.get(
                    rel_event.from_entity_id, str(rel_event.from_entity_id)
                )
                to_char = entity_name_map.get(
                    rel_event.to_entity_id, str(rel_event.to_entity_id)
                )

                relation_break_events.append(
                    (
                        idx,
                        RelationChangeEvent(
                            from_char=from_char,
                            to_char=to_char,
                            relation_type=rel_event.relation_type,
                            change_type=rel_event.change_type,
                            evidence=rel_event.evidence,
                        ),
                    )
                )
            except ValueError:
                pass

    # 8. 创建候选节点
    candidates: list[TimelineCandidate] = []
    for i, (chunk_id, text) in enumerate(chunk_texts):
        progress = i / (total_chunks - 1) if total_chunks > 1 else 0.0

        # 获取标注数据
        ann = annotation_map.get(chunk_id)

        pivot_moment = ann.pivot_moment if ann else False
        cliffhanger = ann.cliffhanger if ann else False
        event_type = ann.event_type if ann else ""
        emotional_valence = ann.emotional_valence if ann else ""

        # 获取事件描述
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

        # 检查是否为关系变化节点（使用预构建的 entity_name_map 避免 N+1 查询）
        relation_changes: list[RelationChangeEvent] = []
        for event_data in relation_events:
            if event_data.chunk_id == chunk_id:
                # 从预构建的映射获取角色名称，避免循环内查询数据库
                from_char = entity_name_map.get(
                    event_data.from_entity_id, str(event_data.from_entity_id)
                )
                to_char = entity_name_map.get(
                    event_data.to_entity_id, str(event_data.to_entity_id)
                )

                relation_changes.append(
                    RelationChangeEvent(
                        from_char=from_char,
                        to_char=to_char,
                        relation_type=event_data.relation_type,
                        change_type=event_data.change_type,
                        evidence=event_data.evidence,
                    )
                )

        # 检查是否为主要角色相关
        is_major_character = bool(
            set(character_entries) | set(character_exits)
            & {c.canonical_name for c in major_characters}
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
        node_type = "plot"
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

    # 9. 筛选节点
    selected_candidates = select_timeline_nodes(
        candidates=candidates,
        chunk_ids=chunk_ids,
        tension_scores=tension_scores,
        major_character_entries=major_character_entries,
        relation_break_events=relation_break_events,
        min_nodes=10,
        max_nodes=20,
    )

    # 10. 根据 max_level 过滤节点
    selected_candidates = [c for c in selected_candidates if c.level <= max_level]

    # 转换为 API 模型
    timeline_nodes = convert_to_timeline_nodes(selected_candidates)

    logger.info(
        f"Timeline generated for novel {novel_id}, task {task_id}: "
        f"{len(timeline_nodes)} nodes, {len(timeline_phases)} phases"
    )

    return TimelineResponse(
        meta=TimelineMeta(
            novel_id=novel_id,
            novel_name=novel_name,
            total_chunks=total_chunks,
        ),
        phases=timeline_phases,
        nodes=timeline_nodes,
        tension_curve=tension_scores if include_curve else None,
    )
