"""审计用量及覆盖缺口查询；只统计实际请求事实"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage.models import ModelTurn

_USAGE_ROW_KINDS = ("agent_turn", "usage")


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
