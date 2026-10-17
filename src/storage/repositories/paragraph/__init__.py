"""导出段落检索与 embedding 访问函数

2026-08-14 M8b：style_data/style_ops（chunk_style 链）已删除——风格指标以
paragraph_metrics 的充分统计量为事实源。

2026-10-16 全库 3NF 改造：新增段落派生观测写入函数（表面张力 z、功能词/
语义类别计数），供预处理链在段落行落库后同事务写入。
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
