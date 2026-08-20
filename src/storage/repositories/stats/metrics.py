"""全局统计、token 使用与 diagnosis 落库相关操作"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.models.cloud.schema import CloudAnalysis as CloudAnalysisSchema
from src.storage.models import CloudAnalysis, GlobalContext, GlobalStats, TokenUsage
from src.storage.models.agent_audit import AgentInvocation, AgentTurn

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def insert_global_stats(session: Session, run_id: str, stats: Iterable[tuple[str, float | None]]) -> None:
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


def fetch_global_stats(session: Session, run_id: str) -> list[tuple[str, float | None]]:
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


def fetch_global_stats_dict(session: Session, run_id: str) -> dict[str, float | None]:
    """
    获取全局统计数据字典

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        统计名称到值的映射字典
    """
    stmt = select(GlobalStats.stat_name, GlobalStats.stat_value).where(GlobalStats.run_id == run_id)
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
    chapter_id: int | None = None,
    cache_read_tokens: int | None = None,
    cost: float | None = None,
    accounting_source: str = "reported",
    reasoning_tokens: int | None = None,
    agent_turn_id: int | None = None,
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
        chapter_id: 分块ID（可选）
        cache_read_tokens: 缓存命中 token 数，缺失记 0（无缓存证据 = 全量计费）
        cost: 网关返回的费用，不估算
        accounting_source: 记账来源（reported=实报 / estimated=tiktoken 估算）
        reasoning_tokens: 推理 token 数（可选）
        agent_turn_id: 关联 agent_turns.id（Agent 回合行一对一，可选）

    Returns:
        插入记录的ID
    """
    from datetime import datetime

    now = datetime.now().isoformat()
    token_usage = TokenUsage(
        novel_id=novel_id,
        chapter_id=chapter_id,
        task_type=task_type,
        call_type=call_type,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cache_read_tokens=cache_read_tokens if cache_read_tokens is not None else 0,
        reasoning_tokens=reasoning_tokens,
        cost=cost,
        accounting_source=accounting_source,
        created_at=now,
        run_id=run_id,
        agent_turn_id=agent_turn_id,
    )
    session.add(token_usage)
    session.flush()
    return token_usage.id


def fetch_token_usage_stats(session: Session, run_id: str, novel_id: str) -> dict[str, Any]:
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
    by_call_type = _fetch_usage_by_call_type(session, run_id, novel_id)
    by_model = _fetch_usage_by_model(session, run_id, novel_id)
    coverage_gaps = _detect_token_coverage_gaps(session, run_id, by_call_type)
    # 这里的 estimated 表示“整套 token 统计只能作为近似成本信号”，
    # 并不强制每一条记录都来自本地估算；像 embedding 这类 provider 能稳定返回 usage 的链路，
    # 仍然优先复用实报值，避免为了统一字面口径反而丢掉更好的原始信息
    summary["accounting_method"] = "estimated"
    summary["coverage_status"] = "partial" if coverage_gaps else "complete"
    return {
        "summary": summary,
        "by_task": by_task,
        "by_call_type": by_call_type,
        "by_model": by_model,
        "coverage_gaps": coverage_gaps,
    }


def _fetch_usage_summary(session: Session, run_id: str, novel_id: str) -> dict[str, Any]:
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


def _fetch_usage_by_task(session: Session, run_id: str, novel_id: str) -> dict[str, Any]:
    """按任务类型获取使用量"""
    stmt = (
        select(
            TokenUsage.task_type,
            func.count().label("call_count"),
            func.sum(TokenUsage.total_tokens).label("total_tokens"),
        )
        .where(
            TokenUsage.novel_id == novel_id,
            TokenUsage.run_id == run_id,
        )
        .group_by(TokenUsage.task_type)
    )

    result = session.execute(stmt).fetchall()
    aggregated: dict[str, dict[str, int]] = {}
    for row in result:
        normalized_task_type = _normalize_token_usage_task_type(row.task_type)
        bucket = aggregated.setdefault(normalized_task_type, {"call_count": 0, "total_tokens": 0})
        # 不要再用 `row.count` 这类名字，mypy 会把它当成序列方法而不是 SQL 列
        bucket["call_count"] += int(row.call_count or 0)
        bucket["total_tokens"] += int(row.total_tokens or 0)
    return aggregated


