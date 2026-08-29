"""Tab 级聚合端点（前端每 tab 一个 API）

统一守门：resolve_run_id + require_run_for_novel + require_readable_run_status；
切片原则见 src/api/models/tabs.py 模块说明。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.dependencies import (
    get_db_session,
    resolve_run_id,
)
from src.api.dependencies import (
    require_readable_run_status as _require_readable_run_status,
)
from src.api.dependencies import (
    require_run_for_novel as _require_run_for_novel,
)
from src.api.models.tabs import LinguisticEntitiesTabResponse, TopicsOverviewTabResponse
from src.api.services.results_queries.tabs import build_linguistic_entities_tab, build_topics_overview

router = APIRouter(prefix="/novels/{novel_id}", tags=["tabs"])


@router.get("/tabs/topics-overview", response_model=TopicsOverviewTabResponse)
async def get_topics_overview_tab(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> TopicsOverviewTabResponse:
    """主题总览 tab：主题词 + 全书/章节完整分布 + TextRank 关键词"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return TopicsOverviewTabResponse(**build_topics_overview(run_id, session))


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
