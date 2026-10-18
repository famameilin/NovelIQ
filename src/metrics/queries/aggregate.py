"""指标取数与结果缓存，业务计算委托本模块的纯聚合入口"""

from __future__ import annotations

import time
from collections.abc import Callable

from src.config import settings
from src.metrics.aggregate import aggregate_all_metrics
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


def query_aggregate_metrics(run_id: str, storage: Storage) -> AggregateResult:
    inputs = AggregateInputs(
        annotation=fetch_annotation_data(storage, run_id),
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

    def invalidate_cache(self, run_id: str) -> None:
        self._cache.pop(run_id, None)

    def get_aggregate_result(self, run_id: str, session: Storage) -> AggregateResult:
        cached = self._cache.get(run_id)
        if cached is not None and self.clock() - cached[1] < self.cache_ttl:
            return cached[0]
        result = query_aggregate_metrics(run_id, session)
        self._cache[run_id] = (result, self.clock())
        return result
