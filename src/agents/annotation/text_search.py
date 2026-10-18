"""
原文关键词与 pgvector 联合定位服务
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.embedding import EmbeddingClient, EmbeddingServiceError, format_query_instruct
from src.storage.models import Chapter, Paragraph
from src.storage.query_terms import extract_query_terms
from src.storage.repositories.paragraph import search_paragraphs_by_keywords, search_similar_paragraphs

from .errors import AnnotationDependencyError

__all__ = ["TextSearchCandidate", "TextSearchService", "extract_query_terms"]


@dataclass(frozen=True, slots=True)
class TextSearchCandidate:
    """用于返回段落级原文定位候选且不赋予 Evidence 身份

    候选粒度固定为自然段（paragraph_id），同章多个候选段落不按 chunk 合并；
    坐标字段直接取 paragraphs 事实源列。
    """

    chapter_id: int
    paragraph_id: int
    excerpt: str
    keyword_score: float
    semantic_score: float | None
    local_start_char: int | None = None
    local_end_char: int | None = None
    global_start_char: int | None = None
    global_end_char: int | None = None


class _MergedCandidate(TypedDict):
    """用于合并同一段落的关键词与语义定位分数"""

    excerpt: str
    keyword_score: float
    semantic_score: float | None
    local_start_char: int | None
    local_end_char: int | None
    global_start_char: int | None
    global_end_char: int | None


class TextSearchService:
    """用于以关键词和段落向量联合定位同 run 原文段落"""

    def __init__(
        self,
        session: Session,
        *,
        run_id: str,
        embedding_client: EmbeddingClient | None = None,
        semantic_enabled: bool = True,
        semantic_top_k: int = 5,
    ) -> None:
        """用于绑定单次 Agent 查询的 run 与语义检索配置"""
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
        before_chapter_sequence: int | None = None,
        after_chapter_sequence: int | None = None,
        limit: int = 50,
    ) -> list[TextSearchCandidate]:
        """用于合并关键词与 pgvector 分数并按段落返回候选

        同章多个候选段落都是独立候选，不按 chunk 合并；
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
            before_chapter_sequence=before_chapter_sequence,
            after_chapter_sequence=after_chapter_sequence,
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
                raise AnnotationDependencyError("原文语义检索已启用但 EmbeddingClient 未配置")
            try:
                query_embedding = await self._embedding_client.get_embedding(format_query_instruct(normalized_query))
            except EmbeddingServiceError as exc:
                # 依赖故障不能伪装成可由模型改参数修复的工具拒绝
                raise AnnotationDependencyError(str(exc)) from exc
            semantic_rows = search_similar_paragraphs(
                self._session,
                self._run_id,
                query_embedding,
                top_k=max(self._semantic_top_k, limit),
                similarity_threshold=0.0,
                min_paragraph_id=min_paragraph_id,
                max_paragraph_id=max_paragraph_id,
                before_chapter_sequence=before_chapter_sequence,
                after_chapter_sequence=after_chapter_sequence,
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

        metadata_statement = (
            select(Paragraph.paragraph_id, Paragraph.chapter_id)
            .join(
                Chapter,
                (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id),
            )
            .where(
                Paragraph.run_id == self._run_id,
                Paragraph.paragraph_id.in_(list(merged)),
            )
        )
        if before_chapter_sequence is not None:
            metadata_statement = metadata_statement.where(Chapter.sequence < before_chapter_sequence)
        if after_chapter_sequence is not None:
            metadata_statement = metadata_statement.where(Chapter.sequence > after_chapter_sequence)
        chapter_by_paragraph = {
            int(row.paragraph_id): int(row.chapter_id) for row in self._session.execute(metadata_statement).all()
        }
        candidates: list[TextSearchCandidate] = []
        for paragraph_id, payload in merged.items():
            meta = chapter_by_paragraph.get(paragraph_id)
            if meta is None:
                continue
            candidates.append(
                TextSearchCandidate(
                    chapter_id=meta,
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
