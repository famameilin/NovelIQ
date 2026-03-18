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

修改时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
修改内容:
- 将模块拆分为子包 src.metrics.aggregate
- 保留此文件作为兼容性转发，所有导出从子包导入
- 保持向后兼容，现有导入路径不变
"""

from __future__ import annotations

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

# 保留旧函数名（下划线前缀）的兼容性
_fetch_annotation_data = fetch_annotation_data
_fetch_emotion_data = fetch_emotion_data
_fetch_character_data = fetch_character_data
_fetch_relation_data = fetch_relation_data
_fetch_text_data = fetch_text_data
_fetch_culture_data = fetch_culture_data
_fetch_tension_data = fetch_tension_data
_compute_narrative_structure_metrics = compute_narrative_structure_metrics
_compute_emotion_curve_metrics = compute_emotion_curve_metrics
_compute_character_relation_metrics = compute_character_relation_metrics
_compute_language_style_metrics = compute_language_style_metrics
_compute_traditional_culture_metrics = compute_traditional_culture_metrics
_map_emotion_score = map_emotion_score

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
    # 旧函数名（兼容性）
    "_fetch_annotation_data",
    "_fetch_emotion_data",
    "_fetch_character_data",
    "_fetch_relation_data",
    "_fetch_text_data",
    "_fetch_culture_data",
    "_fetch_tension_data",
    # 指标计算函数
    "compute_narrative_structure_metrics",
    "compute_emotion_curve_metrics",
    "compute_character_relation_metrics",
    "compute_language_style_metrics",
    "compute_traditional_culture_metrics",
    # 旧函数名（兼容性）
    "_compute_narrative_structure_metrics",
    "_compute_emotion_curve_metrics",
    "_compute_character_relation_metrics",
    "_compute_language_style_metrics",
    "_compute_traditional_culture_metrics",
    # 工具函数
    "map_emotion_score",
    "_map_emotion_score",
]


# 主入口函数保留在此文件中
def aggregate_all_metrics(
    run_id: str,
    annotation_repo,
    chunk_repo,
    stats_repo,
):
    """
    聚合所有指标的主入口函数。

    创建时间: 2026-03-11
    创建者: TraeAI
    修改: 修复 degree_centrality 未存储问题

    修改时间: 2026-03-13
    修改者: TraeAI
    任务: refactor-metrics-layer-functions
    修改内容: 将函数拆解为多个职责单一的私有函数

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 Repository 接口，添加 run_id 参数

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
    修改内容: 委托给子模块函数
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
