"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 数据库操作兼容层

本模块作为兼容层，重新导出 operations/ 子模块中的所有函数。
原有的 1036 行代码已拆分到以下子模块：
- chunk_ops.py: Chunk 操作
- annotation_ops.py: 标注操作
- entity_ops.py: 实体操作
- relation_ops.py: 关系操作
- embedding_ops.py: 向量操作
- stats_ops.py: 统计操作
- completeness.py: 完整性检查
- diagnosis_ops.py: 诊断操作
"""

from .operations.annotation_ops import (
    fetch_all_character_names,
    fetch_annotated_chunk_ids,
    fetch_chunk_annotations,
    insert_chunk_annotation,
    insert_chunk_characters,
    insert_chunk_dialogues,
    insert_chunk_relations,
    update_character_names,
)
from .operations.chunk_ops import (
    ChunkStyleData,
    clear_chunk_topics,
    fetch_chunk_styles,
    fetch_chunk_texts,
    insert_chunk_culture,
    insert_chunk_style,
    insert_chunk_topics,
    insert_chunks,
)
from .operations.completeness import (
    has_aggregated_data,
    has_annotations,
    has_chunks,
    has_diagnosis_data,
    has_topic_data,
    is_aggregate_complete,
    is_annotate_complete,
    is_diagnose_complete,
    is_preprocess_complete,
    is_topic_model_complete,
)
from .operations.diagnosis_ops import (
    fetch_first_last_chunk_summary,
    fetch_foreshadowing_chunks,
    fetch_high_tension_chunks,
    fetch_pivot_blocks,
    fetch_pivot_moments,
    fetch_recent_snapshots,
    fetch_relation_changes,
    fetch_snapshots_by_chunk,
    insert_entity_snapshot,
)
from .operations.embedding_ops import (
    fetch_chunk_embedding,
    get_embedding_dim,
    insert_chunk_embedding,
)
from .operations.entity_ops import (
    fetch_active_entities,
    fetch_all_aliases_for_entity,
    fetch_entity_by_alias,
    fetch_entity_by_canonical,
    increment_alias_confirm,
    insert_entity,
    insert_entity_alias,
    insert_entity_embedding,
    insert_entity_registry,
    update_entity_last_chunk,
)
from .operations.relation_ops import (
    fetch_active_relations,
    fetch_relations_for_entity,
    insert_entity_relation,
    update_relation_last_chunk,
)
from .operations.stats_ops import (
    fetch_global_context,
    fetch_token_usage_by_novel,
    fetch_token_usage_stats,
    insert_character_appearances,
    insert_chunk_summary,
    insert_cloud_analysis,
    insert_emotion_curve,
    insert_global_context,
    insert_global_stats,
    insert_rhythm_curve,
    insert_token_usage,
    update_global_context,
)

__all__ = [
    "ChunkStyleData",
    "clear_chunk_topics",
    "fetch_active_entities",
    "fetch_active_relations",
    "fetch_all_aliases_for_entity",
    "fetch_all_character_names",
    "fetch_annotated_chunk_ids",
    "fetch_chunk_annotations",
    "fetch_chunk_embedding",
    "fetch_chunk_styles",
    "fetch_chunk_texts",
    "fetch_entity_by_alias",
    "fetch_entity_by_canonical",
    "fetch_first_last_chunk_summary",
    "fetch_foreshadowing_chunks",
    "fetch_global_context",
    "fetch_high_tension_chunks",
    "fetch_pivot_blocks",
    "fetch_pivot_moments",
    "fetch_recent_snapshots",
    "fetch_relation_changes",
    "fetch_relations_for_entity",
    "fetch_snapshots_by_chunk",
    "fetch_token_usage_by_novel",
    "fetch_token_usage_stats",
    "get_embedding_dim",
    "has_aggregated_data",
    "has_annotations",
    "has_chunks",
    "has_diagnosis_data",
    "has_topic_data",
    "increment_alias_confirm",
    "insert_character_appearances",
    "insert_chunk_annotation",
    "insert_chunk_characters",
    "insert_chunk_culture",
    "insert_chunk_dialogues",
    "insert_chunk_embedding",
    "insert_chunk_relations",
    "insert_chunk_style",
    "insert_chunk_summary",
    "insert_chunk_topics",
    "insert_chunks",
    "insert_cloud_analysis",
    "insert_emotion_curve",
    "insert_entity",
    "insert_entity_alias",
    "insert_entity_embedding",
    "insert_entity_registry",
    "insert_entity_relation",
    "insert_entity_snapshot",
    "insert_global_context",
    "insert_global_stats",
    "insert_rhythm_curve",
    "insert_token_usage",
    "is_aggregate_complete",
    "is_annotate_complete",
    "is_diagnose_complete",
    "is_preprocess_complete",
    "is_topic_model_complete",
    "update_character_names",
    "update_entity_last_chunk",
    "update_global_context",
    "update_relation_last_chunk",
]
