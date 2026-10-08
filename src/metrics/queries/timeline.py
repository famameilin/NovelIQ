"""时间轴查询适配；读取失败的既有回退在此处理"""

from typing import Protocol

from loguru import logger
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from src.event_trees.read.models import EventForestSnapshot
from src.metrics.event_timeline_metrics import EventTimelinePlanBuildResult
from src.metrics.event_timeline_metrics import build_event_timeline_plan as compute_timeline_plan
from src.metrics.queries.fetchers import _fetch_chapter_progress_map
from src.storage.repositories.paragraph_repository import ParagraphRepository


class ChapterRepositoryProtocol(Protocol):
    def fetch_chapter_texts(self, run_id: str) -> list[tuple[int, str]]: ...


class StatsRepositoryProtocol(Protocol):
    @property
    def session(self) -> Session: ...


def build_event_timeline_plan(
    run_id: str,
    chapter_repo: ChapterRepositoryProtocol,
    stats_repo: StatsRepositoryProtocol,
    forest_snapshot: EventForestSnapshot | None,
) -> EventTimelinePlanBuildResult:
    try:
        chapter_texts = chapter_repo.fetch_chapter_texts(run_id)
    except (DBAPIError, ValueError, KeyError) as exc:
        logger.warning("build_event_timeline_plan fetch_chapter_texts fallback for run {}: {}", run_id, exc)
        chapter_texts = []
    try:
        rows = ParagraphRepository(stats_repo.session).fetch_chapter_tension_scores(run_id)
        tension_by_chapter = {int(cid): float(value) for cid, value in rows}
        progress_map = _fetch_chapter_progress_map(stats_repo.session, run_id)
        tension_available = True
    except (DBAPIError, ValueError, KeyError) as exc:
        logger.warning("build_event_timeline_plan tension fallback for run {}: {}", run_id, exc)
        tension_by_chapter, progress_map, tension_available = {}, {}, False
    return compute_timeline_plan(
        chapter_texts,
        forest_snapshot,
        tension_by_chapter=tension_by_chapter,
        progress_map=progress_map,
        tension_available=tension_available,
    )
