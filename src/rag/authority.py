from __future__ import annotations

from src.knowledge.authority import ActiveEntityContext, KnowledgeGraphAuthorityService, Level1AuthoritySnapshot


class Level1AuthorityProvider:
    """Compatibility adapter that exposes authority views to evidence consumers."""

    def __init__(self, graph_repo) -> None:
        self._service = KnowledgeGraphAuthorityService(graph_repo)

    def build_snapshot(self, run_id: str) -> Level1AuthoritySnapshot:
        return self._service.build_level1_snapshot(run_id)

    def build_active_entity_contexts(
        self,
        run_id: str,
        current_chunk: int,
        lookback: int = 10,
    ) -> list[ActiveEntityContext]:
        return self._service.build_active_entity_view(run_id, current_chunk=current_chunk, lookback=lookback)
