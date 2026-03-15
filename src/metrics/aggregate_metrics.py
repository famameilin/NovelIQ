from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from .narrative_metrics import (
    compute_cliffhanger_rate,
    compute_climax_spacing,
    compute_event_density,
    compute_middle_collapse_index,
    compute_three_act_ratio_by_tension,
)
from .emotion_metrics_extra import (
    compute_arc_delta,
    compute_emotion_curve_type,
    compute_emotion_polarity_distribution,
    compute_emotion_recovery_speed,
    compute_pivot_moment_density,
    compute_pos_neg_ratio,
)
from .character_metrics import (
    compute_antagonist_strength_gap,
    compute_average_clustering,
    compute_character_function_coverage,
    compute_character_degree_centrality,
    compute_greimas_coverage,
    compute_largest_component_size,
    compute_number_of_connected_components,
    compute_protagonist_betweenness,
    compute_relation_change_frequency,
    compute_relation_network_density,
)
from .style_metrics_extra import (
    compute_avg_word_len,
    compute_category_density,
    compute_classical_sentence_ratio,
    compute_function_word_vector,
    compute_idiom_density,
    compute_imagery_density,
    compute_sent_len_std,
    compute_vocab_breadth,
)


"""
创建时间: 2025-03-11
创建者: TraeAI
任务: 聚合所有指标

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 添加从 chunk_culture 表读取文化密度指标并计算平均值
- 添加 confucian_density, taoist_density, buddhist_density, folk_density, allusion_density, imagery_density

修改时间: 2026-03-13
修改者: TraeAI
修改内容: 重构函数拆解，解决 Long Method 和 God Method 代码异味
- 创建数据提取辅助函数 _fetch_*_data
- 创建指标计算私有函数 _compute_*_metrics
- 重构 aggregate_all_metrics 调用拆解后的私有函数

修改时间: 2026-03-14
修改者: TraeAI
任务: metrics-repository-refactor
修改内容: 重构为使用 Repository 模式
- 所有数据访问通过 Repository 接口
- 函数签名添加 run_id 参数
- 保持向后兼容（conn 参数可选）
"""

if TYPE_CHECKING:
    from src.storage.repositories import (
        AnnotationRepository,
        ChunkRepository,
        StatsRepository,
    )


@dataclass
class AggregateResult:
    narrative_structure: Dict[str, float] = field(default_factory=dict)
    emotion_curve: Dict[str, Any] = field(default_factory=dict)
    character_relations: Dict[str, Any] = field(default_factory=dict)
    language_style: Dict[str, Any] = field(default_factory=dict)
    traditional_culture: Dict[str, float | None] = field(default_factory=dict)


@dataclass
class AnnotationData:
    chunk_ids: List[int]
    event_types: List[str]
    cliffhangers: List[int]
    pivot_moments: List[int]
    emotional_valences: List[str]


@dataclass
class EmotionData:
    emotion_values: List[float]
    pos_densities: List[float]
    neg_densities: List[float]


@dataclass
class CharacterData:
    characters: List[Tuple[str, str, int]]
    char_emotion_scores: List[Tuple[str, List[float]]]
    protagonist_name: str | None


@dataclass
class RelationData:
    relations: List[Tuple[str, str]]
    full_relations: List[Tuple[str, str, str, str]]


@dataclass
class TextData:
    texts: List[str]
    all_tokens: List[str]


@dataclass
class CultureData:
    confucian_densities: List[float]
    taoist_densities: List[float]
    buddhist_densities: List[float]
    folk_densities: List[float]
    allusion_densities: List[float]
    imagery_densities: List[float]


@dataclass
class TensionData:
    tension_composite_scores: List[float]


EMOTION_SCORE_MAPPING = {
    "strong_positive": 2,
    "mild_positive": 1,
    "neutral": 0,
    "mild_negative": -1,
    "strong_negative": -2,
}


def _map_emotion_score(score_raw: str | None) -> int:
    """
    2026-03-14 创建 - TraeAI
    任务: metrics-repository-refactor
    说明: 将情绪分数字符串映射为数值
    """
    if score_raw in EMOTION_SCORE_MAPPING:
        return EMOTION_SCORE_MAPPING[score_raw]
    return 0


