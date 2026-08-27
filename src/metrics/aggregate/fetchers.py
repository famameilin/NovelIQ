"""
Aggregate Metrics 数据提取模块

提取所有数据提取函数

"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from src.knowledge.authority import KnowledgeGraphAuthorityService
from src.models.local.character_reference_policy import decide_character_reference
from src.storage.models import Chapter

from .types import (
    AnnotationData,
    CharacterData,
    DialogueData,
    EmotionData,
    RelationData,
    StyleData,
    TensionData,
    TextData,
    map_emotion_score,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.storage.repositories import (
        AnnotationRepository,
        ChapterRepository,
        StatsRepository,
    )


def _fetch_chapter_progress_map(session: Session, run_id: str) -> dict[int, float]:
    """章起点归一化进度：char_offset / max(char_end_offset)。缺 offset 的章不入表。"""
    total = session.execute(
        select(func.max(Chapter.char_end_offset)).where(Chapter.run_id == run_id)
    ).scalar_one_or_none()
    if total is None or int(total) <= 0:
        # 回退：用 max(char_offset)+1，避免全空
        total = session.execute(
            select(func.max(Chapter.char_offset)).where(Chapter.run_id == run_id)
        ).scalar_one_or_none()
        if total is None or int(total) <= 0:
            return {}
        total_chars = float(int(total) + 1)
    else:
        total_chars = float(int(total))

    rows = session.execute(
        select(Chapter.chapter_id, Chapter.char_offset)
        .where(Chapter.run_id == run_id, Chapter.char_offset.is_not(None))
        .order_by(Chapter.sequence, Chapter.chapter_id)
    ).all()
    progress: dict[int, float] = {}
    for chapter_id, offset in rows:
        if offset is None:
            continue
        progress[int(chapter_id)] = float(offset) / total_chars
    return progress


def _build_aggregate_graph_view(
    annotation_repo: AnnotationRepository,
    run_id: str,
):
    """
    获取 aggregate 允许依赖的 graph authority view

    聚合指标属于 graph 下游消费者，只能读取 authority 暴露的稳定事实，
    不能再直接依赖 GraphRepository 的原始 row 形状
    """

    service = KnowledgeGraphAuthorityService.from_session(annotation_repo.session)
    service.assert_graph_ready(run_id)
    return service.build_representative_graph_view(run_id)


def _resolve_aggregate_character_name(
    *,
    surface_name: str | None,
    resolved_global_name: str | None,
) -> str | None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: aggregate 指标只能消费已准入的全局角色，不能把未解析代词重新混回情绪统计。
    """
    decision = decide_character_reference(
        surface_name,
        resolved_global_name=resolved_global_name,
    )
    return decision.resolved_global_name


def fetch_annotation_data(
    annotation_repo: AnnotationRepository,
    run_id: str,
) -> AnnotationData:
    """
    从章节正式标注的 chunks metrics 提取 chunk 粒度指标数据

    """
    rows = annotation_repo.fetch_full_annotations(run_id)

    return AnnotationData(
        chapter_ids=[row.chapter_id for row in rows],
        event_types=[row.event_type or "铺垫" for row in rows],
        cliffhangers=[row.cliffhanger or 0 for row in rows],
        pivot_moments=[row.pivot_moment or 0 for row in rows],
        emotional_valences=[row.emotional_valence or "neutral" for row in rows],
    )


