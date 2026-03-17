"""
指标统计相关操作

创建时间: 2026-03-17
创建者: TraeAI
任务: code-quality-refactor - 拆分stats_repository
说明: 全局统计和Token使用统计相关操作
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Tuple

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.storage.models import GlobalStats, TokenUsage

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def insert_global_stats(session: Session, run_id: str, stats: Iterable[Tuple[str, float]]) -> None:
    """
    插入全局统计数据

    Args:
        session: 数据库会话
        run_id: 运行ID
        stats: 统计数据迭代器 (stat_name, stat_value)
    """
    stats_list = list(stats)
    if not stats_list:
        return

    for stat_name, stat_value in stats_list:
        stmt = (
            pg_insert(GlobalStats)
            .values(
                stat_name=stat_name,
                stat_value=stat_value,
                run_id=run_id,
            )
            .on_conflict_do_update(
                index_elements=["stat_name", "run_id"],
                set_={
                    "stat_value": stat_value,
                },
            )
        )
        session.execute(stmt)
    session.commit()


def fetch_global_stats(session: Session, run_id: str) -> List[Tuple[str, float]]:
    """
    获取全局统计数据

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        (stat_name, stat_value) 元组列表
    """
    stmt = select(GlobalStats.stat_name, GlobalStats.stat_value).where(GlobalStats.run_id == run_id)
    result = session.execute(stmt)
    return [(row.stat_name, row.stat_value) for row in result.fetchall()]


def fetch_global_stats_dict(session: Session, run_id: str) -> Dict[str, float]:
    """
    获取全局统计数据字典

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        统计名称到值的映射字典
    """
    stmt = select(GlobalStats.stat_name, GlobalStats.stat_value).where(
        (GlobalStats.run_id == run_id) | (GlobalStats.run_id.is_(None))
    )
    result = session.execute(stmt).fetchall()
    return {row.stat_name: row.stat_value for row in result}


def insert_token_usage(
    session: Session,
    run_id: str,
    novel_id: str,
    task_type: str,
    call_type: str,
    model: str,
    prompt_tokens: int,
    total_tokens: int,
    completion_tokens: int | None = None,
    chunk_id: int | None = None,
) -> int | None:
    """
    插入 token 使用记录

    Args:
        session: 数据库会话
        run_id: 运行ID
        novel_id: 小说ID
        task_type: 任务类型
        call_type: 调用类型
        model: 模型名称
        prompt_tokens: 提示 token 数
        total_tokens: 总 token 数
        completion_tokens: 完成 token 数（可选）
        chunk_id: 分块ID（可选）

    Returns:
        插入记录的ID
    """
    from datetime import datetime

    now = datetime.now().isoformat()
    token_usage = TokenUsage(
        novel_id=novel_id,
        chunk_id=chunk_id,
        task_type=task_type,
        call_type=call_type,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        created_at=now,
        run_id=run_id,
    )
    session.add(token_usage)
    session.commit()
    return token_usage.id


def fetch_token_usage_stats(session: Session, run_id: str, novel_id: str) -> Dict[str, Any]:
    """
    获取 token 使用统计

    Args:
        session: 数据库会话
        run_id: 运行ID
        novel_id: 小说ID

    Returns:
        使用统计数据字典
    """
    summary = _fetch_usage_summary(session, run_id, novel_id)
    by_task = _fetch_usage_by_task(session, run_id, novel_id)
    by_model = _fetch_usage_by_model(session, run_id, novel_id)
    return {
        "summary": summary,
        "by_task": by_task,
        "by_model": by_model,
    }


def _fetch_usage_summary(session: Session, run_id: str, novel_id: str) -> Dict[str, Any]:
    """获取使用量摘要"""
    stmt = select(
        func.count().label("call_count"),
        func.sum(TokenUsage.prompt_tokens).label("total_prompt_tokens"),
        func.sum(func.coalesce(TokenUsage.completion_tokens, 0)).label("total_completion_tokens"),
        func.sum(TokenUsage.total_tokens).label("total_tokens"),
    ).where(
        TokenUsage.novel_id == novel_id,
        TokenUsage.run_id == run_id,
    )
    result = session.execute(stmt).fetchone()
    if result is None:
        return {
            "call_count": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
        }
    return {
        "call_count": result.call_count or 0,
        "total_prompt_tokens": result.total_prompt_tokens or 0,
        "total_completion_tokens": result.total_completion_tokens or 0,
        "total_tokens": result.total_tokens or 0,
    }


def _fetch_usage_by_task(session: Session, run_id: str, novel_id: str) -> Dict[str, Any]:
    """按任务类型获取使用量"""
    stmt = (
        select(
            TokenUsage.task_type,
            func.count().label("count"),
            func.sum(TokenUsage.total_tokens).label("total"),
        )
        .where(
            TokenUsage.novel_id == novel_id,
            TokenUsage.run_id == run_id,
        )
        .group_by(TokenUsage.task_type)
    )

    result = session.execute(stmt).fetchall()
    return {row.task_type: {"call_count": row.count, "total_tokens": row.total} for row in result}


def _fetch_usage_by_model(session: Session, run_id: str, novel_id: str) -> Dict[str, Any]:
    """按模型获取使用量"""
    stmt = (
        select(
            TokenUsage.model,
            func.count().label("count"),
            func.sum(TokenUsage.total_tokens).label("total"),
        )
        .where(
            TokenUsage.novel_id == novel_id,
            TokenUsage.run_id == run_id,
        )
        .group_by(TokenUsage.model)
    )

    result = session.execute(stmt).fetchall()
    return {row.model: {"call_count": row.count, "total_tokens": row.total} for row in result}