def _fetch_annotation_data(
    annotation_repo: "AnnotationRepository",
    run_id: str,
) -> AnnotationData:
    """
    2026-03-13 创建 - TraeAI
    任务: refactor-metrics-layer-functions
    说明: 提取 chunk_annotation 表数据

    2026-03-13 修改 - TraeAI
    任务: chunk-annotation-schema-refactor
    修改内容: event_type 默认值改为"铺垫"

    2026-03-14 修改 - TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 AnnotationRepository 接口
    """
    rows = annotation_repo.fetch_full_annotations(run_id)

    return AnnotationData(
        chunk_ids=[row[0] for row in rows],
        event_types=[row[1] or "铺垫" for row in rows],
        cliffhangers=[row[2] or 0 for row in rows],
        pivot_moments=[row[3] or 0 for row in rows],
        emotional_valences=[row[4] or "neutral" for row in rows],
    )


def _fetch_emotion_data(
    stats_repo: "StatsRepository",
    run_id: str,
) -> EmotionData:
    """
    2026-03-13 创建 - TraeAI
    任务: refactor-metrics-layer-functions
    说明: 提取 emotion_curve 表数据

    2026-03-14 修改 - TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 StatsRepository 接口
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


def _fetch_character_data(
    annotation_repo: "AnnotationRepository",
    run_id: str,
) -> CharacterData:
    """
    2026-03-13 创建 - TraeAI
    任务: refactor-metrics-layer-functions
    说明: 提取 chunk_characters 表数据

    2026-03-13 修改 - TraeAI
    任务: chunk-annotation-schema-refactor
    修改内容: emotion_score 改为字符串枚举，需要映射为数值

    2026-03-14 修改 - TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 AnnotationRepository 接口
    """
    rows = annotation_repo.fetch_characters_with_scores(run_id)

    characters = []
    for row in rows:
        name, role_function, emotion_score_raw = row
        emotion_score = _map_emotion_score(emotion_score_raw)
        characters.append((name, role_function, emotion_score))

    char_emotion_rows = annotation_repo.fetch_character_emotion_sequence(run_id)
    char_emotion_map: Dict[str, List[float]] = {}
    for name, score_raw in char_emotion_rows:
        if name not in char_emotion_map:
            char_emotion_map[name] = []
        score = float(_map_emotion_score(score_raw))
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


def _fetch_relation_data(
    annotation_repo: "AnnotationRepository",
    run_id: str,
) -> RelationData:
    """
    2026-03-13 创建 - TraeAI
    任务: refactor-metrics-layer-functions
    说明: 提取 chunk_relations 表数据

    2026-03-14 修改 - TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 AnnotationRepository 接口
    """
    relations = annotation_repo.fetch_relations(run_id)
    full_relations = annotation_repo.fetch_full_relations(run_id)

    return RelationData(
        relations=[(row[0], row[1]) for row in relations],
        full_relations=[(row[0], row[1], row[2], row[3]) for row in full_relations],
    )


def _fetch_text_data(
    chunk_repo: "ChunkRepository",
    run_id: str,
) -> TextData:
    """
    2026-03-13 创建 - TraeAI
    任务: refactor-metrics-layer-functions
    说明: 提取 chunks 表文本数据

    2026-03-13 修改 - TraeAI
    任务: chunk-annotation-schema-refactor
    修改内容: 删除 tone 字段获取（已从 schema 中移除）

    2026-03-14 修改 - TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 ChunkRepository 接口
    """
    texts = chunk_repo.fetch_all_chunk_texts(run_id)

    all_tokens: List[str] = []
    for text in texts:
        tokens = re.findall(r"[\u4e00-\u9fa5]+|[a-zA-Z]+", text)
        all_tokens.extend(tokens)

    return TextData(texts=texts, all_tokens=all_tokens)


def _fetch_culture_data(
    stats_repo: "StatsRepository",
    run_id: str,
) -> CultureData:
    """
    2026-03-13 创建 - TraeAI
    任务: refactor-metrics-layer-functions
    说明: 提取 chunk_culture 表数据

    2026-03-14 修改 - TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 StatsRepository 接口
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


