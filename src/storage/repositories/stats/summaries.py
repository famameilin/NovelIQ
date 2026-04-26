"""
分块摘要和角色出场相关操作

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 补充遗漏方法
说明: 分块摘要插入、角色出场信息插入等操作
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.storage.models import CharacterAppearance, ChunkSummary, StageSummary

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def insert_chunk_summary(
    session: Session,
    run_id: str,
    chunk_id: int,
    summary: str,
    *,
    commit: bool = True,
) -> None:
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
    if commit:
        session.commit()
    else:
        session.flush()


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


def insert_stage_summary(
    session: Session,
    run_id: str,
    start_chunk_id: int,
    end_chunk_id: int,
    summary: str,
) -> None:
    """
    插入阶段性摘要

    创建时间: 2026-04-08
    创建者: GLM-5
    任务: summary-full-chain-refactor
    说明: 存储增量消歧阶段生成的阶段性摘要

    Args:
        session: 数据库会话
        run_id: 运行ID
        start_chunk_id: 起始分块ID
        end_chunk_id: 结束分块ID
        summary: 阶段性摘要文本（100字以内）
    """
    now = datetime.now().isoformat()
    stage_summary = StageSummary(
        run_id=run_id,
        start_chunk_id=start_chunk_id,
        end_chunk_id=end_chunk_id,
        summary=summary,
        created_at=now,
    )
    session.add(stage_summary)
    session.commit()


def fetch_chunk_summaries_by_range(
    session: Session,
    run_id: str,
    start_chunk_id: int,
    end_chunk_id: int,
) -> list[tuple[int, str]]:
    """
    获取指定范围内的分块摘要

    创建时间: 2026-04-08
    创建者: GLM-5
    任务: summary-full-chain-refactor
    说明: 用于增量消歧阶段获取最近N个chunk的摘要

    Args:
        session: 数据库会话
        run_id: 运行ID
        start_chunk_id: 起始分块ID
        end_chunk_id: 结束分块ID

    Returns:
        (chunk_id, summary) 元组列表
    """
    from sqlalchemy import select

    stmt = (
        select(ChunkSummary.chunk_id, ChunkSummary.summary)
        .where(
            ChunkSummary.run_id == run_id,
            ChunkSummary.chunk_id >= start_chunk_id,
            ChunkSummary.chunk_id <= end_chunk_id,
        )
        .order_by(ChunkSummary.chunk_id)
    )
    result = session.execute(stmt)
    return [(row.chunk_id, row.summary) for row in result if row.summary]
