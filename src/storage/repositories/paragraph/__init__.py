"""导出段落检索与 embedding 访问函数

段落派生观测（表面张力 z、功能词/语义类别计数）由预处理链在段落行落库后同事务写入。
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
from .writer import (
    insert_paragraph_function_word_counts,
    insert_paragraph_semantic_category_counts,
    insert_paragraph_tension_observations,
)

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
    "insert_paragraph_tension_observations",
    "insert_paragraph_function_word_counts",
    "insert_paragraph_semantic_category_counts",
]
