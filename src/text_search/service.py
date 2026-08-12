"""
原文关键词与 pgvector 联合定位服务
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.local.embedding import EmbeddingClient
from src.storage.models import Chunk
from src.storage.repositories.chunk import search_paragraphs_by_keywords, search_similar_paragraphs

_WHOLE_QUERY_MAX_CHARS = 20


def extract_query_terms(query: str, *, max_whole_query_chars: int = _WHOLE_QUERY_MAX_CHARS) -> list[str]:
    """2026-08-12 用于从中英文查询中提取稳定关键词（NFC 归一化 + 小写 + 去重）

    整句原文仅在前缀长度受限时保留为词项；长句只保留拆分词项，
    避免产生一次必然不命中的整句全表 LIKE 扫描。
    """
    normalized = (
        unicodedata.normalize("NFC", query)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .strip()
        .lower()
    )
    terms = [
        term
        for term in re.split(r"[\s,，。；;：:、!?！？\"'（）()\[\]{}]+", normalized)
        if term
    ]
    candidates = [normalized, *terms]
    if len(normalized) > max_whole_query_chars:
        candidates = terms
    return list(dict.fromkeys(candidates))


@dataclass(frozen=True, slots=True)
class TextSearchCandidate:
    """2026-08-07 用于返回原文定位候选且不赋予 Evidence 身份"""

    chapter_id: int
    chunk_id: int
    excerpt: str
    keyword_score: float
    semantic_score: float | None


class _MergedCandidate(TypedDict):
    """2026-08-07 用于合并同一 chunk 的关键词与语义定位分数"""

    excerpt: str
    keyword_score: float
    semantic_score: float | None


class TextSearchService:
    """2026-08-07 用于以关键词和段落向量联合定位同 run 原文 chunk"""

    def __init__(
        self,
        session: Session,
        *,
        run_id: str,
        embedding_client: EmbeddingClient | None = None,
        semantic_enabled: bool = True,
        semantic_top_k: int = 5,
    ) -> None:
        """2026-08-07 用于绑定单次 Agent 查询的 run 与语义检索配置"""
        self._session = session
        self._run_id = run_id
        self._embedding_client = embedding_client
        self._semantic_enabled = semantic_enabled
        self._semantic_top_k = semantic_top_k

    async def search(
        self,
        query: str,
        *,
        min_chunk_id: int | None = None,
        max_chunk_id: int | None = None,
        limit: int = 50,
    ) -> list[TextSearchCandidate]:
        """2026-08-07 用于合并关键词与 pgvector 分数并按 chunk 返回候选"""
        normalized_query = query.strip()
        if not normalized_query:
            return []
        keyword_rows = search_paragraphs_by_keywords(
            self._session,
            self._run_id,
            extract_query_terms(normalized_query),
            top_k=max(limit * 2, 10),
            min_chunk_id=min_chunk_id,
            max_chunk_id=max_chunk_id,
        )
        merged: dict[int, _MergedCandidate] = {}
        for keyword_row in keyword_rows:
            merged[keyword_row.chunk_id] = {
                "excerpt": keyword_row.paragraph_text,
                "keyword_score": float(keyword_row.match_count),
                "semantic_score": None,
            }

        if self._semantic_enabled:
            if self._embedding_client is None:
                raise ValueError("原文语义检索已启用但 EmbeddingClient 未配置")
            query_embedding = await self._embedding_client.get_embedding(normalized_query)
            semantic_rows = search_similar_paragraphs(
                self._session,
                self._run_id,
                query_embedding,
                top_k=max(self._semantic_top_k, limit),
                similarity_threshold=0.0,
                min_chunk_id=min_chunk_id,
                max_chunk_id=max_chunk_id,
            )
            for semantic_row in semantic_rows:
                candidate = merged.setdefault(
                    semantic_row.chunk_id,
                    {
                        "excerpt": semantic_row.paragraph_text,
                        "keyword_score": 0.0,
                        "semantic_score": None,
                    },
                )
                semantic_score = float(semantic_row.similarity)
                previous_score = candidate["semantic_score"]
                if previous_score is None or semantic_score > previous_score:
                    candidate["semantic_score"] = semantic_score
                    candidate["excerpt"] = semantic_row.paragraph_text

        chapter_by_chunk = {
            int(row.chunk_id): int(row.chapter_id)
            for row in self._session.execute(
                select(Chunk.chunk_id, Chunk.chapter_id).where(
                    Chunk.run_id == self._run_id,
                    Chunk.chunk_id.in_(list(merged)),
                )
            ).all()
        }
        candidates = [
            TextSearchCandidate(
                chapter_id=chapter_by_chunk[chunk_id],
                chunk_id=chunk_id,
                excerpt=str(payload["excerpt"]),
                keyword_score=float(payload["keyword_score"]),
                semantic_score=payload["semantic_score"],
            )
            for chunk_id, payload in merged.items()
            if chunk_id in chapter_by_chunk
        ]
        candidates.sort(
            key=lambda row: (
                -(row.semantic_score or 0.0),
                -row.keyword_score,
                row.chunk_id,
            )
        )
        return candidates[: max(1, limit)]

    def read(self, chunk_id: int) -> str:
        """2026-08-07 用于读取同 run 候选 chunk 的完整原文"""
        content = self._session.execute(
            select(Chunk.text).where(
                Chunk.run_id == self._run_id,
                Chunk.chunk_id == chunk_id,
            )
        ).scalar_one_or_none()
        if content is None:
            raise ValueError(f"原文 chunk 不存在或跨 run: chunk_id={chunk_id}")
        return str(content)