from __future__ import annotations

from src.knowledge.authority import KnowledgeGraphAuthorityService, Level1AuthoritySnapshot


class Level1AuthorityProvider:
    """Compatibility adapter that exposes the minimal Level 1 snapshot to evidence."""

    def __init__(self, graph_repo) -> None:
        self._service = KnowledgeGraphAuthorityService(graph_repo)

    def build_snapshot(self, run_id: str) -> Level1AuthoritySnapshot:
        return self._service.build_level1_snapshot(run_id)
