"""章节工作的进程内回执与跨事务事件登记

2026-10-05 删除数据库租约队列（work_items/claim/lease/epoch）：章节状态
（有无正式标注）就是工作状态，重启恢复等于重查未提交章节，单进程执行器
不再需要租约接管与取消纪元栅栏。本模块只剩工作回执和 outbox 登记，
work 身份不再向审计与事件流注入任何字段。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.agents.annotation.identity import stable_digest
from src.storage.models import AnalysisRun, EventOutbox

WorkKind = Literal["formal_current", "continuity"]


class ImmutableWorkConflict(RuntimeError):
    """同一逻辑工作在相同 cutoff 内出现另一份输入"""


@dataclass(frozen=True, slots=True)
class WorkReceipt:
    """一次章节执行的输入身份；work_id 由 run+章节+载荷+快照确定性铸出"""

    work_id: str
    run_id: str
    work_kind: WorkKind
    payload: dict[str, Any]
    cutoff_hash: str
    attempt_epoch: int


def append_outbox(
    session: Session,
    *,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
    chapter_id: int | None = None,
    cutoff_hash: str | None = None,
) -> str:
    """与业务状态共用事务，重复写入相同事件时不产生第二条流记录"""
    session.get(AnalysisRun, run_id, with_for_update={"read": True})
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"outbox:{run_id}"})
    event_id = stable_digest(run_id, chapter_id, cutoff_hash, event_type, payload)
    statement = insert(EventOutbox).values(
        event_id=event_id,
        run_id=run_id,
        chapter_id=chapter_id,
        cutoff_hash=cutoff_hash,
        event_type=event_type,
        payload=payload,
    )
    session.execute(statement.on_conflict_do_nothing(index_elements=[EventOutbox.event_id]))
    return event_id
