"""伏笔动作直接引用事件并按原文位置排列"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from src.event_trees import storage_map as smap
from src.storage import Storage


@dataclass(frozen=True)
class ForeshadowingActionRow:
    """伏笔动作只读行：事件端点、来源章序与有序原文证据"""

    action_id: str
    action_type: str
    source_event_id: str
    target_event_id: str | None
    producer_agent_id: str
    source_operation_id: str
    operation_order: int
    chapter_id: int | None
    chapter_order: int | None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    evidence_scope: str = "paragraph"

    @property
    def root_event_id(self) -> str:
        return self.source_event_id


class ForeshadowingActionLike(Protocol):
    """动作排序消费的读取形状：动作事实行与事件树伏笔动作视图共用

    成员只读：两侧形状都是冻结 dataclass 行，按只读属性满足本协议。
    """

    @property
    def action_id(self) -> str: ...

    @property
    def chapter_order(self) -> int | None: ...

    @property
    def operation_order(self) -> int: ...

    @property
    def evidence(self) -> list[dict[str, Any]]: ...

    @property
    def evidence_scope(self) -> str: ...


def load_foreshadowing_actions(session: Storage, run_id: str) -> list[ForeshadowingActionRow]:
    """读取本运行伏笔动作及其直接事件端点"""
    annotation_events = smap.run_annotation_event_ids(session, run_id)
    if not annotation_events:
        return []
    action_rows = list(session.reads.event_trees_action_order_load_foreshadowing_actions_1(annotation_events))
    if not action_rows:
        return []
    evidence = smap.fetch_evidence(session, "foreshadow_action_id", [row.action_id for row in action_rows])
    result: list[ForeshadowingActionRow] = []
    for row in action_rows:
        source_context = smap.annotation_chapter_of_execution(session, row.producer_agent_id)
        chapter_id, chapter_order = source_context.chapter_id, source_context.chapter_order
        result.append(
            ForeshadowingActionRow(
                action_id=row.action_id,
                action_type=row.action_type,
                source_event_id=row.source_event_id,
                target_event_id=row.target_event_id,
                producer_agent_id=row.producer_agent_id,
                source_operation_id=row.source_operation_local_key,
                operation_order=int(row.operation_order),
                chapter_id=chapter_id,
                chapter_order=chapter_order,
                evidence=smap.evidence_payloads(session, run_id, evidence.get(row.action_id, [])),
            )
        )
    return sorted(result, key=action_order)


def action_order(action: ForeshadowingActionLike) -> tuple[int, int, int, int, str]:
    positions = [
        (item["paragraph_id"], item.get("char_start", 0))
        for item in action.evidence
        if action.evidence_scope == "paragraph" and "paragraph_id" in item
    ]
    paragraph, start = min(positions, default=(2**31, 0))
    chapter_order = 0 if action.chapter_order is None else action.chapter_order
    return chapter_order, paragraph, start, action.operation_order, action.action_id