def _fetch_tension_data(
    stats_repo: "StatsRepository",
    run_id: str,
) -> TensionData:
    """
    2026-03-13 创建 - TraeAI
    任务: chunk-annotation-schema-refactor
    说明: 提取 rhythm_curve 表的 tension_composite 数据

    2026-03-14 修改 - TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 StatsRepository 接口
    """
    rows = stats_repo.fetch_rhythm_curve(run_id)
    tension_composite_scores = [row[0] for row in rows if row[0] is not None]
    return TensionData(tension_composite_scores=tension_composite_scores)


def _compute_narrative_structure_metrics(
    annotation_data: AnnotationData,
    tension_data: TensionData,
) -> Dict[str, Any]:
    """
    2026-03-13 创建 - TraeAI
    任务: refactor-metrics-layer-functions
    说明: 计算叙事结构聚合指标

    2026-03-13 修改 - TraeAI
    任务: chunk-annotation-schema-refactor
    修改内容: 使用 tension_composite 计算三幕比例、高潮定位、中间塌陷指数
    """
    return {
        **compute_three_act_ratio_by_tension(tension_data.tension_composite_scores),
        "climax_spacing": compute_climax_spacing(annotation_data.chunk_ids, tension_data.tension_composite_scores),
        "middle_collapse_index": compute_middle_collapse_index(
            annotation_data.chunk_ids, tension_data.tension_composite_scores
        ),
        "cliffhanger_rate": compute_cliffhanger_rate(annotation_data.cliffhangers),
        **{f"event_density_{k}": v for k, v in compute_event_density(annotation_data.event_types).items()},
    }


def _compute_emotion_curve_metrics(
    emotion_data: EmotionData,
    annotation_data: AnnotationData,
    char_data: CharacterData,
) -> Dict[str, Any]:
    """
    2026-03-13 创建 - TraeAI
    任务: refactor-metrics-layer-functions
    说明: 计算情感曲线聚合指标
    """
    return {
        "emotion_recovery_speed": compute_emotion_recovery_speed(emotion_data.emotion_values),
        "pivot_moment_density": compute_pivot_moment_density(annotation_data.pivot_moments),
        **compute_emotion_polarity_distribution(annotation_data.emotional_valences),
        "pos_neg_ratio": compute_pos_neg_ratio(emotion_data.pos_densities, emotion_data.neg_densities),
        "arc_delta": compute_arc_delta(char_data.char_emotion_scores),
        "emotion_curve_type": compute_emotion_curve_type(emotion_data.emotion_values),
    }


def _compute_character_relation_metrics(
    relation_data: RelationData,
    char_data: CharacterData,
    total_chunks: int,
) -> Dict[str, Any]:
    """
    2026-03-13 创建 - TraeAI
    任务: refactor-metrics-layer-functions
    说明: 计算人物关系聚合指标
    """
    result: Dict[str, Any] = {
        "network_density": compute_relation_network_density(relation_data.relations),
        "antagonist_strength_gap": compute_antagonist_strength_gap(char_data.characters),
        "average_clustering": compute_average_clustering(relation_data.relations),
        "num_connected_components": float(compute_number_of_connected_components(relation_data.relations)),
        "largest_component_size": float(compute_largest_component_size(relation_data.relations)),
        **compute_relation_change_frequency(relation_data.full_relations, total_chunks),
    }

    if char_data.protagonist_name:
        result["protagonist_betweenness"] = compute_protagonist_betweenness(
            relation_data.relations, char_data.protagonist_name
        )

    degree_centrality = compute_character_degree_centrality(relation_data.relations)
    if degree_centrality:
        max_char = max(degree_centrality, key=lambda k: degree_centrality[k] or 0.0)
        result["max_degree_character"] = max_char
        result["max_degree_value"] = degree_centrality[max_char] or 0.0
        result["degree_centrality"] = degree_centrality

    role_functions = [row[1] for row in char_data.characters if row[1]]
    result.update({f"function_coverage_{k}": v for k, v in compute_character_function_coverage(role_functions).items()})
    result["greimas_coverage"] = compute_greimas_coverage(role_functions)

    return result


