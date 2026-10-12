"""独立时间轴及变化详情，统一复用任务完成读取规则"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.dependencies import get_db_session, require_readable_run_status, require_run_for_novel, resolve_run_id
from src.fact_graph.read.source import read_evidence_source
from src.metrics.queries.progression import ProgressionQuery

router = APIRouter(prefix="/novels", tags=["timeline"])
SessionDep = Annotated[Session, Depends(get_db_session)]
RunDep = Annotated[str, Depends(resolve_run_id)]


def authorize(session: Session, novel_id: str, run_id: str) -> None:
    require_readable_run_status(require_run_for_novel(session, novel_id, run_id))


def query_error(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=404 if isinstance(error, LookupError) else 400, detail={"code": str(error), "message": str(error)}
    )


@router.get("/{novel_id}/timeline")
async def get_timeline(
    novel_id: str,
    session: SessionDep,
    run_id: RunDep,
    through_chapter_id: int | None = None,
    window_start_chapter_id: int | None = None,
    window_end_chapter_id: int | None = None,
    subject_id: str | None = None,
    dimension: Literal["plot", "character", "relationship", "foreshadowing"] | None = None,
    q: str = "",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    source_fact_id: str | None = None,
) -> dict[str, Any]:
    authorize(session, novel_id, run_id)
    try:
        return ProgressionQuery(session, run_id).fetch(
            through_chapter_id=through_chapter_id,
            window_start_chapter_id=window_start_chapter_id,
            window_end_chapter_id=window_end_chapter_id,
            subject_id=subject_id,
            dimension=dimension,
            q=q,
            cursor=cursor,
            limit=limit,
            source_fact_id=source_fact_id,
        )
    except (ValueError, LookupError) as error:
        raise query_error(error) from error


@router.get("/{novel_id}/timeline/changes/{change_id}")
async def get_timeline_change(
    novel_id: str, change_id: str, through_chapter_id: int, session: SessionDep, run_id: RunDep
) -> dict[str, Any]:
    authorize(session, novel_id, run_id)
    try:
        return ProgressionQuery(session, run_id).detail(change_id, through_chapter_id)
    except (ValueError, LookupError) as error:
        raise query_error(error) from error


@router.get("/{novel_id}/timeline/changes/{change_id}/source")
async def get_timeline_source(
    novel_id: str,
    change_id: str,
    through_chapter_id: int,
    session: SessionDep,
    run_id: RunDep,
    chapter_id: int | None = None,
) -> dict[str, Any]:
    authorize(session, novel_id, run_id)
    try:
        detail = ProgressionQuery(session, run_id).detail(change_id, through_chapter_id)
        return read_evidence_source(session, run_id, detail["evidence"], chapter_id)
    except (ValueError, LookupError) as error:
        raise query_error(error) from error
