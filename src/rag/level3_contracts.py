"""
Level3 消费者意图驱动合同。

创建时间: 2026-04-25
任务: level3-intent-phase-split
说明: 收口 Level3Request / QueryPlan / 请求指纹，避免 workflow/provider 继续通过弱语义参数耦合。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.rag.mention_query import MentionEvidenceQuery

Level3Objective = Literal["identity", "emotion", "relation", "foreshadowing"]
Level3QueryMode = Literal["direct", "high_order", "hybrid"]


@dataclass(frozen=True, slots=True)
class Level3Request:
    """
    创建时间: 2026-04-25
    任务: level3-intent-phase-split
    说明: Level3 唯一正式输入合同；消费者必须显式声明目标、预算和是否允许 LLM query expansion。
    """

    objective: Level3Objective
    query_text: str
    seed_entities: list[str]
    current_chunk: int | None
    max_chunk_id: int | None
    exclude_chunk_ids: list[int]
    allow_llm_query_expansion: bool
    top_k: int
    max_queries: int
    model_rerank_query_max_chars: int


@dataclass(frozen=True, slots=True)
class Level3QueryPlan:
    """
    创建时间: 2026-04-25
    任务: level3-intent-phase-split
    说明: 将 query planning 与 retrieval execution 解耦；plan 只描述如何检索，不负责真正执行。
    """

    mode: Level3QueryMode
    base_query_text: str
    mention_queries: list[MentionEvidenceQuery]
    candidate_pool_k: int
    top_k: int


def build_level3_request_fingerprint(request: Level3Request) -> tuple[object, ...]:
    """
    创建时间: 2026-04-25
    任务: level3-intent-phase-split
    说明: 对显式请求做稳定指纹，用于 Phase1/Phase3 这类“合同完全一致则直接复用 bundle”的场景。
    """

    normalized_query = request.query_text.strip()
    normalized_seed_entities = tuple(
        dict.fromkeys(entity.strip() for entity in request.seed_entities if entity.strip())
    )
    normalized_excludes = tuple(dict.fromkeys(request.exclude_chunk_ids))
    return (
        request.objective,
        normalized_query,
        normalized_seed_entities,
        request.current_chunk,
        request.max_chunk_id,
        normalized_excludes,
        request.allow_llm_query_expansion,
        request.top_k,
        request.max_queries,
        request.model_rerank_query_max_chars,
    )
