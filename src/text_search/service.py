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
from src.storage.models import Paragraph
from src.storage.repositories.chunk import search_paragraphs_by_keywords, search_similar_paragraphs

_WHOLE_QUERY_MAX_CHARS = 20
_SPLIT_RE = re.compile(r"[\s,，。；;：:、!?！？\"'（）()\[\]{}]+")


def extract_query_terms(query: str, *, max_whole_query_chars: int = _WHOLE_QUERY_MAX_CHARS) -> list[str]:
    """2026-08-12 用于从中英文查询中提取稳定关键词（NFC 归一化 + 小写 + 去重）

    整句原文仅在前缀长度受限时保留为词项；长句只保留拆分词项；
    长句无分隔符时返回空列表（不产生必然不命中的整句全表 LIKE 扫描）。
    """
    normalized = (
        unicodedata.normalize("NFC", query)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .strip()
        .lower()
    )
    if not normalized:
        return []
    terms = [term for term in _SPLIT_RE.split(normalized) if term]
    if len(normalized) > max_whole_query_chars:
        if not _SPLIT_RE.search(normalized):
            # 无分隔符时 re.split 退化为整句本身，必须丢弃避免整句 LIKE 扫描
            return []
        return list(dict.fromkeys(terms))
    return list(dict.fromkeys([normalized, *terms]))


@dataclass(frozen=True, slots=True)
class TextSearchCandidate:
    """2026-08-14 用于返回段落级原文定位候选且不赋予 Evidence 身份

    二期段落化：候选粒度固定为自然段（paragraph_id），同章多个候选段落
    不再按 chunk 合并；坐标字段直接取 paragraphs 事实源列。
    """

    chapter_id: int
    chunk_id: int
    paragraph_id: int
    excerpt: str
    keyword_score: float
    semantic_score: float | None
    local_start_char: int | None = None
    local_end_char: int | None = None
    global_start_char: int | None = None
    global_end_char: int | None = None


class _MergedCandidate(TypedDict):
    """2026-08-14 用于合并同一段落的关键词与语义定位分数"""

    excerpt: str
    keyword_score: float
    semantic_score: float | None
    local_start_char: int | None
    local_end_char: int | None
    global_start_char: int | None
    global_end_char: int | None


class TextSearchService:
    """2026-08-14 用于以关键词和段落向量联合定位同 run 原文段落"""

    def __init__(
        self,
        session: Session,
        *,
        run_id: str,
        embedding_client: EmbeddingClient | None = None,
        semantic_enabled: bool = True,
        semantic_top_k: int = 5,
    ) -> None:
        """2026-08-14 用于绑定单次 Agent 查询的 run 与语义检索配置"""
        self._session = session
        self._run_id = run_id
        self._embedding_client = embedding_client
        self._semantic_enabled = semantic_enabled
        self._semantic_top_k = semantic_top_k

    async def search(
        self,
        query: str,
        *,
        min_paragraph_id: int | None = None,
        max_paragraph_id: int | None = None,
        limit: int = 50,
    ) -> list[TextSearchCandidate]:
        """2026-08-14 用于合并关键词与 pgvector 分数并按段落返回候选

        二期段落化：不再按 chunk 合并——同章多个候选段落都是独立候选；
        仅当同一段落同时命中关键词与语义检索时合并为一条（两分取各自最优）。
        """
        normalized_query = query.strip()
        if not normalized_query:
            return []
        keyword_rows = search_paragraphs_by_keywords(
            self._session,
            self._run_id,
            extract_query_terms(normalized_query),
            top_k=max(limit * 2, 10),
            min_paragraph_id=min_paragraph_id,
            max_paragraph_id=max_paragraph_id,
        )
        merged: dict[int, _MergedCandidate] = {}
        for keyword_row in keyword_rows:
            merged[keyword_row.paragraph_id] = {
                "excerpt": keyword_row.paragraph_text,
                "keyword_score": float(keyword_row.match_count),
                "semantic_score": None,
                "local_start_char": keyword_row.local_start_char,
                "local_end_char": keyword_row.local_end_char,
                "global_start_char": keyword_row.global_start_char,
                "global_end_char": keyword_row.global_end_char,
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
                min_paragraph_id=min_paragraph_id,
                max_paragraph_id=max_paragraph_id,
            )
            for semantic_row in semantic_rows:
                candidate = merged.setdefault(
                    semantic_row.paragraph_id,
                    {
                        "excerpt": semantic_row.paragraph_text,
                        "keyword_score": 0.0,
                        "semantic_score": None,
                        "local_start_char": semantic_row.local_start_char,
                        "local_end_char": semantic_row.local_end_char,
                        "global_start_char": semantic_row.global_start_char,
                        "global_end_char": semantic_row.global_end_char,
                    },
                )
                semantic_score = float(semantic_row.similarity)
                previous_score = candidate["semantic_score"]
                if previous_score is None or semantic_score > previous_score:
                    candidate["semantic_score"] = semantic_score
                    candidate["excerpt"] = semantic_row.paragraph_text

        chapter_and_chunk_by_paragraph = {
            int(row.paragraph_id): (int(row.chapter_id), int(row.chunk_id))
            for row in self._session.execute(
                select(Paragraph.paragraph_id, Paragraph.chapter_id, Paragraph.chunk_id).where(
                    Paragraph.run_id == self._run_id,
                    Paragraph.paragraph_id.in_(list(merged)),
                )
            ).all()
        }
        candidates: list[TextSearchCandidate] = []
        for paragraph_id, payload in merged.items():
            meta = chapter_and_chunk_by_paragraph.get(paragraph_id)
            if meta is None:
                continue
            candidates.append(
                TextSearchCandidate(
                    chapter_id=meta[0],
                    chunk_id=meta[1],
                    paragraph_id=paragraph_id,
                    excerpt=str(payload["excerpt"]),
                    keyword_score=float(payload["keyword_score"]),
                    semantic_score=payload["semantic_score"],
                    local_start_char=payload["local_start_char"],
                    local_end_char=payload["local_end_char"],
                    global_start_char=payload["global_start_char"],
                    global_end_char=payload["global_end_char"],
                )
            )
        candidates.sort(
            key=lambda row: (
                -(row.semantic_score or 0.0),
                -row.keyword_score,
                row.paragraph_id,
            )
        )
        return candidates[: max(1, limit)]

    def read(self, paragraph_id: int, context_paragraphs: int = 1) -> str:
        """2026-08-14 用于读取同 run 候选段落的原文

        段落顺序按 paragraph_id；context_paragraphs > 0 时返回目标段 +
        前后各 N 段的拼接文本（边界处自然截断），段落文本用换行分隔。
        context_paragraphs = 0 时只返回目标段本身。
        """
        start = paragraph_id - max(0, context_paragraphs)
        end = paragraph_id + max(0, context_paragraphs)
        rows = self._session.execute(
            select(Paragraph.paragraph_id, Paragraph.text).where(
                Paragraph.run_id == self._run_id,
                Paragraph.paragraph_id >= start,
                Paragraph.paragraph_id <= end,
            ).order_by(Paragraph.paragraph_id.asc())
        ).all()
        if not any(int(row.paragraph_id) == paragraph_id for row in rows):
            raise ValueError(f"原文段落不存在或跨 run: paragraph_id={paragraph_id}")
        return "\n".join(str(row.text) for row in rows)
