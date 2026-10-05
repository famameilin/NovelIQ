"""
说明: 提供分析结果导出和查询接口

修改时间: 2026-10-02
修改者: Trae
修改内容: 大文件拆分——按资源域拆分至同目录子模块（results_common/results_export/
results_paragraphs/results_topics/results_graph/results_metrics），本模块仅保留
router 聚合入口；include 顺序与原路由注册顺序完全一致（event-forest 域在 metrics 之后），
路径、响应模型与 OpenAPI 标签均保持不变。
"""

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