def fetch_emotion_data(
    stats_repo: StatsRepository,
    run_id: str,
) -> EmotionData:
    """
    提取每章（chunk）情绪密度（§9.1 守恒聚合，2026-08-14 M8b 段落化）

    章情绪密度 = 章内段落分子之和 / 分母之和（Σpos/Σtoken、Σneg/Σtoken、
    (Σpos − Σneg)/Σtoken）；token 为 0 的章无有效密度，直接跳过。
    """
    from src.storage.repositories.paragraph_repository import ParagraphRepository

    aggregates = ParagraphRepository(stats_repo.session).fetch_chapter_metric_aggregates(run_id)
    progress_map = _fetch_chapter_progress_map(stats_repo.session, run_id)
    emotion_values: list[float] = []
    pos_densities: list[float] = []
    neg_densities: list[float] = []
    chapter_ids: list[int] = []
    positions: list[float] = []
    for chapter_id, totals in aggregates:
        token_count = totals.get("token_count", 0.0)
        if token_count <= 0:
            continue
        position = progress_map.get(int(chapter_id))
        if position is None:
            continue
        pos_total = totals.get("positive_weight_sum", 0.0)
        neg_total = totals.get("negative_weight_sum", 0.0)
        chapter_ids.append(int(chapter_id))
        positions.append(position)
        pos_densities.append(pos_total / token_count)
        neg_densities.append(neg_total / token_count)
        emotion_values.append((pos_total - neg_total) / token_count)

    return EmotionData(
        emotion_values=emotion_values,
        pos_densities=pos_densities,
        neg_densities=neg_densities,
        chapter_ids=chapter_ids,
        positions=positions,
    )


def fetch_character_data(
    annotation_repo: AnnotationRepository,
    run_id: str,
) -> CharacterData:
    """
    提取角色数据

    避免 aggregate character stats 依赖 graph participant state 过滤结果
    """
    authority_service = KnowledgeGraphAuthorityService.from_session(annotation_repo.session)
    snapshot = authority_service.build_level1_snapshot(run_id)
    active_characters = [
        entity
        for entity in snapshot.canonical_entities
        if entity.entity_type == "character" and entity.status == "active"
    ]

    # 2. 从数据库图人物事实聚合情感分数
    rows = annotation_repo.fetch_characters_with_scores(run_id)
    emotion_map: dict[str, int] = {}
    for row in rows:
        canonical_name = _resolve_aggregate_character_name(
            surface_name=getattr(row, "surface_name", None) or getattr(row, "name", None),
            resolved_global_name=getattr(row, "resolved_global_name", None),
        )
        if canonical_name is None:
            continue
        emotion_score_raw = getattr(row, "emotion_score", None)
        emotion_map[canonical_name] = map_emotion_score(emotion_score_raw)

    # 3. 构建角色列表（使用共享 canonical entity 作为完整角色种子）
    characters = []
    for entity in active_characters:
        emotion_score = emotion_map.get(entity.name, 0)
        characters.append((entity.name, entity.primary_role_function or "其他", emotion_score))

    # 4. 从数据库图人物事实构建情感序列
    char_emotion_rows = annotation_repo.fetch_character_emotion_sequence(run_id)
    char_emotion_map: dict[str, list[float]] = {}
    for row in char_emotion_rows:
        canonical_name = _resolve_aggregate_character_name(
            surface_name=getattr(row, "surface_name", None) or getattr(row, "name", None),
            resolved_global_name=getattr(row, "resolved_global_name", None),
        )
        if canonical_name is None:
            continue
        if canonical_name not in char_emotion_map:
            char_emotion_map[canonical_name] = []
        score = float(map_emotion_score(getattr(row, "emotion_score", None)))
        char_emotion_map[canonical_name].append(score)
    char_emotion_scores = list(char_emotion_map.items())

    return CharacterData(
        characters=characters,
        char_emotion_scores=char_emotion_scores,
    )


