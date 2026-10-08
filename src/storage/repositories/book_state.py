"""全书工作状态的原始记录读取，不装配业务视图"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage.models import AnnotationWork, BookCase, Chapter, EventEdge, EventNode


def work_records(session: Session, run_id: str) -> list[AnnotationWork]:
    return list(session.scalars(select(AnnotationWork).where(AnnotationWork.run_id == run_id)))


def case_records(session: Session, run_id: str) -> list[BookCase]:
    return list(session.scalars(select(BookCase).where(BookCase.run_id == run_id)))


def event_records(session: Session, run_id: str) -> list[EventNode]:
    return list(session.scalars(select(EventNode).where(EventNode.run_id == run_id)))


def connection_records(session: Session, run_id: str) -> list[EventEdge]:
    return list(session.scalars(select(EventEdge).where(EventEdge.run_id == run_id)))


def chapter_count(session: Session, run_id: str) -> int:
    return int(session.scalar(select(func.count()).select_from(Chapter).where(Chapter.run_id == run_id)) or 0)
