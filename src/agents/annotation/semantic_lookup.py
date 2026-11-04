"""查询语义检索：用段落向量定位相近原文，再按事件证据映射到事件树、参与者与案例"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from src.embedding import EmbeddingClient, EmbeddingServiceError, format_query_instruct
from src.event_trees.semantic import event_paragraph_ids, paragraph_ranks, ranked_keys


def _run_blocking(coroutine) -> Any:
    """在独立线程与独立事件循环里执行异步取向量，同步工具直接等待结果"""
    outcome: dict[str, Any] = {}

    def runner() -> None:
        try:
            outcome["value"] = asyncio.run(coroutine)
        except BaseException as exc:  # noqa: BLE001 - 异常原样交回调用线程
            outcome["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


class SemanticLookup:
    """按查询向量取同 run 相近段落身份；未启用或服务不可用时返回 None 表示退回字面"""

    def __init__(self, session: Any, run_id: str) -> None:
        self._session, self._run_id = session, run_id

    def paragraph_ids(self, query: str, *, limit: int = 20) -> list[int] | None:
        """相似段落身份按相似度降序；语义未启用或依赖失败返回 None"""
        from src.config import settings

        config = settings.models.paragraph_embedding
        normalized = query.strip()
        if not normalized or not config.semantic_enabled:
            return None
        try:
            return _run_blocking(self._fetch(normalized, max(limit, 1)))
        except (EmbeddingServiceError, TimeoutError, ConnectionError):
            return None

    async def _fetch(self, query: str, limit: int) -> list[int]:
        client = EmbeddingClient()
        try:
            vector = await client.get_embedding(format_query_instruct(query))
        finally:
            await client.aclose()
        rows = self._session.paragraphs.search_similar_paragraphs(
            self._run_id,
            vector,
            top_k=limit,
            similarity_threshold=0.0,
        )
        return [int(row.paragraph_id) for row in rows]


__all__ = [
    "SemanticLookup",
    "event_paragraph_ids",
    "paragraph_ranks",
    "ranked_keys",
]
