"""
创建时间: 2026-03-11
创建者: Claude
任务: API 路由数据获取函数
说明: 从数据库获取分析结果的辅助函数

修改时间: 2026-03-14
修改者: TraeAI
任务: refactor-routes-use-repository
修改内容: 重构为使用 Repository 模式，所有函数添加 run_id 参数支持

修改时间: 2026-03-19
修改者: TraeAI
任务: 添加层级关系导出到JSON功能
修改内容: 添加 _fetch_hierarchical_relations 函数和 HierarchicalRelation 导入

修改时间: 2026-03-28
修改者: TraeAI
任务: consolidate-codebase-architecture
修改内容: 拆分为子模块，此文件仅作为转发导入层
"""

from src.api.routes.results_fetchers.fetchers import (
    _fetch_alias_merges_only,
    _fetch_character_relations,
    _fetch_characters,
    _fetch_chunk_annotations,
    _fetch_chunk_cultures,
    _fetch_chunk_curves,
    _fetch_chunk_styles,
    _fetch_diagnosis,
    _fetch_global_stats,
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
from src.api.routes.results_fetchers.parsers import _parse_int_field, _parse_json_field
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
    "_normalize_arc_scores",
    "_fetch_chunk_styles",
    "_fetch_chunk_annotations",
    "_fetch_character_relations",
    "_fetch_hierarchical_relations",
    "_fetch_global_stats",
    "_fetch_chunk_cultures",
    "_fetch_novel_name",
    "_fetch_token_usage_stats",
    "_fetch_known_characters",
    "_fetch_alias_merges_only",
]
