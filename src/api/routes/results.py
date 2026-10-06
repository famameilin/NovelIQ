"""分析结果查询路由的注册入口（各资源域子模块见同目录 results_*.py）"""
from __future__ import annotations

from fastapi import APIRouter

from src.api.routes import (
    results_common,
    results_export,
    results_graph,
    results_metrics,
    results_paragraphs,
    results_topics,
)

router = APIRouter(prefix="/novels", tags=["results"])

# 1) pipeline 快照（results_common，同时承载共享 Depends 与公共工具）
router.include_router(results_common.router)
# 2) 完整结果导出
router.include_router(results_export.router)
# 3) 段落曲线 / 情绪趋势 / 章节指标 / 章节标注 / 角色
router.include_router(results_paragraphs.router)
# 4) 主题族 / 诊断 / 伏笔树
router.include_router(results_topics.router)
# 5) 图快照 / 图变化 / 图指标 / 关键词
router.include_router(results_graph.router)
# 6) metrics/* 聚合指标
router.include_router(results_metrics.router)
# 7) 事件森林（原注册顺序位于 metrics/* 之后）
router.include_router(results_graph.event_forest_router)
