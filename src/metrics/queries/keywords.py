"""关键词查询；TextRank 本身不访问数据库"""

from typing import Any

from src.metrics.aggregate.algorithms import compute_keywords
from src.storage import Storage


def query_keywords(run_id: str, session: Storage, top_n: int = 10) -> dict[str, Any]:
    texts = session.paragraphs.fetch_paragraph_texts(run_id)
    return compute_keywords(run_id, texts, top_n)
