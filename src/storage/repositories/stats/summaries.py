"""
分块摘要和角色出场相关操作

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 补充遗漏方法
说明: 分块摘要插入、角色出场信息插入等操作
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.storage.models import CharacterAppearance, ChunkSummary

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def insert_chunk_summary(session: Session, run_id: str, chunk_id: int, summary: str) -> None:
    """
    插入分块摘要

    Args:
        session: 数据库会话
        run_id: 运行ID
        chunk_id: 分块ID
        summary: 摘要文本
    """
    now = datetime.now().isoformat()
    stmt = (
        pg_insert(ChunkSummary)
        .values(
            chunk_id=chunk_id,
            summary=summary,
            created_at=now,
            run_id=run_id,
        )
        .on_conflict_do_update(
            index_elements=["chunk_id", "run_id"],
            set_={
                "summary": summary,
                "created_at": now,
            },
        )
    )
    session.execute(stmt)
    session.commit()


def insert_character_appearances(session: Session, run_id: str, chunk_id: int, appearances: Sequence[Any]) -> None:
    """
    插入角色出场信息

    Args:
        session: 数据库会话
        run_id: 运行ID
        chunk_id: 分块ID
        appearances: 角色出场信息序列
    """
    if not appearances:
        return
    now = datetime.now().isoformat()
    for a in appearances:
        char_appearance = CharacterAppearance(
            chunk_id=chunk_id,
            raw_name=a.raw_name,
            identity_clue=a.identity_clue,
            clue_type=a.clue_type,
            created_at=now,
            run_id=run_id,
        )
        session.add(char_appearance)
    session.commit()
