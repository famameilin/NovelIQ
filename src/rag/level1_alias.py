"""
RAG Level1 alias 查询边界。

单独承接别名缓存与查询职责，避免 retriever 同时维护多层证据细节。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from src.storage.repositories import GraphRepository


class AliasLookup:
    """
    Level1: 别名表精确匹配。

    保留原有缓存行为，但将 Level1 边界从 provider 主类中拆出。
    """

    def __init__(
        self,
        graph_repo: GraphRepository | None = None,
        run_id: str | None = None,
    ):
        self._graph_repo = graph_repo
        self._run_id = run_id
        self._cache: dict[str, str] | None = None

    def _ensure_cache(self) -> dict[str, str]:
        if self._cache is None:
            if self._graph_repo is None or self._run_id is None:
                self._cache = {}
            else:
                self._cache = self._graph_repo.fetch_alias_map(self._run_id)
        return self._cache

    def invalidate_cache(self) -> None:
        """清理别名缓存。"""
        self._cache = None

    def query(self, alias: str) -> str | None:
        """查询别名对应的 canonical。"""
        canonical = self._ensure_cache().get(alias)
        if canonical:
            logger.debug("AliasLookup: '{}' -> '{}'", alias, canonical)
        return canonical

    def get_alias_map(self) -> dict[str, str]:
        """返回当前缓存的完整别名映射只读副本。"""
        return dict(self._ensure_cache())
