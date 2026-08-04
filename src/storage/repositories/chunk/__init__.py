"""导出 chunk 相关的样式、主题与 embedding 访问函数"""

from .embedding_ops import (
    ParagraphEmbeddingRow,
    SimilarChunkRow,
    SimilarParagraphRow,
    get_chunk_embedding,
    get_incomplete_paragraph_embedding_chunk_ids,
    get_missing_embedding_chunk_ids,
    has_embeddings,
    has_paragraph_embeddings,
    insert_chunk_embeddings,
    insert_paragraph_embeddings,
    search_similar_chunks,
    search_similar_paragraphs,
    search_similar_paragraphs_within_chunks,
)
from .keyword_ops import KeywordMatchRow, fetch_chunk_text, search_paragraphs_by_keywords
from .style_data import ChunkStyleData
from .style_ops import (
    fetch_chunk_imagery_lexicon_densities,
    fetch_chunk_styles,
    fetch_chunk_styles_full,
    insert_chunk_style,
)
from .topic_ops import clear_chunk_topics, fetch_chunk_topics_agg, insert_chunk_topics

__all__ = [
    "ChunkStyleData",
    "KeywordMatchRow",
    "fetch_chunk_text",
    "search_paragraphs_by_keywords",
    "fetch_chunk_styles",
    "insert_chunk_style",
    "fetch_chunk_styles_full",
    "fetch_chunk_imagery_lexicon_densities",
    "insert_chunk_topics",
    "clear_chunk_topics",
    "fetch_chunk_topics_agg",
    "insert_chunk_embeddings",
    "insert_paragraph_embeddings",
    "get_incomplete_paragraph_embedding_chunk_ids",
    "get_missing_embedding_chunk_ids",
    "get_chunk_embedding",
    "search_similar_chunks",
    "search_similar_paragraphs",
    "search_similar_paragraphs_within_chunks",
    "has_embeddings",
    "has_paragraph_embeddings",
    "SimilarChunkRow",
    "SimilarParagraphRow",
    "ParagraphEmbeddingRow",
]
