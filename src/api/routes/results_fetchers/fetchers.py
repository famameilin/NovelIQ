"""
数据获取函数兼容转发层。

创建时间: 2026-03-28
创建者: TraeAI
任务: consolidate-codebase-architecture
说明: 现仅保留向 services.results_queries 的兼容转发，避免 service 反向依赖 route。

修改时间: 2026-04-23
修改者: Codex
任务: p1-api-route-service-decouple
修改内容: 真正实现迁移到 `src.api.services.results_queries` 分区模块，本文件只做兼容导出。
"""

from src.api.services.results_queries import (
    GRAPH_PAGE_EVENT_LIMIT,
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
    _fetch_raw_chunk_curves,
    _fetch_token_usage_stats,
    _fetch_topics,
    _serialize_graph_page_quality,
    _serialize_graph_page_summary,
)
from src.knowledge.authority import KnowledgeGraphAuthorityService

__all__ = [
    "KnowledgeGraphAuthorityService",
    "GRAPH_PAGE_EVENT_LIMIT",
    "_fetch_chunk_curves",
    "_fetch_raw_chunk_curves",
    "_fetch_characters",
    "_fetch_topics",
    "_fetch_diagnosis",
    "_fetch_graph_events_page",
    "_fetch_graph_snapshot",
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
