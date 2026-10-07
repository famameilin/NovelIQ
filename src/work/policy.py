"""annotation_work 行的角色值域与章节完成判定

说明: 角色集合是 annotation_work.role 列的取值域（与建表 CHECK 约束同源），
完成判定只读已登记的行，不写任何东西。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, Protocol

Role = Literal["solo", "structure", "event", "evidence"]
LANES: tuple[Role, ...] = ("structure", "event", "evidence")


class WorkStateRecord(Protocol):
    """完成判定仅消费实际 work 的身份与保存状态"""

    chapter_id: int
    state: str
    role: str


def completed_chapters(records: Iterable[WorkStateRecord]) -> set[int]:
    """按已保存的实际角色确定完成，缺失角色不能缩小必需集合"""
    groups: dict[int, set[str]] = {}
    for record in records:
        if record.state == "saved":
            groups.setdefault(record.chapter_id, set()).add(record.role)
    return {chapter_id for chapter_id, roles in groups.items() if roles == {"solo"} or roles == set(LANES)}
