"""全书统计与模型计账落库

- 全书统计：正式聚合的 16 个具名结果落在 analysis_runs 的明确列（不加统计行表、
  不加分子/分母列）；插入即按运行覆盖同名统计列，读取按列是否可用投影。
- 非 Agent 模型调用：每条真实请求进 model_calls，非 Agent 上下文进
  standalone_* 列，用量分项、供应商实报总量、费用与幂等键与请求同一行，
  不伪造 Agent 工作身份、不另建用量/实报/费用子表。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from src.storage.models import AnalysisRun, ModelCall, Novel

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

#: 全书统计目录（analysis_runs 的 16 个具名列；目录穷举，不接纳任意统计名）
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
    """把正式聚合的全书统计写入 analysis_runs 的具名列。

    提交项按名称覆盖本运行同名列（未提交的列保持原值）；未知统计名直接报错，
    不做兜底丢弃。写入同时登记聚合阶段真实完成事实 aggregate_completed_at
    （is_aggregate_complete 的唯一依据）。
    """
    assignments: dict[str, float | int | datetime | None] = {}
    for stat_name, stat_value in stats:
        if stat_name not in GLOBAL_STAT_COLUMNS:
            raise ValueError(f"未知的全书统计名: {stat_name}（目录为 analysis_runs 的 16 个具名列）")
        if stat_value is None:
            assignments[stat_name] = None
        elif stat_name in GLOBAL_STAT_CHAPTER_ID_COLUMNS:
            assignments[stat_name] = int(stat_value)
        else:
            assignments[stat_name] = float(stat_value)
    if not assignments:
        return
    # 完成事实与统计同一 UPDATE 落库：一次提交成功后聚合阶段即判完成，幂等重跑覆盖同列
    assignments["aggregate_completed_at"] = datetime.now(UTC).replace(tzinfo=None)

    result = session.execute(
        update(AnalysisRun).where(AnalysisRun.run_id == run_id).values(**assignments)
    )
    # 运行期返回游标结果（DML 影响的真实行数只在运行期可知），静态返回类型不含 rowcount
    if cast(CursorResult[Any], result).rowcount == 0:
        raise ValueError(f"运行不存在，无法写入全书统计: {run_id}")
    session.commit()


def fetch_global_stats_dict(session: Session, run_id: str) -> dict[str, float | None]:
    """按运行读出可用的全书统计项（无值列不输出）。

    阶段完成事实由 analysis_runs.aggregate_completed_at 表达，不用某列非空代替。
    """
    statement = select(*[getattr(AnalysisRun, name) for name in GLOBAL_STAT_COLUMNS]).where(
        AnalysisRun.run_id == run_id
    )
    row = session.execute(statement).first()
    if row is None:
        return {}
    return {
        name: value
        for name, value in zip(GLOBAL_STAT_COLUMNS, row, strict=True)
        if value is not None
    }


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
    """写入一次非 Agent 模型调用的真实请求、用量与费用（Agent 回合由审计记录器写入）

    调用身份进 model_calls；非 Agent 上下文进 standalone_* 列（不伪造 Agent 工作身份）；
    用量分项、供应商实报总量（仅 accounting_source=reported）、费用与幂等键同列保存，
    程序估算的总量由读取侧按分项投影，不写成实报。
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    call = ModelCall(
        model=model,
        status="success",
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
        # 非 Agent 调用以 0 兜底，保持既有合计读法不变
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
    return int(call.call_id)


def insert_agent_analysis(session: Session, run_id: str, payload: Mapping[str, Any]) -> str:
    """诊断报告由诊断纵切面按 diagnosis_reports 正式关系写入

    保留入口名称只为不让无关模块在导入期失败；本函数不做任何读写。
    """
    del session, run_id, payload
    raise NotImplementedError("analysis_outputs 已退场：诊断报告改由 diagnosis_reports 正式关系写入")


def fetch_agent_analysis(session: Session, run_id: str) -> dict[str, Any] | None:
    """诊断报告读取由诊断纵切面的正式读接口承担"""
    del session, run_id
    raise NotImplementedError("analysis_outputs 已退场：诊断报告改由 diagnosis_reports 正式读接口读取")


def fetch_novel_title(session: Session, novel_id: str) -> str | None:
    """获取小说标题。"""
    return session.execute(select(Novel.title).where(Novel.novel_id == novel_id)).scalar_one_or_none()
