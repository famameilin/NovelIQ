"""
结果查询共享包。

创建时间: 2026-04-23
创建者: Codex
任务: p1-api-route-service-decouple
说明: 为 route 与 service 提供统一的结果查询组装器，纠正原先 service 反向依赖 route 的问题。
"""

from .characters import _fetch_characters
from .chunks import (
    _fetch_chunk_annotations,
    _fetch_chunk_curves,
    _fetch_chunk_styles,
    _fetch_raw_chunk_curves,
)
from .common import (
    _calculate_protagonist_scores,
    _normalize_arc_scores,
    _normalize_name,
    _normalize_name_list,
    _normalize_text_by_alias_map,
    _parse_int_field,
    _parse_json_field,
)
from .diagnosis import _fetch_diagnosis
from .graph import (
    GRAPH_PAGE_EVENT_LIMIT,
    _fetch_character_relations,
    _fetch_graph_events_page,
    _fetch_graph_snapshot,
    _fetch_hierarchical_relations,
    _serialize_graph_page_quality,
    _serialize_graph_page_summary,
)
from .metadata import (
    _fetch_alias_merges_only,
    _fetch_global_stats,
    _fetch_known_characters,
    _fetch_novel_name,
    _fetch_token_usage_stats,
)
from .topics import _fetch_topics

__all__ = [
    "GRAPH_PAGE_EVENT_LIMIT",
    "_parse_json_field",
    "_parse_int_field",
    "_normalize_name",
    "_normalize_name_list",
    "_normalize_text_by_alias_map",
    "_fetch_chunk_curves",
    "_fetch_raw_chunk_curves",
    "_fetch_characters",
    "_calculate_protagonist_scores",
    "_fetch_topics",
    "_fetch_diagnosis",
    "_fetch_graph_events_page",
    "_fetch_graph_snapshot",
    "_normalize_arc_scores",
    "_serialize_graph_page_quality",
    "_serialize_graph_page_summary",
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
