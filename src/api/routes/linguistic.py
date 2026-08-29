"""语言结构基础数据查询端点（《分析能力扩展路线图》§3.3 B/C 赛道 API）

聚合端点：
- GET /{novel_id}/linguistic/features?level=book|chapter 词性/词长/句式/依存聚合
- GET /{novel_id}/linguistic/entities                 LTP 实体候选（审核面数据源）
- GET /{novel_id}/linguistic/phrases                  固定短语命中统计
- GET /{novel_id}/linguistic/word2vec                 词向量契约 + POS 覆盖率与质心

全部复合结果查询时计算；语言阶段未运行时返回 unavailable_reason。
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.dependencies import get_db_session, resolve_run_id
from src.api.models.responses import (
    LinguisticEntitiesResponse,
    LinguisticFeaturesResponse,
    LinguisticPhrasesResponse,
    Word2VecStatsResponse,
)
from src.api.routes.results import _require_readable_run_status, _require_run_for_novel
from src.api.services.results_queries.linguistic import (
    aggregate_linguistic_features,
    aggregate_phrase_stats,
    fetch_entity_candidates,
    fetch_word2vec_stats,
)

router = APIRouter(prefix="/novels/{novel_id}", tags=["linguistic"])


@router.get("/linguistic/features", response_model=LinguisticFeaturesResponse)
async def get_linguistic_features(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    level: Literal["book", "chapter"] = Query(default="book", description="聚合层级：book 或 chapter"),
) -> LinguisticFeaturesResponse:
    """
    词性/词长/句式/依存聚合（§5.11）：分母为有效 LTP 词元数或句子数

    返回 book 与 chapters 两级（level 参数决定响应侧重，当前恒返回两级）。
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return LinguisticFeaturesResponse(**aggregate_linguistic_features(run_id, session))


@router.get("/linguistic/entities", response_model=LinguisticEntitiesResponse)
async def get_linguistic_entities(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> LinguisticEntitiesResponse:
    """LTP 实体候选（§5.4）：候选不代表正式图谱事实，仅供审核对照"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return LinguisticEntitiesResponse(**fetch_entity_candidates(run_id, session))


@router.get("/linguistic/phrases", response_model=LinguisticPhrasesResponse)
async def get_linguistic_phrases(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> LinguisticPhrasesResponse:
    """固定短语命中统计（§5.11）：正式密度与四字候选数量分开报告"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return LinguisticPhrasesResponse(**aggregate_phrase_stats(run_id, session))


@router.get("/linguistic/word2vec", response_model=Word2VecStatsResponse)
async def get_linguistic_word2vec(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> Word2VecStatsResponse:
    """词向量契约与词性覆盖率/质心（§5.6/§5.11）"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return Word2VecStatsResponse(**fetch_word2vec_stats(run_id, session))