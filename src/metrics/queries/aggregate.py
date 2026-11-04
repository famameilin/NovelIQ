"""指标取数与结果缓存，业务计算委托本模块的纯聚合入口"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from threading import Lock

from src.config import settings
from src.metrics.aggregate import aggregate_all_metrics
from src.metrics.aggregate.computers import compute_narrative_structure_metrics
from src.metrics.aggregate.types import AggregateInputs, AggregateResult
from src.metrics.queries.fetchers import (
    fetch_annotation_data,
    fetch_character_data,
    fetch_dialogue_data,
    fetch_emotion_data,
    fetch_relation_data,
    fetch_style_data,
    fetch_tension_data,
    fetch_text_data,
)
from src.storage import Storage
from src.storage.records.annotation import ChapterAnnotationRow


def query_narrative_structure(run_id: str, storage: Storage) -> dict[str, object]:
    """仅读取叙事结构计算所需的标注和章节张力"""
    return compute_narrative_structure_metrics(
        fetch_annotation_data(storage, run_id),
        fetch_tension_data(storage, run_id),
        small_sample_min_chapters=settings.metrics.small_sample_min_chapters,
    )


def query_aggregate_metrics(
    run_id: str, storage: Storage, *, annotation_rows: Sequence[ChapterAnnotationRow] | None = None,
) -> AggregateResult:
    inputs = AggregateInputs(
        annotation=fetch_annotation_data(storage, run_id, rows=annotation_rows),
        emotion=fetch_emotion_data(storage, run_id),
        characters=fetch_character_data(storage, run_id),
        relations=fetch_relation_data(storage, run_id),
        text=fetch_text_data(storage.chapters, run_id),
        tension=fetch_tension_data(storage, run_id),
        dialogue=fetch_dialogue_data(storage, run_id),
        style=fetch_style_data(storage, run_id),
        total_chars=storage.chapters.fetch_chapter_counts(run_id)[1],
    )
    return aggregate_all_metrics(inputs, small_sample_min_chapters=settings.metrics.small_sample_min_chapters)


class MetricsQueryService:
    """只缓存领域结果，不存储 HTTP 响应模型"""
    def __init__(self, cache_ttl: int = 300, *, clock: Callable[[], float] = time.time) -> None:
        self.cache_ttl = cache_ttl
        self.clock = clock
        self._cache: dict[str, tuple[AggregateResult, float]] = {}
        self._pending: dict[str, Future[AggregateResult]] = {}
        self._lock = Lock()

    def invalidate_cache(self, run_id: str) -> None:
        with self._lock:
            self._cache.pop(run_id, None)
            self._pending.pop(run_id, None)

    def get_aggregate_result(self, run_id: str, session: Storage) -> AggregateResult:
        with self._lock:
            cached = self._cache.get(run_id)
            if cached is not None and self.clock() - cached[1] < self.cache_ttl:
                return cached[0]
            pending = self._pending.get(run_id)
            owner = pending is None
            if pending is None:
                pending = Future()
                self._pending[run_id] = pending
        if not owner:
            return pending.result()
        try:
            result = query_aggregate_metrics(run_id, session)
        except BaseException as exc:
            with self._lock:
                if self._pending.get(run_id) is pending:
                    self._pending.pop(run_id, None)
            pending.set_exception(exc)
            raise
        with self._lock:
            if self._pending.get(run_id) is pending:
                self._cache[run_id] = (result, self.clock())
                self._pending.pop(run_id, None)
        pending.set_result(result)
        return result
