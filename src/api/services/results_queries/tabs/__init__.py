"""Tab 级聚合查询服务

按页面域分模块组装 tab 响应；只做编排与切片，聚合口径复用既有
results_queries 服务，不重复实现指标计算。
"""

from src.api.services.results_queries.tabs.linguistic import build_linguistic_entities_tab
from src.api.services.results_queries.tabs.topics import build_topics_overview

__all__ = [
    "build_linguistic_entities_tab",
    "build_topics_overview",
]
