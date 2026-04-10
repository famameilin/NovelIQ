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
    """Level1: 别名表精确匹配（带缓存）"""

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
        self._cache = None

    def query(self, alias: str) -> str | None:
        canonical = self._ensure_cache().get(alias)
        if canonical:
            logger.debug(f"AliasLookup: '{alias}' -> '{canonical}'")
        return canonical

    def get_alias_map(self) -> dict[str, str]:
        """返回当前缓存的完整别名映射（只读副本）。"""
        return dict(self._ensure_cache())


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


class DisambigContextProvider:
    """消歧上下文提供器

    为标注阶段提供别名消歧和活跃实体上下文。
    支持两级检索：Level1 精确匹配 + Level2 活跃实体候选。
    同时提供图谱反馈能力：已裁决别名映射 + 已确认关系。
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

        self._graph_repo = graph_repo
        self._novel_id = novel_id
        self._run_id = run_id
        self._lookback_chunks = lookback_chunks
        self._relations_cache: list[dict] | None = None

    def invalidate_cache(self) -> None:
        """别名映射和关系缓存失效（每个 chunk 处理后调用，因为 projection 可能更新了别名表）"""
        self._alias_lookup.invalidate_cache()
        self._relations_cache = None

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

    def build_disambig_context(
        self,
        names_in_chunk: list[str],
        current_chunk: int | None = None,
    ) -> str:
        """对 chunk 中出现的名字逐个执行层级检索，生成消歧线索文本。

        - Level1 精确命中：直接追加到 alias_map，不生成额外线索
        - Level2 候选集：生成 <Disambig_Candidates> 供 LLM 参考
        - 未命中：不生成任何线索
        """
        if not names_in_chunk:
            return ""

        disambig_parts: list[str] = []

        for name in names_in_chunk:
            result = self.retrieve(name, current_chunk=current_chunk)
            if result.level1_hit:
                # 精确命中不需要额外线索，alias_map 中已有
                pass
            elif result.level2_candidates:
                candidates_str = "、".join(result.level2_candidates[:5])
                disambig_parts.append(f"- 「{name}」可能是：{candidates_str}")

        if not disambig_parts:
            return ""

        return "<Disambig_Candidates>\n" + "\n".join(disambig_parts) + "\n</Disambig_Candidates>"

    def build_graph_feedback_hint(
        self,
        existing_names: list[str],
        base_hint: str | None = None,
    ) -> str | None:
        """构建图谱反馈提示，包含已裁决别名映射和已确认关系。

        统一消歧阶段和标注阶段的图谱数据查询逻辑，
        替代散落在各处的直接 GraphRepository 调用。
        """
        if self._graph_repo is None or self._run_id is None:
            return base_hint

        existing_set = set(existing_names)
        parts: list[str] = []

        if base_hint:
            parts.append(base_hint)

        # 1. 已裁决的别名映射（复用 AliasLookup 缓存）
        alias_map = self._alias_lookup.get_alias_map()
        graph_aliases = {a: c for a, c in alias_map.items() if a != c and c in existing_set}
        if graph_aliases:
            alias_lines = ["【图谱已裁决的别名映射】"]
            for alias, canonical in sorted(graph_aliases.items()):
                alias_lines.append(f"- {alias} → {canonical}")
            parts.append("\n".join(alias_lines))
            logger.debug(f"Graph feedback: injected {len(graph_aliases)} alias mappings")

        # 2. 当前活跃关系（带缓存，与 AliasLookup 缓存同步失效）
        if self._relations_cache is None:
            self._relations_cache = self._graph_repo.fetch_current_relations(self._run_id, active_only=True)
        relations = self._relations_cache
        relevant_rels = [r for r in relations if r["from_name"] in existing_set or r["to_name"] in existing_set]
        if relevant_rels:
            rel_lines = ["【图谱已确认的关系】"]
            for r in relevant_rels[:10]:
                rel_lines.append(f"- {r['from_name']} ←{r['type']}→ {r['to_name']}")
            parts.append("\n".join(rel_lines))
            logger.debug(f"Graph feedback: injected {len(relevant_rels)} relations")

        if not parts:
            return base_hint

        return "\n".join(parts)
