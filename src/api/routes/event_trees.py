"""正式事件只读入口；声明来源只用于审计，新旧契约禁止混读"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.dependencies import get_db_session, require_readable_run_status, require_run_for_novel, resolve_run_id
from src.event_trees.read.organization import EventTreeQuery, RunRequiresRebuildError
from src.fact_graph.read.source import read_evidence_source

router = APIRouter(tags=["event-trees"])
SessionDep = Annotated[Session, Depends(get_db_session)]
RunDep = Annotated[str, Depends(resolve_run_id)]


def _query(session: Session, novel_id: str, run_id: str) -> EventTreeQuery:
    require_readable_run_status(require_run_for_novel(session, novel_id, run_id))
    return EventTreeQuery(session, run_id)


def _error(error: Exception) -> HTTPException:
    if isinstance(error, RunRequiresRebuildError):
        return HTTPException(status_code=400, detail={"code": "RUN_REQUIRES_REBUILD", "message": str(error)})
    return HTTPException(
        status_code=404 if isinstance(error, LookupError) else 400, detail={"code": str(error), "message": str(error)}
    )


@router.get("/{novel_id}/event-trees")
async def get_event_trees(
    novel_id: str,
    session: SessionDep,
    run_id: RunDep,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    try:
        return _query(session, novel_id, run_id).fetch(cursor=cursor, limit=limit)
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
    novel_id: str,
    node_id: str,
    session: SessionDep,
    run_id: RunDep,
    chapter_id: int | None = None,
    kind: Literal["event", "declaration"] = "event",
) -> dict[str, Any]:
    try:
        query = _query(session, novel_id, run_id)
        if kind == "event":
            evidence = query.detail(node_id)["evidence"]
        else:
            evidence = query.declaration_source(node_id)
        source = read_evidence_source(session, run_id, evidence, chapter_id)
        # 全章正文供阅读，准确证据单独返回，不能把正文段落数组伪装成全部证据
        source["evidence"] = evidence
        source["evidence_scope"] = (
            "paragraph" if evidence and all(item.get("paragraph_id") is not None for item in evidence) else "chapter"
        )
        if kind == "declaration":
            source["locator"] = query.declaration_locator(node_id)
        return source
    except (ValueError, LookupError) as error:
        raise _error(error) from error
