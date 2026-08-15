"""导出段落检索与 embedding 访问函数

2026-08-14 M8b：style_data/style_ops（chunk_style 链）已删除——风格指标以
paragraph_metrics 的充分统计量为事实源。
"""

from .embedding_ops import (
    ParagraphEmbeddingRow,
    SimilarParagraphRow,
    get_incomplete_paragraph_embedding_paragraph_ids,
    has_paragraph_embeddings,
    insert_paragraph_embeddings,
    search_similar_paragraphs,
)
from .keyword_ops import KeywordMatchRow, fetch_chunk_text, search_paragraphs_by_keywords

__all__ = [
    "KeywordMatchRow",
    "fetch_chunk_text",
    "search_paragraphs_by_keywords",
    "insert_paragraph_embeddings",
    "get_incomplete_paragraph_embedding_paragraph_ids",
    "search_similar_paragraphs",
    "has_paragraph_embeddings",
    "SimilarParagraphRow",
    "ParagraphEmbeddingRow",
]
