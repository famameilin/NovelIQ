"""
Aggregate Metrics 兼容性转发模块

创建时间: 2025-03-11
创建者: TraeAI
任务: 聚合所有指标

修改历史:
- 2026-03-12: 添加文化密度指标 (confucian, taoist, buddhist, folk, allusion, imagery)
- 2026-03-13: 重构函数拆解，解决 Long Method 和 God Method 代码异味
- 2026-03-14: 重构为使用 Repository 模式
- 2026-03-18: 拆分为子包 src.metrics.aggregate，此文件作为兼容性转发

说明:
- 此文件保留向后兼容，所有功能已移至 src.metrics.aggregate 子包
- 下划线前缀的函数名（如 _fetch_*）已弃用，请使用新函数名（如 fetch_*）
"""

from __future__ import annotations

import warnings

# 从子包导入所有公共API，保持向后兼容
from src.metrics.aggregate import (
    AggregateResult,
    AnnotationData,
    CharacterData,
    CultureData,
    EmotionData,
    RelationData,
    TensionData,
    TextData,
    compute_character_relation_metrics,
    compute_emotion_curve_metrics,
    compute_language_style_metrics,
    compute_narrative_structure_metrics,
    compute_traditional_culture_metrics,
    fetch_annotation_data,
    fetch_character_data,
    fetch_culture_data,
    fetch_emotion_data,
    fetch_relation_data,
    fetch_tension_data,
    fetch_text_data,
)
from src.metrics.aggregate.types import map_emotion_score


# 弃用的兼容函数（下划线前缀）
def _deprecated_alias(old_name: str, new_func):
    """创建弃用的函数别名"""
    def wrapper(*args, **kwargs):
        warnings.warn(
            f"{old_name} is deprecated. Use {new_func.__name__} instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return new_func(*args, **kwargs)
    wrapper.__name__ = old_name
    wrapper.__doc__ = f"Deprecated. Use {new_func.__name__} instead."
    return wrapper


# 弃用的函数别名
_fetch_annotation_data = _deprecated_alias("_fetch_annotation_data", fetch_annotation_data)
_fetch_emotion_data = _deprecated_alias("_fetch_emotion_data", fetch_emotion_data)
_fetch_character_data = _deprecated_alias("_fetch_character_data", fetch_character_data)
_fetch_relation_data = _deprecated_alias("_fetch_relation_data", fetch_relation_data)
_fetch_text_data = _deprecated_alias("_fetch_text_data", fetch_text_data)
_fetch_culture_data = _deprecated_alias("_fetch_culture_data", fetch_culture_data)
_fetch_tension_data = _deprecated_alias("_fetch_tension_data", fetch_tension_data)
_compute_narrative_structure_metrics = _deprecated_alias(
    "_compute_narrative_structure_metrics", compute_narrative_structure_metrics
)
_compute_emotion_curve_metrics = _deprecated_alias(
    "_compute_emotion_curve_metrics", compute_emotion_curve_metrics
)
_compute_character_relation_metrics = _deprecated_alias(
    "_compute_character_relation_metrics", compute_character_relation_metrics
)
_compute_language_style_metrics = _deprecated_alias(
    "_compute_language_style_metrics", compute_language_style_metrics
)
_compute_traditional_culture_metrics = _deprecated_alias(
    "_compute_traditional_culture_metrics", compute_traditional_culture_metrics
)
_map_emotion_score = _deprecated_alias("_map_emotion_score", map_emotion_score)

__all__ = [
    # 数据类
    "AggregateResult",
    "AnnotationData",
    "CharacterData",
    "CultureData",
    "EmotionData",
    "RelationData",
    "TensionData",
    "TextData",
    # 数据提取函数
    "fetch_annotation_data",
    "fetch_emotion_data",
    "fetch_character_data",
    "fetch_relation_data",
    "fetch_text_data",
    "fetch_culture_data",
    "fetch_tension_data",
    # 指标计算函数
    "compute_narrative_structure_metrics",
    "compute_emotion_curve_metrics",
    "compute_character_relation_metrics",
    "compute_language_style_metrics",
    "compute_traditional_culture_metrics",
    # 工具函数
    "map_emotion_score",
    # 弃用的函数（保留向后兼容）
    "_fetch_annotation_data",
    "_fetch_emotion_data",
    "_fetch_character_data",
    "_fetch_relation_data",
    "_fetch_text_data",
    "_fetch_culture_data",
    "_fetch_tension_data",
    "_compute_narrative_structure_metrics",
    "_compute_emotion_curve_metrics",
    "_compute_character_relation_metrics",
    "_compute_language_style_metrics",
    "_compute_traditional_culture_metrics",
    "_map_emotion_score",
]


def aggregate_all_metrics(
    run_id: str,
    annotation_repo,
    chunk_repo,
    stats_repo,
) -> AggregateResult:
    """
    聚合所有指标的主入口函数。

    Args:
        run_id: 运行ID
        annotation_repo: 标注数据仓库
        chunk_repo: 分块数据仓库
        stats_repo: 统计数据仓库

    Returns:
        AggregateResult: 聚合结果
    """
    result = AggregateResult()

    annotation_data = fetch_annotation_data(annotation_repo, run_id)
    emotion_data = fetch_emotion_data(stats_repo, run_id)
    char_data = fetch_character_data(annotation_repo, run_id)
    relation_data = fetch_relation_data(annotation_repo, run_id)
    text_data = fetch_text_data(chunk_repo, run_id)
    culture_data = fetch_culture_data(stats_repo, run_id)
    tension_data = fetch_tension_data(stats_repo, run_id)

    total_chunks = chunk_repo.count_chunks(run_id) or 1

    result.narrative_structure = compute_narrative_structure_metrics(annotation_data, tension_data)
    result.emotion_curve = compute_emotion_curve_metrics(emotion_data, annotation_data, char_data)
    result.character_relations = compute_character_relation_metrics(relation_data, char_data, total_chunks)
    result.language_style = compute_language_style_metrics(text_data)
    result.traditional_culture = compute_traditional_culture_metrics(culture_data, text_data.texts)

    return result
