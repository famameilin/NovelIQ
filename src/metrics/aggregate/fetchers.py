"""
Aggregate Metrics 数据提取模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
说明: 提取所有数据提取函数

修改历史:
- 2026-03-13: 创建数据提取函数 (refactor-metrics-layer-functions)
- 2026-03-13: event_type 默认值改为"铺垫" (chunk-annotation-schema-refactor)
- 2026-03-14: 使用 Repository 接口 (metrics-repository-refactor)
- 2026-03-18: 提取为独立模块函数 (code-quality-refactor Task 11)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .types import (
    AnnotationData,
    CharacterData,
    CultureData,
    DialogueData,
    EmotionData,
    RelationData,
    TensionData,
    TextData,
    map_emotion_score,
)

if TYPE_CHECKING:
    from src.storage.repositories import (
        AnnotationRepository,
        ChunkRepository,
        StatsRepository,
    )


def fetch_annotation_data(
    annotation_repo: AnnotationRepository,
    run_id: str,
) -> AnnotationData:
    """提取 chunk_annotation 表数据"""
    rows = annotation_repo.fetch_full_annotations(run_id)

    return AnnotationData(
        chunk_ids=[row[0] for row in rows],
        event_types=[row[1] or "铺垫" for row in rows],
        cliffhangers=[row[2] or 0 for row in rows],
        pivot_moments=[row[3] or 0 for row in rows],
        emotional_valences=[row[4] or "neutral" for row in rows],
    )


def fetch_emotion_data(
    stats_repo: StatsRepository,
    run_id: str,
) -> EmotionData:
    """提取 emotion_curve 表数据"""
    rows = stats_repo.fetch_emotion_curve(run_id)
    emotion_values = [row[2] for row in rows]

    density_rows = stats_repo.fetch_emotion_densities(run_id)
    pos_densities = [row[0] for row in density_rows if row[0] is not None]
    neg_densities = [row[1] for row in density_rows if row[1] is not None]

    return EmotionData(
        emotion_values=emotion_values,
        pos_densities=pos_densities,
        neg_densities=neg_densities,
    )


def fetch_character_data(
    annotation_repo: AnnotationRepository,
    run_id: str,
) -> CharacterData:
    """提取 chunk_characters 表数据"""
    rows = annotation_repo.fetch_characters_with_scores(run_id)

    characters = []
    for row in rows:
        name, role_function, emotion_score_raw = row
        emotion_score = map_emotion_score(emotion_score_raw)
        characters.append((name, role_function, emotion_score))

    char_emotion_rows = annotation_repo.fetch_character_emotion_sequence(run_id)
    char_emotion_map: dict[str, list[float]] = {}
    for name, score_raw in char_emotion_rows:
        if name not in char_emotion_map:
            char_emotion_map[name] = []
        score = float(map_emotion_score(score_raw))
        char_emotion_map[name].append(score)
    char_emotion_scores = list(char_emotion_map.items())

    protagonist_name = None
    for name, role, _ in characters:
        if role == "主体":
            protagonist_name = name
            break

    return CharacterData(
        characters=characters,
        char_emotion_scores=char_emotion_scores,
        protagonist_name=protagonist_name,
    )


def fetch_relation_data(
    annotation_repo: AnnotationRepository,
    run_id: str,
) -> RelationData:
    """提取 chunk_relations 表数据"""
    relations = annotation_repo.fetch_relations(run_id)
    full_relations = annotation_repo.fetch_full_relations(run_id)

    return RelationData(
        relations=[(row[0], row[1]) for row in relations],
        full_relations=[(row[0], row[1], row[2], row[3]) for row in full_relations],
    )


def fetch_text_data(
    chunk_repo: ChunkRepository,
    run_id: str,
) -> TextData:
    """提取 chunks 表文本数据"""
    texts = chunk_repo.fetch_all_chunk_texts(run_id)

    all_tokens: list[str] = []
    for text in texts:
        tokens = re.findall(r"[\u4e00-\u9fa5]+|[a-zA-Z]+", text)
        all_tokens.extend(tokens)

    return TextData(texts=texts, all_tokens=all_tokens)


def fetch_culture_data(
    stats_repo: StatsRepository,
    run_id: str,
) -> CultureData:
    """
    提取 chunk_culture 表数据

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: 简化文化指标系统
    修改内容: 只返回 imagery_densities
    """
    culture_rows = stats_repo.fetch_chunk_culture(run_id)

    return CultureData(
        imagery_densities=[row[0] for row in culture_rows if row[0] is not None],
    )


def fetch_tension_data(
    stats_repo: StatsRepository,
    run_id: str,
) -> TensionData:
    """提取 rhythm_curve 表的 tension_composite 数据"""
    rows = stats_repo.fetch_rhythm_curve(run_id)
    tension_composite_scores = [row[0] for row in rows if row[0] is not None]
    return TensionData(tension_composite_scores=tension_composite_scores)


def fetch_dialogue_data(
    annotation_repo: AnnotationRepository,
    run_id: str,
) -> DialogueData:
    """
    提取 chunk_dialogues 表的 tone 数据

    创建时间: 2026-03-25
    创建者: TraeAI
    任务: fix-tone-distribution-semantic-error
    说明: 从对话表获取语气类型数据用于聚合计算
    """
    rows = annotation_repo.fetch_chunk_dialogues_full(run_id)
    tones = [row[3] for row in rows if len(row) > 3 and row[3] is not None]
    return DialogueData(tones=tones)
