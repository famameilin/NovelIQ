"""全局统计、模型回合计账与分析产物落库相关操作"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.storage.models import AnalysisOutput, GlobalStats, ModelTurn, Novel

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# 计账聚合只统计真实模型调用行；attempt_error 行是尝试结果登记，不是一次调用


def insert_global_stats(session: Session, run_id: str, stats: Iterable[tuple[str, float | None]]) -> None:
    """插入全局统计数据。"""
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


def fetch_global_stats_dict(session: Session, run_id: str) -> dict[str, float | None]:
    """获取全局统计数据字典。"""
    stmt = select(GlobalStats.stat_name, GlobalStats.stat_value).where(GlobalStats.run_id == run_id)
    result = session.execute(stmt).fetchall()
    return {row.stat_name: row.stat_value for row in result}


def insert_model_turn(
    session: Session,
    *,
    run_id: str,
    task_type: str,
    call_type: str,
    model: str,
    prompt_tokens: int,
    total_tokens: int,
    completion_tokens: int | None = None,
    chapter_id: int | None = None,
    cache_read_tokens: int | None = None,
    cost: float | None = None,
    accounting_source: str = "reported",
    reasoning_tokens: int | None = None,
    message_key: str | None = None,
) -> int:
    """插入非 Agent 模型调用的记账行（Agent 回合的计账由审计记录器内联在回合行上）。"""
    now = datetime.now(UTC).replace(tzinfo=None)
    turn = ModelTurn(
        row_kind="usage",
        run_id=run_id,
        task_type=task_type,
        call_type=call_type,
        model=model,
        chapter_id=chapter_id,
        status="success",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cache_read_tokens=cache_read_tokens if cache_read_tokens is not None else 0,
        reasoning_tokens=reasoning_tokens,
        cost=cost,
        accounting_source=accounting_source,
        started_at=now,
        finished_at=now,
        message_key=message_key,
    )
    session.add(turn)
    session.flush()
    return turn.id


def insert_agent_analysis(session: Session, run_id: str, payload: Mapping[str, Any]) -> str:
    """诊断产物以 kind=agent_analysis 追加进分析产物表，读侧取最新一行

    这里只落已由诊断 agent 校验过的字段面，不重复做领域校验。
    """
    row = AnalysisOutput(
        output_id=str(uuid4()),
        run_id=run_id,
        kind="agent_analysis",
        payload=dict(payload),
    )
    session.add(row)
    session.flush()
    return row.output_id


def fetch_agent_analysis(session: Session, run_id: str) -> dict[str, Any] | None:
    """读取当前诊断产物（最新一行），返回展平的合同字典"""
    result = session.execute(
        select(AnalysisOutput)
        .where(AnalysisOutput.run_id == run_id, AnalysisOutput.kind == "agent_analysis")
        .order_by(AnalysisOutput.created_at.desc(), AnalysisOutput.output_id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if result is None:
        return None
    return {**result.payload, "run_id": result.run_id}


def fetch_novel_title(session: Session, novel_id: str) -> str | None:
    """获取小说标题。"""
    return session.execute(select(Novel.title).where(Novel.novel_id == novel_id)).scalar_one_or_none()
