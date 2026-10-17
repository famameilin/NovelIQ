"""work 行的角色值域与章节完成判定

说明: 角色集合是 work_items.role 列的取值域（与建表 CHECK 约束同源）。
2026-10-16 全库 3NF：不再有 annotation_work.state 列——完成判定消费的
state 是由「该 work 的真实执行是否存在 chapter_annotations 正式产物行」
推导出的内存观察（观察值 saved/pending），只读已登记事实，不写任何东西。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, Protocol

Role = Literal["solo", "structure", "event", "evidence"]
LANES: tuple[Role, ...] = ("structure", "event", "evidence")


class WorkStateRecord(Protocol):
    """完成判定仅消费 work 身份与推导出的保存观察（state 不是数据库列）

    三个成员都是只读投影：冻结行（annotation 读投影行）以只读属性满足本协议。
    """

    @property
    def chapter_id(self) -> int: ...

    @property
    def state(self) -> str: ...

    @property
    def role(self) -> str: ...


def completed_chapters(records: Iterable[WorkStateRecord]) -> set[int]:
    """按已保存的实际角色确定完成，缺失角色不能缩小必需集合

    state 由调用方按「正式产物存在性」推导；重复的同一 work 不改变集合语义。
    """
    groups: dict[int, set[str]] = {}
    for record in records:
        if record.state == "saved":
            groups.setdefault(record.chapter_id, set()).add(record.role)
    return {chapter_id for chapter_id, roles in groups.items() if roles == {"solo"} or roles == set(LANES)}
