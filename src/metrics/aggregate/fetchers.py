"""
Aggregate Metrics 数据提取模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
说明: 提取所有数据提取函数
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, List

from .types import (
    AnnotationData,
    CharacterData,
    CultureData,
    EmotionData,
    RelationData,
    TextData,
    TensionData,
    map_emotion_score,
)

if TYPE_CHECKING:
    from src.storage.repositories import (
        AnnotationRepository,
        ChunkRepository,
        StatsRepository,
    )


def fetch_annotation_data(
    annotation_repo: "AnnotationRepository",
    run_id: str,
) -> AnnotationData:
    """
    提取 chunk_annotation 表数据

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-metrics-layer-functions

    修改时间: 2026-03-13
    修改者: TraeAI
    任务: chunk-annotation-schema-refactor
    修改内容: event_type 默认值改为"铺垫"

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 AnnotationRepository 接口

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
    修改内容: 提取为独立模块函数
    """
    rows = annotation_repo.fetch_full_annotations(run_id)

    return AnnotationData(
        chunk_ids=[row[0] for row in rows],
        event_types=[row[1] or "铺垫" for row in rows],
        cliffhangers=[row[2] or 0 for row in rows],
        pivot_moments=[row[3] or 0 for row in rows],
        emotional_valences=[row[4] or "neutral" for row in rows],
    )


def fetch_emotion_data(
    stats_repo: "StatsRepository",
    run_id: str,
) -> EmotionData:
    """
    提取 emotion_curve 表数据

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-metrics-layer-functions

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 StatsRepository 接口

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
    修改内容: 提取为独立模块函数
    """
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
    annotation_repo: "AnnotationRepository",
    run_id: str,
) -> CharacterData:
    """
    提取 chunk_characters 表数据

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-metrics-layer-functions

    修改时间: 2026-03-13
    修改者: TraeAI
    任务: chunk-annotation-schema-refactor
    修改内容: emotion_score 改为字符串枚举，需要映射为数值

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 AnnotationRepository 接口

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
    修改内容: 提取为独立模块函数
    """
    rows = annotation_repo.fetch_characters_with_scores(run_id)

    characters = []
    for row in rows:
        name, role_function, emotion_score_raw = row
        emotion_score = map_emotion_score(emotion_score_raw)
        characters.append((name, role_function, emotion_score))

    char_emotion_rows = annotation_repo.fetch_character_emotion_sequence(run_id)
    char_emotion_map: dict[str, List[float]] = {}
    for name, score_raw in char_emotion_rows:
        if name not in char_emotion_map:
            char_emotion_map[name] = []
        score = float(map_emotion_score(score_raw))
        char_emotion_map[name].append(score)
    char_emotion_scores = [(name, scores) for name, scores in char_emotion_map.items()]

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
    annotation_repo: "AnnotationRepository",
    run_id: str,
) -> RelationData:
    """
    提取 chunk_relations 表数据

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-metrics-layer-functions

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 AnnotationRepository 接口

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
    修改内容: 提取为独立模块函数
    """
    relations = annotation_repo.fetch_relations(run_id)
    full_relations = annotation_repo.fetch_full_relations(run_id)

    return RelationData(
        relations=[(row[0], row[1]) for row in relations],
        full_relations=[(row[0], row[1], row[2], row[3]) for row in full_relations],
    )


def fetch_text_data(
    chunk_repo: "ChunkRepository",
    run_id: str,
) -> TextData:
    """
    提取 chunks 表文本数据

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-metrics-layer-functions

    修改时间: 2026-03-13
    修改者: TraeAI
    任务: chunk-annotation-schema-refactor
    修改内容: 删除 tone 字段获取（已从 schema 中移除）

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 ChunkRepository 接口

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
    修改内容: 提取为独立模块函数
    """
    texts = chunk_repo.fetch_all_chunk_texts(run_id)

    all_tokens: List[str] = []
    for text in texts:
        tokens = re.findall(r"[\u4e00-\u9fa5]+|[a-zA-Z]+", text)
        all_tokens.extend(tokens)

    return TextData(texts=texts, all_tokens=all_tokens)


def fetch_culture_data(
    stats_repo: "StatsRepository",
    run_id: str,
) -> CultureData:
    """
    提取 chunk_culture 表数据

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-metrics-layer-functions

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 StatsRepository 接口

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
    修改内容: 提取为独立模块函数
    """
    culture_rows = stats_repo.fetch_chunk_culture(run_id)

    return CultureData(
        confucian_densities=[row[0] for row in culture_rows if row[0] is not None],
        taoist_densities=[row[1] for row in culture_rows if row[1] is not None],
        buddhist_densities=[row[2] for row in culture_rows if row[2] is not None],
        folk_densities=[row[3] for row in culture_rows if row[3] is not None],
        allusion_densities=[row[4] for row in culture_rows if row[4] is not None],
        imagery_densities=[row[5] for row in culture_rows if row[5] is not None],
    )


def fetch_tension_data(
    stats_repo: "StatsRepository",
    run_id: str,
) -> TensionData:
    """
    提取 rhythm_curve 表的 tension_composite 数据

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: chunk-annotation-schema-refactor

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 StatsRepository 接口

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
    修改内容: 提取为独立模块函数
    """
    rows = stats_repo.fetch_rhythm_curve(run_id)
    tension_composite_scores = [row[0] for row in rows if row[0] is not None]
    return TensionData(tension_composite_scores=tension_composite_scores)
