"""
分块摘要和角色出场相关操作

分块摘要插入、角色出场信息插入等操作
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.storage.models import ChapterSummary

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def insert_chapter_summary(
    session: Session,
    run_id: str,
    chapter_id: int,
    summary: str,
    *,
    commit: bool = True,
) -> None:
    """
    插入分块摘要

    Args:
        session: 数据库会话
        run_id: 运行ID
        chapter_id: 分块ID
        summary: 摘要文本
    """
    now = datetime.now().isoformat()
    stmt = (
        pg_insert(ChapterSummary)
        .values(
            chapter_id=chapter_id,
            summary=summary,
            created_at=now,
            run_id=run_id,
        )
        .on_conflict_do_update(
            index_elements=["chapter_id", "run_id"],
            set_={
                "summary": summary,
                "created_at": now,
            },
        )
    )
    session.execute(stmt)
    if commit:
        session.commit()
    else:
        session.flush()
