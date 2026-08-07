"""
数据获取函数兼容转发层

说明: 现仅保留向 services.results_queries 的兼容转发，避免 service 反向依赖 route
"""

from src.api.services.results_queries import (
    GRAPH_CHANGE_LIMIT,
    _fetch_character_relations,
    _fetch_characters,
    _fetch_chunk_annotations,
    _fetch_chunk_curves,
    _fetch_chunk_styles,
    _fetch_diagnosis,
    _fetch_global_stats,
    _fetch_graph_changes_page,
    _fetch_graph_snapshot,
    _fetch_hierarchical_relations,
    _fetch_known_characters,
    _fetch_novel_name,
    _fetch_raw_chunk_curves,
    _fetch_token_usage_stats,
    _fetch_topics,
)
from src.knowledge.authority import KnowledgeGraphAuthorityService

__all__ = [
    "KnowledgeGraphAuthorityService",
    "GRAPH_CHANGE_LIMIT",
    "_fetch_chunk_curves",
    "_fetch_raw_chunk_curves",
    "_fetch_characters",
    "_fetch_topics",
    "_fetch_diagnosis",
    "_fetch_graph_changes_page",
    "_fetch_graph_snapshot",
    "_fetch_chunk_styles",
    "_fetch_chunk_annotations",
    "_fetch_character_relations",
    "_fetch_hierarchical_relations",
    "_fetch_global_stats",
    "_fetch_novel_name",
    "_fetch_token_usage_stats",
    "_fetch_known_characters",
]
