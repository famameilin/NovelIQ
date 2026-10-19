"""伏笔动作按原文位置排列，正式事件身份沿声明归属取得"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from src.event_trees import storage_map as smap
from src.storage import Storage


@dataclass(frozen=True)
class ForeshadowingActionRow:
    """伏笔动作只读行：动作事实 + 来源章序 + 有序原文证据 + 声明绑定的正式事件身份"""

    action_id: str
    action_type: str
    source_declaration_id: str
    target_declaration_id: str | None
    producer_agent_id: str
    source_operation_id: str
    operation_order: int
    chapter_id: int | None
    chapter_order: int | None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    evidence_scope: str = "paragraph"
    # 以下为读取投影：来源/目标声明绑定的完整事件，未发布保持空
    root_event_id: str | None = None
    target_event_id: str | None = None


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
    """本 run 的伏笔动作行：来源或目标声明属于本 run；绑定未发布时事件身份为空"""
    declarations = smap.run_declaration_ids(session, run_id)
    if not declarations:
        return []
    action_rows = list(session.reads.event_trees_action_order_load_foreshadowing_actions_1(declarations))
    if not action_rows:
        return []
    bindings = {
        row.declaration_id: row.event_id
        for row in session.reads.event_trees_action_order_load_foreshadowing_actions_2(declarations, run_id)
    }
    evidence = smap.fetch_evidence(session, "foreshadow_action_id", [row.action_id for row in action_rows])
    result: list[ForeshadowingActionRow] = []
    for row in action_rows:
        source_context = smap.annotation_chapter_of_execution(session, row.producer_agent_id)
        chapter_id, chapter_order = source_context.chapter_id, source_context.chapter_order
        result.append(
            ForeshadowingActionRow(
                action_id=row.action_id,
                action_type=row.action_type,
                source_declaration_id=row.source_declaration_id,
                target_declaration_id=row.target_declaration_id,
                producer_agent_id=row.producer_agent_id,
                source_operation_id=row.source_operation_local_key,
                operation_order=int(row.operation_order),
                chapter_id=chapter_id,
                chapter_order=chapter_order,
                evidence=smap.evidence_payloads(session, run_id, evidence.get(row.action_id, [])),
                root_event_id=bindings.get(row.source_declaration_id),
                target_event_id=(
                    bindings.get(row.target_declaration_id) if row.target_declaration_id is not None else None
                ),
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
