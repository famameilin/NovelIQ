"""事件森林/DAG API 响应模型（ 树内图外）

2026-08-19：事件层改为「树视图 + 树间边」——event_trees 为事件树列表（树根/
主链/次因分支），causal_edges 只含因果关联边（contains 派生化不再返回）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EventNodeResponse(BaseModel):
    """2026-08-19 用于返回事件节点（含树结构字段）"""

    event_id: str
    chapter_id: int = Field(gt=0)
    chapter_order: int = Field(gt=0)
    description: str
    participants: list[dict[str, Any]] = Field(default_factory=list)
    anchor_paragraph_ids: list[int] = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    text_hash: str
    evidence: list[dict[str, Any]] = Field(min_length=1)
    causal_event_refs: list[str] = Field(default_factory=list)
    tree_id: str = Field(min_length=1)
    cause_role: Literal["root", "main", "secondary"]


class EventEdgeResponse(BaseModel):
    """2026-08-19 用于返回因果关联边（contains 已派生化，不再返回）"""

    edge_id: str
    edge_type: Literal["causal"]
    source_event_id: str
    target_event_id: str
    source_chapter_id: int = Field(gt=0)
    target_chapter_id: int = Field(gt=0)
    is_active: bool
    evidence: list[dict[str, Any]] = Field(min_length=1)


class ForeshadowingEdgeResponse(BaseModel):
    """2026-08-18 用于返回伏笔边（线程即边）"""

    setup_id: str
    setup_event_id: str
    payoff_event_id: str | None = None
    first_chapter_id: int = Field(gt=0)
    last_chapter_id: int = Field(gt=0)
    setup_summary: str
    status: str
    active: bool


class EventSecondaryGroupResponse(BaseModel):
    """2026-08-19 用于返回事件树的次因分支（挂在某个目标事件下）"""

    target_event_id: str
    branch: list[str]


class EventTreeResponse(BaseModel):
    """2026-08-19 用于返回一棵事件树（一棵树 = 一个完整事件）"""

    tree_id: str
    root_event_id: str
    main_chain: list[str]
    secondary_groups: list[EventSecondaryGroupResponse] = Field(default_factory=list)
    chapter_ids: list[int]
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)


class EventForestResponse(BaseModel):
    """2026-08-19 用于返回完整事件森林快照（事件树列表 + 树间因果边 + 伏笔边）"""

    chapter_id: int = Field(gt=0)
    chapter_order: int = Field(gt=0)
    visible_through_chapter_order: int = Field(gt=0)
    derived_event_order: list[str]
    event_nodes: list[EventNodeResponse]
    event_trees: list[EventTreeResponse]
    causal_edges: list[EventEdgeResponse]
    foreshadowing_edges: list[ForeshadowingEdgeResponse]
