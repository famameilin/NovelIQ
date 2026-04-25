"""
Level3 mention extraction 编排服务。

创建时间: 2026-04-24
任务: llm-mention-rerank-chain
说明: provider 只调用本服务；服务先尝试 LLM extractor，再回退规则 extractor，并统一做后处理过滤。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from loguru import logger

from src.rag.mention_extraction import extract_person_mentions
from src.rag.mention_extraction_types import MentionExtractionRequest, PersonMention


class PersonMentionExtractor(Protocol):
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: LLM mention extractor 的最小协议；具体供应商由外层注入，service 不暗猜模型来源。
    """

    async def extract_mentions(self, request: MentionExtractionRequest) -> list[PersonMention]:
        """从 request.text 中抽取人物 mention。"""


class MentionExtractionService:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 统一编排 LLM 主路径与规则 fallback，避免 workflow 层散落 mention extraction 逻辑。
    """

    def __init__(self, llm_extractor: PersonMentionExtractor | None = None) -> None:
        self._llm_extractor = llm_extractor

    async def extract_mentions(
        self,
        request: MentionExtractionRequest,
        *,
        prefer_llm: bool = True,
    ) -> list[PersonMention]:
        """
        创建时间: 2026-04-24
        任务: llm-mention-rerank-chain
        说明: 优先执行 LLM 抽取；模型不可用或返回空结果时回退规则抽取，并显式记录回退原因。

        修改时间: 2026-04-25
        任务: fix-level3-relation-query-expansion-contract
        修改内容: 支持调用方显式关闭 LLM 主路径；relation 这类“允许受限扩展但不默认走 LLM”
                  的 objective 可直接复用规则 extractor，而不必复制一套 service。
        """
        if prefer_llm and self._llm_extractor is not None:
            try:
                llm_mentions = await self._llm_extractor.extract_mentions(request)
            except Exception as exc:
                logger.warning("LLM mention extraction failed; falling back to rule extractor: {}", exc)
            else:
                normalized = normalize_person_mentions(llm_mentions, request=request, fallback_source="llm")
                if normalized:
                    return normalized
                logger.info("LLM mention extraction returned no usable mentions; falling back to rule extractor")

        rule_mentions = extract_person_mentions(request.text)
        return normalize_person_mentions(rule_mentions, request=request, fallback_source="rule")


def normalize_person_mentions(
    mentions: list[PersonMention],
    *,
    request: MentionExtractionRequest,
    fallback_source: str,
) -> list[PersonMention]:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 对 LLM/规则 mention 做统一去重和护栏过滤，避免 hallucination、纯实名或过宽 mention 进入 query 层。
    """
    normalized: list[PersonMention] = []
    seen: set[tuple[str, str]] = set()
    current_names = {name.strip() for name in request.names_in_chunk if name.strip()}
    source_text = request.text or ""

    for mention in mentions:
        raw_text = mention.raw_text.strip()
        sentence_text = mention.sentence_text.strip()
        if not raw_text:
            continue
        if raw_text in current_names:
            continue
        if _is_unrelated_to_request(raw_text, sentence_text, source_text):
            continue
        if _is_too_broad(mention):
            continue

        key = (raw_text, sentence_text)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            replace(
                mention,
                raw_text=raw_text,
                sentence_text=sentence_text,
                source=mention.source or fallback_source,
                normalized_query_terms=_normalize_query_terms(mention.normalized_query_terms),
            )
        )

    return normalized


def _is_unrelated_to_request(raw_text: str, sentence_text: str, source_text: str) -> bool:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: LLM 输出必须能在原文中找到 raw mention 或其句子，防止把外部猜测塞入 retrieval。
    """
    if raw_text in source_text:
        return False
    if sentence_text and sentence_text in source_text:
        return False
    return True


def _is_too_broad(mention: PersonMention) -> bool:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 缺少外貌/动作/位置/归一化特征的纯角色指代不进入主 query 池，降低噪声。
    """
    if mention.normalized_query_terms:
        return False
    cues = mention.cues
    has_distinctive_cues = any(cues.get(key) for key in ("appearance", "action", "location"))
    if has_distinctive_cues:
        return False
    return mention.mention_type in {"pronoun_role", "role_based"}


def _normalize_query_terms(terms: tuple[str, ...]) -> tuple[str, ...]:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: LLM normalized_query_terms 进入 query builder 前先去空、去重，保持稳定顺序。
    """
    normalized: list[str] = []
    for term in terms:
        text = str(term).strip()
        if text and text not in normalized:
            normalized.append(text)
    return tuple(normalized)
