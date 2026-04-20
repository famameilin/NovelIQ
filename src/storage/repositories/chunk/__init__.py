"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分chunk_repository.py
说明: chunk 子模块初始化

修改时间: 2026-04-10
修改者: TraeAI
任务: implement-level3-vector-retrieval
修改内容: 新增 embedding 操作函数导出
"""

from .embedding_ops import (
    get_chunk_embedding,
    get_missing_embedding_chunk_ids,
    has_embeddings,
    insert_chunk_embeddings,
    search_similar_chunks,
)
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
    "fetch_chunk_styles",
    "insert_chunk_style",
    "fetch_chunk_styles_full",
    "fetch_chunk_imagery_lexicon_densities",
    "insert_chunk_topics",
    "clear_chunk_topics",
    "fetch_chunk_topics_agg",
    "insert_chunk_embeddings",
    "get_missing_embedding_chunk_ids",
    "get_chunk_embedding",
    "search_similar_chunks",
    "has_embeddings",
]
