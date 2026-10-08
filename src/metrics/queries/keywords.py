"""关键词查询；TextRank 本身不访问数据库"""

from typing import Any

from sqlalchemy.orm import Session

from src.metrics.aggregate.algorithms import compute_keywords
from src.storage.repositories.paragraph_repository import ParagraphRepository


def query_keywords(run_id: str, session: Session, top_n: int = 10) -> dict[str, Any]:
    rows = ParagraphRepository(session).fetch_paragraph_rows(run_id)
    return compute_keywords(run_id, [row.text for row in rows], top_n)