def _compute_language_style_metrics(text_data: TextData) -> Dict[str, Any]:
    """
    2026-03-13 创建 - TraeAI
    任务: refactor-metrics-layer-functions
    说明: 计算语言风格聚合指标

    2026-03-13 修改 - TraeAI
    任务: chunk-annotation-schema-refactor
    修改内容: 删除 tone_distribution 计算（tone 字段已移除）
    """
    return {
        "vocab_breadth": compute_vocab_breadth(text_data.all_tokens),
        "avg_word_len": compute_avg_word_len(text_data.texts),
        "sent_len_std": compute_sent_len_std(text_data.texts),
        **{f"function_word_{k}": v for k, v in compute_function_word_vector(text_data.texts).items()},
        **{f"category_density_{k}": v for k, v in compute_category_density(text_data.texts).items()},
    }


def _compute_traditional_culture_metrics(
    culture_data: CultureData,
    texts: List[str],
) -> Dict[str, float | None]:
    """
    2026-03-13 创建 - TraeAI
    任务: refactor-metrics-layer-functions
    说明: 计算传统文化聚合指标
    """
    return {
        "idiom_density": compute_idiom_density(texts),
        "classical_sentence_ratio": compute_classical_sentence_ratio(texts),
        "imagery_density": compute_imagery_density(texts),
        "confucian_density": statistics.mean(culture_data.confucian_densities)
        if culture_data.confucian_densities
        else None,
        "taoist_density": statistics.mean(culture_data.taoist_densities) if culture_data.taoist_densities else None,
        "buddhist_density": statistics.mean(culture_data.buddhist_densities)
        if culture_data.buddhist_densities
        else None,
        "folk_density": statistics.mean(culture_data.folk_densities) if culture_data.folk_densities else None,
        "allusion_density": statistics.mean(culture_data.allusion_densities)
        if culture_data.allusion_densities
        else None,
        "imagery_density_from_culture": statistics.mean(culture_data.imagery_densities)
        if culture_data.imagery_densities
        else None,
    }


def aggregate_all_metrics(
    run_id: str,
    annotation_repo: "AnnotationRepository",
    chunk_repo: "ChunkRepository",
    stats_repo: "StatsRepository",
) -> AggregateResult:
    """
    聚合所有指标的主入口函数。

    2026-03-11 修复 degree_centrality 未存储问题 - Claude
    原因：计算了 degree_centrality 但未存入结果字典，导致数据丢失

    2026-03-13 重构 - TraeAI
    任务: refactor-metrics-layer-functions
    说明: 将函数拆解为多个职责单一的私有函数，解决 Long Method 和 God Method 代码异味

    2026-03-13 修改 - TraeAI
    任务: chunk-annotation-schema-refactor
    修改内容: 添加 tension_data 提取并传递给叙事结构指标计算

    2026-03-14 修改 - TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 Repository 接口，添加 run_id 参数
    """
    result = AggregateResult()

    annotation_data = _fetch_annotation_data(annotation_repo, run_id)
    emotion_data = _fetch_emotion_data(stats_repo, run_id)
    char_data = _fetch_character_data(annotation_repo, run_id)
    relation_data = _fetch_relation_data(annotation_repo, run_id)
    text_data = _fetch_text_data(chunk_repo, run_id)
    culture_data = _fetch_culture_data(stats_repo, run_id)
    tension_data = _fetch_tension_data(stats_repo, run_id)

    total_chunks = chunk_repo.count_chunks(run_id) or 1

    result.narrative_structure = _compute_narrative_structure_metrics(annotation_data, tension_data)
    result.emotion_curve = _compute_emotion_curve_metrics(emotion_data, annotation_data, char_data)
    result.character_relations = _compute_character_relation_metrics(relation_data, char_data, total_chunks)
    result.language_style = _compute_language_style_metrics(text_data)
    result.traditional_culture = _compute_traditional_culture_metrics(culture_data, text_data.texts)

    return result
