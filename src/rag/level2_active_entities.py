"""
RAG Level2 活跃实体查询边界。

将近期活跃实体候选查询从 provider 主类中分离，形成独立边界。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.storage.repositories import GraphRepository


class ActiveEntityLookup:
    """
    Level2: 近期活跃实体候选。

    统一封装活跃实体查询输出，避免上层直接依赖 repository 返回形状。
    """

    def __init__(self, graph_repo: GraphRepository | None = None, run_id: str | None = None):
        self._graph_repo = graph_repo
        self._run_id = run_id

    def get_active_candidates(
        self,
        current_chunk: int,
        lookback: int = 10,
    ) -> list[str]:
        """
        获取近期活跃实体名称候选。

        读取 ActiveEntityRow.name，避免依赖 repository raw dict。
        """
        if self._graph_repo is None or self._run_id is None:
            return []
        rows = self._graph_repo.fetch_active_entities(current_chunk, lookback, self._run_id)
        return [str(row.get("name", "")) if isinstance(row, dict) else str(row.name) for row in rows]