def _build_call_type_key(task_type: str, call_type: str) -> str:
    """构建对外统一的调用桶 key"""
    return f"{task_type}.{call_type}"


def _normalize_token_usage_task_type(task_type: str) -> str:
    """2026-08-05 用于返回最新主链唯一的 Token 任务类型"""
    return task_type


def _agent_call_type(task_type: str) -> str:
    """2026-08-10 用于把 Agent 审计任务类型映射到 token_usage 的调用桶 call_type"""
    if task_type == "annotation":
        return "agent"
    if task_type == "diagnosis":
        return "diagnosis"
    return task_type


def _fetch_usage_by_call_type(session: Session, run_id: str, novel_id: str) -> dict[str, Any]:
    """按 task_type + call_type 获取使用量"""
    stmt = (
        select(
            TokenUsage.task_type,
            TokenUsage.call_type,
            func.count().label("call_count"),
            func.sum(TokenUsage.total_tokens).label("total_tokens"),
        )
        .where(
            TokenUsage.novel_id == novel_id,
            TokenUsage.run_id == run_id,
        )
        .group_by(TokenUsage.task_type, TokenUsage.call_type)
    )

    result = session.execute(stmt).fetchall()
    aggregated: dict[str, dict[str, int]] = {}
    for row in result:
        normalized_task_type = _normalize_token_usage_task_type(row.task_type)
        key = _build_call_type_key(normalized_task_type, row.call_type)
        bucket = aggregated.setdefault(key, {"call_count": 0, "total_tokens": 0})
        bucket["call_count"] += int(row.call_count or 0)
        bucket["total_tokens"] += int(row.total_tokens or 0)
    return aggregated


def _fetch_usage_by_model(session: Session, run_id: str, novel_id: str) -> dict[str, Any]:
    """按模型获取使用量"""
    stmt = (
        select(
            TokenUsage.model,
            func.count().label("call_count"),
            func.sum(TokenUsage.total_tokens).label("total_tokens"),
        )
        .where(
            TokenUsage.novel_id == novel_id,
            TokenUsage.run_id == run_id,
        )
        .group_by(TokenUsage.model)
    )

    result = session.execute(stmt).fetchall()
    return {
        row.model: {
            "call_count": int(row.call_count or 0),
            "total_tokens": int(row.total_tokens or 0),
        }
        for row in result
    }


def _fetch_agent_turn_call_counts(session: Session, run_id: str) -> dict[str, int]:
    """2026-08-10 用于统计新审计表中真实成功的 Agent 模型回合数"""
    stmt = (
        select(AgentInvocation.task_type, func.count().label("turn_count"))
        .join(AgentTurn, AgentTurn.invocation_id == AgentInvocation.id)
        .where(AgentInvocation.run_id == run_id, AgentTurn.status == "success")
        .group_by(AgentInvocation.task_type)
    )
    aggregated: dict[str, int] = {}
    for row in session.execute(stmt).fetchall():
        key = _build_call_type_key(row.task_type, _agent_call_type(row.task_type))
        aggregated[key] = aggregated.get(key, 0) + int(row.turn_count or 0)
    return aggregated


def _detect_token_coverage_gaps(
    session: Session,
    run_id: str,
    by_call_type: dict[str, Any],
) -> list[str]:
    """比较真实 Agent 回合与已记账调用，找出 token 覆盖缺口"""
    agent_turn_counts = _fetch_agent_turn_call_counts(session, run_id)
    gaps: list[str] = []
    for call_key in sorted(agent_turn_counts.keys()):
        agent_call_count = int(agent_turn_counts.get(call_key, 0) or 0)
        token_call_count = int(by_call_type.get(call_key, {}).get("call_count", 0) or 0)
        if token_call_count < agent_call_count:
            gaps.append(call_key)
    return gaps


