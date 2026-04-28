"""
Level3 模型 rerank 边界。

在 chunk 粗召回与 paragraph 局部 evidence 后接入可选模型精排；失败时由 provider 回退确定性 rerank。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from loguru import logger

if TYPE_CHECKING:
    from src.storage.repositories.chunk import SimilarChunkRow


@dataclass(frozen=True, slots=True)
class Level3RerankCandidate:
    """
    传给模型 rerank 的候选 DTO，显式携带 query、chunk 和 paragraph 分数。
    """

    query_text: str
    mention_text: str | None
    candidate_chunk_text: str
    candidate_local_preview: str | None
    chunk_id: int
    chunk_semantic_score: float | None
    paragraph_semantic_score: float | None
    business_rerank_score: float | None


@dataclass(frozen=True, slots=True)
class Level3RerankResult:
    """
    模型 rerank 输出，只负责排序分和可选解释，不改变 EvidenceBundle 主结构。
    """

    chunk_id: int
    model_rerank_score: float
    model_rerank_reason: str | None = None
    model_confidence: float | None = None


class Level3ModelReranker(Protocol):
    """
    模型 rerank 的最小协议；具体模型供应商由外层注入，provider 不创建新供应商配置。
    """

    async def rerank(
        self,
        *,
        query_text: str,
        candidates: list[Level3RerankCandidate],
        run_id: str | None = None,
        chunk_id: int | None = None,
    ) -> list[Level3RerankResult]:
        """返回候选 chunk 的模型排序分。"""


async def try_model_rerank_level3_results(
    results: list[SimilarChunkRow],
    *,
    query_text: str,
    reranker: Level3ModelReranker | None,
    run_id: str | None = None,
    chunk_id: int | None = None,
) -> list[SimilarChunkRow] | None:
    """
    尝试执行模型 rerank；没有模型或模型失败时返回 None，由 provider 显式 fallback。
    """
    if reranker is None or not results:
        return None
    candidates = [_to_candidate(result, query_text=query_text) for result in results]
    try:
        rerank_results = await reranker.rerank(
            query_text=query_text,
            candidates=candidates,
            run_id=run_id,
            chunk_id=chunk_id,
        )
    except Exception as exc:
        logger.warning("Level3 model rerank failed; falling back to deterministic rerank: {}", exc)
        return None

    score_by_chunk_id = {item.chunk_id: item for item in rerank_results}
    if not score_by_chunk_id:
        logger.info("Level3 model rerank returned no scores; falling back to deterministic rerank")
        return None

    reranked: list[SimilarChunkRow] = []
    for result in results:
        model_score = score_by_chunk_id.get(result.chunk_id)
        if model_score is None:
            reranked.append(replace(result, model_rerank_enabled=True, rerank_source="model"))
            continue
        reranked.append(
            replace(
                result,
                similarity=round(model_score.model_rerank_score, 6),
                model_rerank_score=round(model_score.model_rerank_score, 6),
                model_rerank_reason=model_score.model_rerank_reason,
                model_confidence=model_score.model_confidence,
                model_rerank_enabled=True,
                rerank_source="model",
                final_rank_score=round(model_score.model_rerank_score, 6),
            )
        )
    return sorted(reranked, key=_model_sort_key, reverse=True)


def _to_candidate(result: SimilarChunkRow, *, query_text: str) -> Level3RerankCandidate:
    """
    从仓储 DTO 转为模型 rerank DTO，优先暴露 paragraph local preview 作为局部 evidence。
    """
    return Level3RerankCandidate(
        query_text=query_text,
        mention_text=result.mention_text,
        candidate_chunk_text=result.text,
        candidate_local_preview=result.local_preview,
        chunk_id=result.chunk_id,
        chunk_semantic_score=result.chunk_semantic_score,
        paragraph_semantic_score=result.paragraph_semantic_score,
        business_rerank_score=result.business_rerank_score,
    )


def _model_sort_key(result: SimilarChunkRow) -> tuple[float, float, float, float, float, float, int]:
    """
    按文档约定的模型分优先级排序，并保留旧分数字段作为稳定兜底。
    """
    return (
        result.model_rerank_score if result.model_rerank_score is not None else float("-inf"),
        result.final_rank_score if result.final_rank_score is not None else float("-inf"),
        result.business_rerank_score if result.business_rerank_score is not None else float("-inf"),
        result.paragraph_semantic_score if result.paragraph_semantic_score is not None else float("-inf"),
        result.chunk_semantic_score if result.chunk_semantic_score is not None else float("-inf"),
        result.similarity,
        -result.chunk_id,
    )
