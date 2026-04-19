"""
结果数据获取模块

创建时间: 2026-03-28
创建者: TraeAI
任务: consolidate-codebase-architecture
说明: 从 results_fetchers.py 拆分，提供统一的数据获取接口
"""

from src.api.routes.results_fetchers.fetchers import (
    _fetch_alias_merges_only,
    _fetch_character_relations,
    _fetch_characters,
    _fetch_chunk_annotations,
    _fetch_chunk_curves,
    _fetch_chunk_styles,
    _fetch_diagnosis,
    _fetch_global_stats,
    _fetch_graph_events_page,
    _fetch_graph_snapshot,
    _fetch_hierarchical_relations,
    _fetch_known_characters,
    _fetch_novel_name,
    _fetch_token_usage_stats,
    _fetch_topics,
)
from src.api.routes.results_fetchers.normalizers import (
    _normalize_name,
    _normalize_name_list,
    _normalize_text_by_alias_map,
)
from src.api.routes.results_fetchers.parsers import (
    _parse_int_field,
    _parse_json_field,
)
from src.api.routes.results_fetchers.scoring import (
    _calculate_protagonist_scores,
    _normalize_arc_scores,
)

__all__ = [
    "_parse_json_field",
    "_parse_int_field",
    "_normalize_name",
    "_normalize_name_list",
    "_normalize_text_by_alias_map",
    "_fetch_chunk_curves",
    "_fetch_characters",
    "_calculate_protagonist_scores",
    "_fetch_topics",
    "_fetch_diagnosis",
    "_fetch_graph_events_page",
    "_fetch_graph_snapshot",
    "_normalize_arc_scores",
    "_fetch_chunk_styles",
    "_fetch_chunk_annotations",
    "_fetch_character_relations",
    "_fetch_hierarchical_relations",
    "_fetch_global_stats",
    "_fetch_novel_name",
    "_fetch_token_usage_stats",
    "_fetch_known_characters",
    "_fetch_alias_merges_only",
]
