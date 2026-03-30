from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from src.storage.repositories import GraphRepository


@dataclass
class DisambigResult:
    """消歧上下文查询结果"""

    level1_hit: bool = False
    level2_candidates: list[str] = field(default_factory=list)
    canonical_name: str | None = None
    used_levels: list[int] = field(default_factory=list)


class AliasLookup:
    """Level1: 别名表精确匹配"""

    def __init__(
        self,
        graph_repo: GraphRepository | None = None,
        run_id: str | None = None,
    ):
        self._graph_repo = graph_repo
        self._run_id = run_id

    def query(self, alias: str) -> str | None:
        if self._graph_repo is None or self._run_id is None:
            return None
        canonical = self._graph_repo.fetch_alias_map(self._run_id).get(alias)
        if canonical:
            logger.debug(f"AliasLookup: '{alias}' -> '{canonical}'")
        return canonical

    def get_all_known_aliases(self) -> dict[str, str]:
        if self._graph_repo is None or self._run_id is None:
            return {}
        return self._graph_repo.fetch_alias_map(self._run_id)


class ActiveEntityLookup:
    """Level2: 近期活跃实体候选"""

    def __init__(self, graph_repo: GraphRepository | None = None, run_id: str | None = None):
        self._graph_repo = graph_repo
        self._run_id = run_id

    def get_active_candidates(
        self,
        current_chunk: int,
        lookback: int = 10,
    ) -> list[str]:
        if self._graph_repo is None or self._run_id is None:
            return []
        rows = self._graph_repo.fetch_active_entities(current_chunk, lookback, self._run_id)
        return [str(row["name"]) for row in rows]

    def get_all_known_aliases(self) -> dict[str, str]:
        if self._graph_repo is None or self._run_id is None:
            return {}
        return self._graph_repo.fetch_alias_map(self._run_id)


class DisambigContextProvider:
    """消歧上下文提供器

    为标注阶段提供别名消歧和活跃实体上下文。
    """

    def __init__(
        self,
        graph_repo: GraphRepository | None = None,
        novel_id: str = "default",
        run_id: str | None = None,
        lookback_chunks: int = 10,
    ):
        self._alias_lookup = AliasLookup(
            graph_repo=graph_repo,
            run_id=run_id,
        )
        self._active_lookup = ActiveEntityLookup(graph_repo=graph_repo, run_id=run_id)

        self._novel_id = novel_id
        self._run_id = run_id
        self._lookback_chunks = lookback_chunks

    def retrieve(
        self,
        alias: str,
        context_sentence: str | None = None,
        current_chunk: int | None = None,
    ) -> DisambigResult:
        logger.debug(f"DisambigContextProvider retrieve: alias='{alias}', chunk={current_chunk}")
        result = DisambigResult()

        canonical = self._alias_lookup.query(alias)
        if canonical:
            result.level1_hit = True
            result.canonical_name = canonical
            result.used_levels.append(1)
            logger.debug(f"DisambigContextProvider: Level1 hit, canonical='{canonical}'")
            return result

        if current_chunk is not None:
            candidates = self._active_lookup.get_active_candidates(current_chunk, self._lookback_chunks)
            if candidates:
                result.level2_candidates = candidates
                result.used_levels.append(2)
                logger.debug(f"DisambigContextProvider: Level2 candidates={candidates[:5]}")

        if not result.used_levels:
            logger.debug(f"DisambigContextProvider: no levels used for alias='{alias}'")

        return result

    def get_known_aliases(self) -> dict[str, str]:
        aliases = self._alias_lookup.get_all_known_aliases()
        if not aliases:
            aliases = self._active_lookup.get_all_known_aliases()
        return aliases

    def format_known_aliases_for_prompt(self) -> str:
        aliases = self.get_known_aliases()
        if not aliases:
            return ""

        alias_pairs = [f"{alias} → {canonical}" for alias, canonical in sorted(aliases.items())[:20]]
        return f"<Known_Aliases>\n{chr(10).join(alias_pairs)}\n</Known_Aliases>"