def insert_cloud_analysis(session: Session, run_id: str, analysis: CloudAnalysisSchema) -> None:
    """
    修改时间: 2026-04-30
    任务: diagnosis-current-contract
    修改原因: `cloud_analysis` 持久化统一使用当前结构

    插入云端分析结果

    `cloud_analysis` 统一落库焦点合同字段，不再写入旧 `protagonist` 列
    """
    arc_scores_json = json.dumps(dict(analysis.arc_scores), ensure_ascii=False)
    genre_labels_json = json.dumps(list(analysis.genre_labels), ensure_ascii=False)
    style_labels_json = json.dumps(list(analysis.style_labels), ensure_ascii=False)
    topic_labels_json = json.dumps(list(analysis.topic_labels), ensure_ascii=False)
    focus_characters_json = json.dumps(list(analysis.focus_characters), ensure_ascii=False)
    main_characters_json = json.dumps(list(analysis.main_characters), ensure_ascii=False)
    core_cast_json = json.dumps(list(analysis.core_cast), ensure_ascii=False)

    cloud_analysis = CloudAnalysis(
        novel_id=analysis.novel_id,
        foreshadow_expectation=analysis.foreshadow_expectation,
        arc_scores=arc_scores_json,
        genre_labels=genre_labels_json,
        style_labels=style_labels_json,
        topic_labels=topic_labels_json,
        diagnosis=analysis.diagnosis,
        value_logic_type=analysis.value_logic_type,
        value_logic_reason=analysis.value_logic_reason,
        power_stance_score=analysis.power_stance_score,
        power_stance_reason=analysis.power_stance_reason,
        common_people_dignity=analysis.common_people_dignity,
        dignity_reason=analysis.dignity_reason,
        cultural_depth_score=analysis.cultural_depth_score,
        cultural_depth_reason=analysis.cultural_depth_reason,
        narrative_arc_type=analysis.narrative_arc_type,
        focus_structure=analysis.focus_structure,
        focus_characters=focus_characters_json,
        main_characters=main_characters_json,
        core_cast=core_cast_json,
        theme_color=analysis.theme_color,
        run_id=run_id,
    )
    session.add(cloud_analysis)
    session.commit()


def fetch_cloud_analysis(session: Session, novel_id: str, run_id: str) -> dict[str, Any] | None:
    """
    修改时间: 2026-04-30
    任务: diagnosis-current-contract
    修改原因: 读取层统一返回当前 `cloud_analysis` 结构
    """
    stmt = (
        select(CloudAnalysis)
        .where(
            CloudAnalysis.novel_id == novel_id,
            CloudAnalysis.run_id == run_id,
        )
        .order_by(CloudAnalysis.id.desc())
        .limit(1)
    )

    result = session.execute(stmt).scalar_one_or_none()

    if result is None:
        stmt = (
            select(CloudAnalysis)
            .where(CloudAnalysis.run_id == run_id)
            .order_by(CloudAnalysis.id.desc())
            .limit(1)
        )
        result = session.execute(stmt).scalar_one_or_none()

    if result is None:
        return None

    return {
        "novel_id": result.novel_id,
        "foreshadow_expectation": result.foreshadow_expectation,
        "arc_scores": result.arc_scores,
        "genre_labels": result.genre_labels,
        "style_labels": result.style_labels,
        "topic_labels": result.topic_labels,
        "diagnosis": result.diagnosis,
        "value_logic_type": result.value_logic_type,
        "value_logic_reason": result.value_logic_reason,
        "power_stance_score": result.power_stance_score,
        "power_stance_reason": result.power_stance_reason,
        "common_people_dignity": result.common_people_dignity,
        "dignity_reason": result.dignity_reason,
        "cultural_depth_score": result.cultural_depth_score,
        "cultural_depth_reason": result.cultural_depth_reason,
        "narrative_arc_type": result.narrative_arc_type,
        "focus_structure": result.focus_structure,
        "focus_characters": result.focus_characters,
        "main_characters": result.main_characters,
        "core_cast": result.core_cast,
        "theme_color": result.theme_color,
        "run_id": result.run_id,
    }


