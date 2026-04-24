"""
Level3 LLM rerank 实现。

创建时间: 2026-04-24
任务: llm-mention-rerank-chain
说明: 复用现有 BaseModelClient 结构化输出能力，将候选 chunk/paragraph 小池交给模型做最终精排。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from src.rag.model_rerank import Level3RerankCandidate, Level3RerankResult


class LLMLevel3RerankItem(BaseModel):
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 单条模型 rerank 结果 schema，只返回排序相关字段，不越权改写 evidence contract。
    """

    chunk_id: int
    model_rerank_score: float
    model_rerank_reason: str | None = None
    model_confidence: float | None = None


class LLMLevel3RerankResponse(BaseModel):
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: Level3 rerank 的顶层结构化响应。
    """

    results: list[LLMLevel3RerankItem] = Field(default_factory=list)


class LLMLevel3Reranker:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 使用结构化 JSON 输出执行 Level3 模型 rerank；模型只负责排序，不负责人物身份结论。
    """

    def __init__(self, model_client: Any, *, enable_thinking: bool = False) -> None:
        self._model_client = model_client
        self._enable_thinking = enable_thinking

    async def rerank(
        self,
        *,
        query_text: str,
        candidates: list[Level3RerankCandidate],
    ) -> list[Level3RerankResult]:
        """
        创建时间: 2026-04-24
        任务: llm-mention-rerank-chain
        说明: 调用 LLM 对小池候选做重排；若模型调用失败，由 provider 显式回退 deterministic rerank。
        """
        if not candidates:
            return []

        messages = _build_messages(query_text=query_text, candidates=candidates)
        timeout = getattr(self._model_client, "_config", None) and getattr(
            self._model_client._config, "timeout_s", None
        )
        response = await self._model_client._call_api(
            messages,
            enable_thinking=self._enable_thinking,
            response_model=LLMLevel3RerankResponse,
            timeout=timeout,
        )
        parsed = (
            response
            if isinstance(response, LLMLevel3RerankResponse)
            else self._model_client._parse_structured_response(response, LLMLevel3RerankResponse)
        )
        return _normalize_results(parsed.results)


def _build_messages(
    *,
    query_text: str,
    candidates: list[Level3RerankCandidate],
) -> list[dict[str, str]]:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 构造 rerank 请求，显式提示模型优先比较同一人物证据而不是泛场景相似度。
    """
    candidate_payload = [
        {
            "chunk_id": candidate.chunk_id,
            "mention_text": candidate.mention_text,
            "candidate_local_preview": candidate.candidate_local_preview,
            "candidate_chunk_text": candidate.candidate_chunk_text,
            "chunk_semantic_score": candidate.chunk_semantic_score,
            "paragraph_semantic_score": candidate.paragraph_semantic_score,
            "business_rerank_score": candidate.business_rerank_score,
        }
        for candidate in candidates
    ]
    user_content = (
        "请对候选历史证据做 rerank，只输出 JSON。\n"
        "目标：优先把与 query 所指向同一人物/角色最一致的证据排前，不要把泛场景相似误判为同一人。\n"
        "约束：不生成新候选，不改写 chunk_id，不输出最终身份结论。\n"
        "请为每个候选返回 model_rerank_score，分数越高表示越相关；可选返回简短 reason 与 confidence。\n"
        f"query:\n{query_text}\n"
        "candidates:\n"
        f"{json.dumps(candidate_payload, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": "你是小说 Level3 rerank 模块，只输出结构化 JSON。"},
        {"role": "user", "content": user_content},
    ]


def _normalize_results(results: list[LLMLevel3RerankItem]) -> list[Level3RerankResult]:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 对模型输出按 chunk_id 去重，保留最高分结果，避免异常重复响应干扰 provider 排序。
    """
    best_by_chunk_id: dict[int, Level3RerankResult] = {}
    for item in results:
        normalized = Level3RerankResult(
            chunk_id=item.chunk_id,
            model_rerank_score=float(item.model_rerank_score),
            model_rerank_reason=item.model_rerank_reason,
            model_confidence=item.model_confidence,
        )
        existing = best_by_chunk_id.get(normalized.chunk_id)
        if existing is None or normalized.model_rerank_score > existing.model_rerank_score:
            best_by_chunk_id[normalized.chunk_id] = normalized
    return list(best_by_chunk_id.values())
