"""语言结构基础数据查询端点"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

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
from src.api.models.responses import (
    LinguisticEntitiesResponse,
    LinguisticFeaturesResponse,
    LinguisticPhrasesResponse,
    Word2VecStatsResponse,
)
from src.linguistic.queries import (
    aggregate_linguistic_features,
    aggregate_phrase_stats,
    fetch_entity_candidates,
    fetch_word2vec_stats,
)
from src.storage import Storage

router = APIRouter(prefix="/novels/{novel_id}", tags=["linguistic"])


@router.get("/linguistic/features", response_model=LinguisticFeaturesResponse)
async def get_linguistic_features(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Storage, Depends(get_db_session)],
    level: Literal["book", "chapter"] = Query(default="book", description="聚合层级：book 或 chapter"),
) -> LinguisticFeaturesResponse:
    """
    词性/词长/句式/依存聚合：分母为有效 LTP 词元数或句子数

    返回 book 与 chapters 两级（level 参数决定响应侧重，当前恒返回两级）。
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return LinguisticFeaturesResponse(**aggregate_linguistic_features(run_id, session))


@router.get("/linguistic/entities", response_model=LinguisticEntitiesResponse)
async def get_linguistic_entities(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Storage, Depends(get_db_session)],
) -> LinguisticEntitiesResponse:
    """LTP 实体候选：候选不代表正式图谱事实，仅供审核对照"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return LinguisticEntitiesResponse(**fetch_entity_candidates(run_id, session))


@router.get("/linguistic/phrases", response_model=LinguisticPhrasesResponse)
async def get_linguistic_phrases(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Storage, Depends(get_db_session)],
) -> LinguisticPhrasesResponse:
    """固定短语命中统计：正式密度与四字候选数量分开报告"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return LinguisticPhrasesResponse(**aggregate_phrase_stats(run_id, session))


@router.get("/linguistic/word2vec", response_model=Word2VecStatsResponse)
async def get_linguistic_word2vec(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Storage, Depends(get_db_session)],
) -> Word2VecStatsResponse:
    """词向量契约与词性覆盖率/质心"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return Word2VecStatsResponse(**fetch_word2vec_stats(run_id, session))
