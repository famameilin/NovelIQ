"""全书统计与模型计账落库

- 全书统计：正式聚合的 16 个具名结果落在 runs 的明确列（不加统计行表、
  不加分子/分母列）；插入即按运行覆盖同名统计列，读取按列是否可用投影。
- 非 Agent 模型调用：每条真实请求进 agent_loop，非 Agent 上下文进
  standalone_* 列，用量分项、供应商实报总量、费用与幂等键与请求同一行，
  不伪造 Agent 工作身份、不另建用量/实报/费用子表。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from src.storage.models import AgentLoop, GlobalStats, Novel

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

#: 全书统计目录（global_stats 的 16 个具名列；目录穷举，不接纳任意统计名）
GLOBAL_STAT_COLUMNS: tuple[str, ...] = (
    "avg_mtld",
    "avg_ttr",
    "avg_sent_len",
    "emotion_avg",
    "lexicon_zero_hit_share",
    "emotion_std",
    "emotion_max",
    "emotion_min",
    "emotion_peak_chapter_id",
    "emotion_min_chapter_id",
    "rhythm_avg",
    "rhythm_std",
    "rhythm_max",
    "rhythm_min",
    "rhythm_peak_chapter_id",
    "rhythm_min_chapter_id",
)

#: 章号类统计项（正式值为整型章号，计算侧按浮点产出，写入时收敛为整数）
GLOBAL_STAT_CHAPTER_ID_COLUMNS: frozenset[str] = frozenset(
    {
        "emotion_peak_chapter_id",
        "emotion_min_chapter_id",
        "rhythm_peak_chapter_id",
        "rhythm_min_chapter_id",
    }
)


def insert_global_stats(session: Session, run_id: str, stats: Iterable[tuple[str, float | None]]) -> None:
    "把正式聚合的全书统计写入 runs 的具名列"
    assignments: dict[str, float | int | datetime | None] = {}
    for stat_name, stat_value in stats:
        if stat_name not in GLOBAL_STAT_COLUMNS:
            raise ValueError(f"未知的全书统计名: {stat_name}（目录为 global_stats 的 16 个具名列）")
        if stat_value is None:
            assignments[stat_name] = None
        elif stat_name in GLOBAL_STAT_CHAPTER_ID_COLUMNS:
            assignments[stat_name] = int(stat_value)
        else:
            assignments[stat_name] = float(stat_value)
    if not assignments:
        return
    from sqlalchemy.dialects.postgresql import insert

    statement = insert(GlobalStats).values(run_id=run_id, **assignments)
    session.execute(statement.on_conflict_do_update(index_elements=[GlobalStats.run_id], set_=assignments))
    session.flush()


def fetch_global_stats_dict(session: Session, run_id: str) -> dict[str, float | None]:
    "按运行读出可用的全书统计项（无值列不输出，与旧统计行缺失读法一致）"
    statement = select(*[getattr(GlobalStats, name) for name in GLOBAL_STAT_COLUMNS]).where(
        GlobalStats.run_id == run_id
    )
    row = session.execute(statement).first()
    if row is None:
        return {}
    return {name: value for name, value in row._mapping.items() if value is not None}


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
) -> str:
    "写入一次非 Agent 模型调用的真实请求、用量与费用（Agent 回合由审计记录器写入）"
    now = datetime.now(UTC).replace(tzinfo=None)
    call = AgentLoop(
        model=model,
        error=None,
        started_at=now,
        finished_at=now,
        message_key=message_key,
        standalone_run_id=run_id,
        standalone_chapter_id=chapter_id,
        standalone_task_type=task_type,
        standalone_call_type=call_type,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        # 非 Agent 调用沿用旧的 0 兜底口径，保持既有合计读法不变
        cache_read_tokens=cache_read_tokens if cache_read_tokens is not None else 0,
        reasoning_tokens=reasoning_tokens,
        accounting_source=accounting_source,
        reported_total_tokens=(
            int(total_tokens) if accounting_source == "reported" and total_tokens is not None else None
        ),
        cost=float(cost) if cost is not None else None,
    )
    session.add(call)
    session.flush()
    return str(call.id)


def insert_agent_analysis(session: Session, run_id: str, payload: Mapping[str, Any]) -> str:
    "保留入口名称只为不让无关模块在导入期失败；本函数不再对任何退场表做读写"
    del session, run_id, payload
    raise NotImplementedError("analysis_outputs 已退场：诊断报告改由 diagnosis_reports 正式关系写入")


def fetch_agent_analysis(session: Session, run_id: str) -> dict[str, Any] | None:
    del session, run_id
    raise NotImplementedError("analysis_outputs 已退场：诊断报告改由 diagnosis_reports 正式读接口读取")


def fetch_novel_title(session: Session, novel_id: str) -> str | None:
    "获取小说标题"
    return session.execute(select(Novel.title).where(Novel.novel_id == novel_id)).scalar_one_or_none()
