"""全局统计、模型回合计账与分析产物落库相关操作"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.agents.diagnosis.schema import AgentAnalysis as AgentAnalysisSchema
from src.storage.models import AnalysisOutput, GlobalStats, ModelTurn, Novel

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# 计账聚合只统计真实模型调用行；attempt_error 行是尝试结果登记，不是一次调用
_USAGE_ROW_KINDS = ("agent_turn", "usage")


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


def fetch_token_usage_stats(session: Session, run_id: str) -> dict[str, Any]:
    """获取模型回合的 token 使用统计。"""
    summary = _fetch_usage_summary(session, run_id)
    by_task = _fetch_usage_by_task(session, run_id)
    by_call_type = _fetch_usage_by_call_type(session, run_id)
    by_model = _fetch_usage_by_model(session, run_id)
    coverage_gaps = _detect_token_coverage_gaps(session, run_id)
    # 这里的 estimated 表示“整套 token 统计只能作为近似成本信号”，
    # 并不强制每一条记录都来自本地估算；像 embedding 这类 provider 能稳定返回 usage 的链路，
    # 仍然优先复用实报值，避免为了统一字面口径反而丢掉更好的原始信息
    sources = set(
        session.execute(
            select(ModelTurn.accounting_source).where(
                ModelTurn.run_id == run_id, ModelTurn.row_kind.in_(_USAGE_ROW_KINDS)
            )
        ).scalars()
    )
    summary["accounting_method"] = "unknown" if not sources else "reported" if sources == {"reported"} else "estimated"
    summary["coverage_scope"] = "实际审计请求及已记录的非 Agent 调用；未记录链路不能推断完整"
    summary["coverage_status"] = "partial" if coverage_gaps else "unknown" if not sources else "recorded_calls"
    return {
        "summary": summary,
        "by_task": by_task,
        "by_call_type": by_call_type,
        "by_model": by_model,
        "coverage_gaps": coverage_gaps,
    }


def _fetch_usage_summary(session: Session, run_id: str) -> dict[str, Any]:
    """获取使用量摘要"""
    stmt = select(
        func.count().label("call_count"),
        func.sum(ModelTurn.prompt_tokens).label("total_prompt_tokens"),
        func.sum(func.coalesce(ModelTurn.completion_tokens, 0)).label("total_completion_tokens"),
        func.sum(ModelTurn.total_tokens).label("total_tokens"),
    ).where(
        ModelTurn.run_id == run_id,
        ModelTurn.row_kind.in_(_USAGE_ROW_KINDS),
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


def _fetch_usage_by_task(session: Session, run_id: str) -> dict[str, Any]:
    """按任务类型获取使用量"""
    stmt = (
        select(
            ModelTurn.task_type,
            func.count().label("call_count"),
            func.sum(ModelTurn.total_tokens).label("total_tokens"),
        )
        .where(
            ModelTurn.run_id == run_id,
            ModelTurn.row_kind.in_(_USAGE_ROW_KINDS),
        )
        .group_by(ModelTurn.task_type)
    )

    result = session.execute(stmt).fetchall()
    aggregated: dict[str, dict[str, int]] = {}
    for row in result:
        bucket = aggregated.setdefault(row.task_type, {"call_count": 0, "total_tokens": 0})
        # 不要再用 `row.count` 这类名字，mypy 会把它当成序列方法而不是 SQL 列
        bucket["call_count"] += int(row.call_count or 0)
        bucket["total_tokens"] += int(row.total_tokens or 0)
    return aggregated


def _build_call_type_key(task_type: str, call_type: str) -> str:
    """构建对外统一的调用桶 key"""
    return f"{task_type}.{call_type}"


def _fetch_usage_by_call_type(session: Session, run_id: str) -> dict[str, Any]:
    """按 task_type + call_type 获取使用量"""
    stmt = (
        select(
            ModelTurn.task_type,
            ModelTurn.call_type,
            func.count().label("call_count"),
            func.sum(ModelTurn.total_tokens).label("total_tokens"),
        )
        .where(
            ModelTurn.run_id == run_id,
            ModelTurn.row_kind.in_(_USAGE_ROW_KINDS),
        )
        .group_by(ModelTurn.task_type, ModelTurn.call_type)
    )

    result = session.execute(stmt).fetchall()
    aggregated: dict[str, dict[str, int]] = {}
    for row in result:
        key = _build_call_type_key(row.task_type, row.call_type)
        bucket = aggregated.setdefault(key, {"call_count": 0, "total_tokens": 0})
        bucket["call_count"] += int(row.call_count or 0)
        bucket["total_tokens"] += int(row.total_tokens or 0)
    return aggregated


def _fetch_usage_by_model(session: Session, run_id: str) -> dict[str, Any]:
    """按模型获取使用量"""
    stmt = (
        select(
            ModelTurn.model,
            func.count().label("call_count"),
            func.sum(ModelTurn.total_tokens).label("total_tokens"),
        )
        .where(
            ModelTurn.run_id == run_id,
            ModelTurn.row_kind.in_(_USAGE_ROW_KINDS),
        )
        .group_by(ModelTurn.model)
    )

    result = session.execute(stmt).fetchall()
    return {
        row.model: {
            "call_count": int(row.call_count or 0),
            "total_tokens": int(row.total_tokens or 0),
        }
        for row in result
    }


def _detect_token_coverage_gaps(
    session: Session,
    run_id: str,
) -> list[str]:
    """找出计账口径不完整的调用桶

    Agent 回合与计账列同行内联，缺口只剩三类：尚未收口的 running 行、
    没有 token 记账的行、以及只能本地估算的行。
    """
    gaps: set[str] = set()
    statement = select(ModelTurn.task_type, ModelTurn.call_type).where(
        ModelTurn.run_id == run_id,
        ModelTurn.row_kind == "agent_turn",
        (ModelTurn.status == "running")
        | (ModelTurn.prompt_tokens.is_(None))
        | (ModelTurn.accounting_source != "reported"),
    )
    for row in session.execute(statement):
        gaps.add(_build_call_type_key(row.task_type, row.call_type))
    return sorted(gaps)


def insert_agent_analysis(session: Session, run_id: str, analysis: AgentAnalysisSchema) -> str:
    """诊断产物以 kind=agent_analysis 追加进分析产物表，读侧取最新一行"""
    row = AnalysisOutput(
        output_id=str(uuid4()),
        run_id=run_id,
        kind="agent_analysis",
        payload=analysis.model_dump(),
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