# 关系聚合使用完整角色子图，孤立参与者也进入统计口径
def fetch_relation_data(
    annotation_repo: AnnotationRepository,
    run_id: str,
) -> RelationData:
    """提取 graph_* 关系数据（权威来源）"""
    graph_view = _build_aggregate_graph_view(annotation_repo, run_id)
    # P4：人物网络只消费 entity_type=character 的角色子图，不再把地点/物品等全实体节点计入
    character_names = {
        state.name for state in graph_view.participant_states if state.entity_type == "character" and state.name
    }
    current_relations = [
        relation
        for relation in graph_view.confirmed_relations
        if relation.from_name in character_names and relation.to_name in character_names
    ]
    relation_changes = [
        change
        for change in graph_view.graph_changes
        if change.change_kind == "relation"
        and change.from_name
        and change.to_name
        and change.relation_type
        and change.from_name in character_names
        and change.to_name in character_names
    ]

    return RelationData(
        relations=[(relation.from_name, relation.to_name) for relation in current_relations],
        full_relations=[
            (
                change.from_name or "",
                change.to_name or "",
                change.relation_type or "",
                # 2026-08-13 P2：changes 为空时兜底，避免隐式不变量破坏后 IndexError
                str(change.changes[0].get("change_kind") or "refine") if change.changes else "refine",
            )
            for change in relation_changes
        ],
        participant_names=sorted(character_names),
    )


def fetch_text_data(
    chapter_repo: ChapterRepository,
    run_id: str,
) -> TextData:
    """提取 chunks 表文本数据"""
    texts = chapter_repo.fetch_all_chapter_texts(run_id)

    all_tokens: list[str] = []
    for text in texts:
        tokens = re.findall(r"[\u4e00-\u9fa5]+|[a-zA-Z]+", text)
        all_tokens.extend(tokens)

    return TextData(texts=texts, all_tokens=all_tokens)


def fetch_tension_data(
    stats_repo: StatsRepository,
    run_id: str,
) -> TensionData:
    """
    提取每章（chunk）张力（2026-08-14 M8b 段落化）

    章张力 = 章内段落 surface_tension 均值（段落值已为 run 内稳健标准化 +
    sigmoid 的 [0,1] 值，直接取均值；无张力数据的章不输出，由调用方兜底）。
    """
    from src.storage.repositories.paragraph_repository import ParagraphRepository

    rows = ParagraphRepository(stats_repo.session).fetch_chapter_tension_scores(run_id)
    progress_map = _fetch_chapter_progress_map(stats_repo.session, run_id)
    return TensionData(
        chapter_ids=[chapter_id for chapter_id, _tension in rows],
        tension_composite_scores=[tension for _chapter_id, tension in rows],
        positions=[progress_map.get(int(chapter_id)) for chapter_id, _tension in rows],
    )


def fetch_dialogue_data(
    annotation_repo: AnnotationRepository,
    run_id: str,
) -> DialogueData:
    """
    从数据库图对话事实提取 tone 数据

    按事实中的 chapter_id 展开语气类型用于聚合计算

    """
    rows = annotation_repo.fetch_chapter_dialogues_full(run_id)
    tones = [row.tone for row in rows if row.tone is not None]
    return DialogueData(tones=tones)


def fetch_style_data(
    chapter_repo: ChapterRepository,
    run_id: str,
) -> StyleData:
    """
    提取全书风格指标（§9.1 守恒聚合，2026-08-14 M8b 段落化）

    从段落充分统计量计算全书守恒值：dialogue_ratio = Σdialogue_char_count /
    Σchar_count；avg_sent_len = Σsentence_char_sum / Σsentence_count。
    """
    from src.storage.repositories.paragraph_repository import ParagraphRepository

    aggregates = ParagraphRepository(chapter_repo.session).fetch_chapter_metric_aggregates(run_id)
    dialogue_char_total = sum(item.get("dialogue_char_count", 0.0) for _cid, item in aggregates)
    char_total = sum(item.get("char_count", 0.0) for _cid, item in aggregates)
    sentence_char_total = sum(item.get("sentence_char_sum", 0.0) for _cid, item in aggregates)
    sentence_total = sum(item.get("sentence_count", 0.0) for _cid, item in aggregates)

    return StyleData(
        dialogue_ratio=(dialogue_char_total / char_total) if char_total > 0 else None,
        avg_sent_len=(sentence_char_total / sentence_total) if sentence_total > 0 else None,
    )
