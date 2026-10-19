"""事件森林只读 DTO；不包含仓储或执行行为"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class EventNodeRow:
    """返回章节事件节点"""

    declaration_id: str
    event_id: str | None
    chapter_id: int
    chapter_order: int
    description: str
    participants: list[dict[str, Any]]
    anchor_paragraph_ids: list[int]
    char_start: int
    char_end: int
    evidence: list[dict[str, Any]]
    causal_event_refs: list[str]
    tree_id: str
    cause_role: str
    parent_event_id: str | None
    evidence_scope: str
    payload_path: str
    event_ordinal: int


@dataclass(frozen=True)
class EventEdgeRow:
    """返回章节事件因果边"""

    edge_id: str
    edge_type: str
    source_event_id: str
    target_event_id: str
    source_chapter_id: int
    target_chapter_id: int
    is_active: bool
    evidence: list[dict[str, Any]]
    expired_at: datetime | None = None


@dataclass(frozen=True)
class ForeshadowingEdgeRow:
    """返回章节伏笔树视图（伏笔即事件树，一行一棵树）"""

    root_event_id: str
    run_id: str
    tree_id: str
    payoff_event_id: str | None
    first_chapter_id: int
    last_chapter_id: int
    description: str
    status: str
    active: bool


@dataclass(frozen=True)
class EventSecondaryGroupRow:
    """返回事件树的次因分支"""

    target_event_id: str
    branch: list[str]


@dataclass(frozen=True)
class EventTreeRow:
    """返回一棵事件树"""

    tree_id: str
    root_event_id: str
    main_chain: list[str]
    secondary_groups: list[EventSecondaryGroupRow]
    chapter_ids: list[int]
    char_start: int
    char_end: int


@dataclass(frozen=True)
class EventForestSnapshot:
    """返回章节边界内的事件森林"""

    chapter_id: int
    chapter_order: int
    visible_through_chapter_order: int
    derived_event_order: list[str]
    event_nodes: list[EventNodeRow]
    event_trees: list[EventTreeRow]
    causal_edges: list[EventEdgeRow]
    foreshadowing_edges: list[ForeshadowingEdgeRow]
