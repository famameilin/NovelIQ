"""角色 work 的稳定身份与必需角色，章节完成只读聚合"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from src.utils.identity import stable_digest

Role = Literal["solo", "structure", "event", "evidence"]
LANES: tuple[Role, ...] = ("structure", "event", "evidence")


def required_roles(chapter_text: str, threshold: int) -> tuple[Role, ...]:
    return ("solo",) if len(chapter_text) <= threshold else LANES


def annotation_work_id(run_id: str, chapter_id: int, role: Role) -> str:
    return stable_digest("annotation_agent", run_id, chapter_id, role)


def completed_chapters(records: Iterable[Any]) -> set[int]:
    """按已保存的实际角色确定完成，缺失角色不能缩小必需集合"""
    groups: dict[int, set[str]] = {}
    for record in records:
        if record.state == "saved":
            groups.setdefault(record.chapter_id, set()).add(record.role)
    return {chapter_id for chapter_id, roles in groups.items() if roles == {"solo"} or roles == set(LANES)}



@dataclass(frozen=True)
class WorkReceipt:
    """稳定工作身份与实际输入；选举运行信息仅在派发时附入 payload"""

    work_id: str
    run_id: str
    work_kind: str
    payload: dict[str, Any]
