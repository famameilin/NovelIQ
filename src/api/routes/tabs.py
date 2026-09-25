"""Tab 级聚合端点（前端每 tab 一个 API）

统一守门：resolve_run_id + require_run_for_novel + require_readable_run_status；
切片原则见 src/api/models/tabs.py 模块说明。

既有单源端点直接作为所属 tab 的 API，不在此包一层：
- 情绪趋势 tab → /emotion-trend
- 时间轴/节点详情 tab → /timeline
- 主题演进/迁移/情绪 tab → /topics/series|shifts|emotion
- 词法句法/词向量 tab → /linguistic/features|word2vec
- 角色排行/角色表 tab → /characters
- 图谱变化 tab → /graph/changes
- 诊断摘要/价值与主题 tab → /diagnosis；伏笔树 tab → /foreshadowing-trees
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.dependencies import get_db_session, get_metrics_service, resolve_run_id
from src.api.dependencies import require_readable_run_status as _require_readable_run_status
from src.api.dependencies import require_run_for_novel as _require_run_for_novel
from src.api.models.tabs import (
    CharacterFunctionTabResponse,
    DashboardTabResponse,
    GraphNetworkTabResponse,
    LinguisticEntitiesTabResponse,
    RhythmTabResponse,
    TopicsOverviewTabResponse,
)
from src.api.services.metrics_service import MetricsService
from src.api.services.results_queries.tabs import (
    build_character_function_tab,
    build_dashboard_tab,
    build_graph_network_tab,
    build_linguistic_entities_tab,
    build_rhythm_tab,
    build_topics_overview,
)

router = APIRouter(prefix="/novels/{novel_id}", tags=["tabs"])


@router.get("/tabs/dashboard", response_model=DashboardTabResponse)
async def get_dashboard_tab(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    metrics_service: Annotated[MetricsService, Depends(get_metrics_service)],
) -> DashboardTabResponse:
    """仪表盘 tab：四组聚合指标 + 章节汇总 + 主题词 + 诊断 + 情绪趋势"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return DashboardTabResponse(**build_dashboard_tab(run_id, novel_id, session, metrics_service, run))


@router.get("/tabs/rhythm", response_model=RhythmTabResponse)
async def get_rhythm_tab(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    metrics_service: Annotated[MetricsService, Depends(get_metrics_service)],
    max_points: Annotated[int | None, Query(gt=0, description="展示降采样点数上限")] = None,
) -> RhythmTabResponse:
    """节奏张力 tab：段落曲线 + 叙事结构高潮参数"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return RhythmTabResponse(**build_rhythm_tab(run_id, session, metrics_service, max_points))


@router.get("/tabs/character-function", response_model=CharacterFunctionTabResponse)
async def get_character_function_tab(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CharacterFunctionTabResponse:
    """功能与焦点 tab：角色功能分布 + 诊断焦点结构切片"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return CharacterFunctionTabResponse(**build_character_function_tab(run_id, novel_id, session))


@router.get("/tabs/graph-network", response_model=GraphNetworkTabResponse)
async def get_graph_network_tab(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    chapter_id: Annotated[int | None, Query(gt=0, description="目标章节边界，缺省取最新章节")] = None,
) -> GraphNetworkTabResponse:
    """图谱 tab：图快照 + 登场次数 + 图算法指标 + 变化总数"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return GraphNetworkTabResponse(**build_graph_network_tab(run_id, session, chapter_id=chapter_id))


@router.get("/tabs/topics-overview", response_model=TopicsOverviewTabResponse)
async def get_topics_overview_tab(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> TopicsOverviewTabResponse:
    """主题总览 tab：主题词 + 全书/章节完整分布 + TextRank 关键词"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return TopicsOverviewTabResponse(**build_topics_overview(run_id, session, novel_id))


@router.get("/tabs/linguistic-entities", response_model=LinguisticEntitiesTabResponse)
async def get_linguistic_entities_tab(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> LinguisticEntitiesTabResponse:
    """实体与短语 tab：实体类型计数 + 高频实体名 + 固定短语统计（不含 span 明细）"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return LinguisticEntitiesTabResponse(**build_linguistic_entities_tab(run_id, session))
