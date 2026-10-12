"""全书事件树只读入口，章节定位不改变全书结构"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.dependencies import get_db_session, require_readable_run_status, require_run_for_novel, resolve_run_id
from src.event_trees.read.organization import EventOrganizationQuery
from src.fact_graph.read.source import read_evidence_source

router = APIRouter(tags=["event-trees"])
SessionDep = Annotated[Session, Depends(get_db_session)]
RunDep = Annotated[str, Depends(resolve_run_id)]


def _query(session: Session, novel_id: str, run_id: str) -> EventOrganizationQuery:
    require_readable_run_status(require_run_for_novel(session, novel_id, run_id))
    return EventOrganizationQuery(session, run_id)


def _error(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=404 if isinstance(error, LookupError) else 400, detail={"code": str(error), "message": str(error)}
    )


@router.get("/{novel_id}/event-trees")
async def get_event_trees(
    novel_id: str,
    session: SessionDep,
    run_id: RunDep,
    parent_id: str | None = None,
    q: str = "",
    chapter_id: int | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    expand_all: bool = False,
) -> dict[str, Any]:
    try:
        return _query(session, novel_id, run_id).fetch(
            parent_id=parent_id, q=q, chapter_id=chapter_id, cursor=cursor, limit=limit, expand_all=expand_all
        )
    except (ValueError, LookupError) as error:
        raise _error(error) from error


@router.get("/{novel_id}/event-trees/nodes/{node_id}")
async def get_event_tree_node(novel_id: str, node_id: str, session: SessionDep, run_id: RunDep) -> dict[str, Any]:
    try:
        return _query(session, novel_id, run_id).detail(node_id)
    except (ValueError, LookupError) as error:
        raise _error(error) from error


@router.get("/{novel_id}/event-trees/nodes/{node_id}/source")
async def get_event_tree_source(
    novel_id: str, node_id: str, session: SessionDep, run_id: RunDep, chapter_id: int | None = None
) -> dict[str, Any]:
    try:
        detail = _query(session, novel_id, run_id).detail(node_id)
        return read_evidence_source(session, run_id, detail["evidence"], chapter_id)
    except (ValueError, LookupError) as error:
        raise _error(error) from error