def insert_global_context(
    session: Session,
    run_id: str,
    novel_id: str,
    core_characters: str,
    world_setting: str,
    novel_title: str | None = None,
) -> None:
    """
    插入全局上下文

    Args:
        session: 数据库会话
        run_id: 运行ID
        novel_id: 小说ID
        core_characters: 核心角色
        world_setting: 世界观设定
        novel_title: 小说标题（可选）
    """
    now = datetime.now().isoformat()
    stmt = (
        pg_insert(GlobalContext)
        .values(
            novel_id=novel_id,
            novel_title=novel_title,
            core_characters=core_characters,
            world_setting=world_setting,
            updated_at=now,
            run_id=run_id,
        )
        .on_conflict_do_update(
            index_elements=["novel_id"],
            set_={
                "novel_title": novel_title,
                "core_characters": core_characters,
                "world_setting": world_setting,
                "updated_at": now,
                "run_id": run_id,
            },
        )
    )
    session.execute(stmt)
    session.commit()


def fetch_global_context(session: Session, run_id: str, novel_id: str) -> tuple[str, str, str, str] | None:
    """
    获取全局上下文

    Args:
        session: 数据库会话
        run_id: 运行ID
        novel_id: 小说ID

    Returns:
        (novel_title, core_characters, world_setting, updated_at) 元组，不存在则返回 None
    """
    # 2026-08-14 D15：insert 按 novel_id upsert 并覆写 run_id（全局上下文只保留
    # 最新 run），读侧若再按 run_id 过滤，旧 run 会读不到上下文而视图不一致；
    # 统一只按 novel_id 读取（run_id 参数保留仅为调用方兼容）
    stmt = select(
        GlobalContext.novel_title,
        GlobalContext.core_characters,
        GlobalContext.world_setting,
        GlobalContext.updated_at,
    ).where(
        GlobalContext.novel_id == novel_id,
    )
    result = session.execute(stmt).fetchone()
    if result is None:
        return None
    return (result.novel_title, result.core_characters, result.world_setting, result.updated_at)


def update_global_context(session: Session, run_id: str, novel_id: str, **kwargs: Any) -> None:
    """
    更新全局上下文

    Args:
        session: 数据库会话
        run_id: 运行ID
        novel_id: 小说ID
        **kwargs: 要更新的字段
    """
    allowed_fields = {"core_characters", "world_setting"}
    update_data = {}
    for key, value in kwargs.items():
        if key in allowed_fields:
            update_data[key] = value
    if not update_data:
        return
    update_data["updated_at"] = datetime.now().isoformat()

    stmt = (
        update(GlobalContext)
        # 2026-08-14 D15：与 fetch_global_context 同口径，只按 novel_id 定位最新行
        .where(GlobalContext.novel_id == novel_id)
        .values(**update_data)
    )
    session.execute(stmt)
    session.commit()


def fetch_novel_title(session: Session, novel_id: str, run_id: str) -> str | None:
    """
    获取小说标题

    Args:
        session: 数据库会话
        novel_id: 小说ID
        run_id: 运行ID

    Returns:
        小说标题，不存在则返回 None
    """
    stmt = (
        select(GlobalContext.novel_title)
        # 2026-08-14 D15：只按 novel_id 读取最新行
        .where(
            GlobalContext.novel_id == novel_id,
        )
        .limit(1)
    )

    result = session.execute(stmt).fetchone()
    return result.novel_title if result else None


def has_global_context(session: Session, run_id: str, novel_id: str) -> bool:
    """检查某小说是否已存在 global_context 记录

    2026-08-14 D15：表内每 novel 至多一行（upsert 覆写 run_id），
    旧 run 的 run_id 已被最新 run 覆盖，故按 novel_id 判断（run_id 仅兼容保留）
    """
    stmt = select(GlobalContext).where(GlobalContext.novel_id == novel_id).limit(1)
    result = session.execute(stmt).scalar_one_or_none()
    return result is not None
