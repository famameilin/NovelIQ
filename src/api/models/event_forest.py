"""事件森林/DAG API 响应模型

2026-08-18 P2：事件过程层 API 合同，返回章节根、事件节点、三类边、锚点、
Evidence、可见边界和派生顺序。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EventNodeResponse(BaseModel):
    """2026-08-18 用于返回事件节点"""

    event_id: str
    event_revision: int = Field(gt=0)
    chapter_id: int = Field(gt=0)
    chapter_order: int = Field(gt=0)
    description: str
    participants: list[dict[str, Any]] = Field(default_factory=list)
    anchor_paragraph_ids: list[int] = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    text_hash: str
    evidence: list[dict[str, Any]] = Field(min_length=1)
    causal_event_refs: list[int] = Field(default_factory=list)


class EventEdgeResponse(BaseModel):
    """2026-08-18 用于返回事件边（contains / causal）"""

    edge_id: str
    edge_type: Literal["contains", "causal"]
    source_event_id: str | None = None
    source_event_revision: int | None = Field(default=None, gt=0)
    target_event_id: str
    target_event_revision: int = Field(gt=0)
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


class EventChapterRootResponse(BaseModel):
    """2026-08-18 用于返回章节根及其 contains 事件顺序"""

    chapter_id: int = Field(gt=0)
    chapter_order: int = Field(gt=0)
    event_ids: list[str]


class EventForestResponse(BaseModel):
    """2026-08-18 用于返回完整事件森林快照"""

    graph_version_id: str
    chapter_order: int = Field(gt=0)
    visible_through_chapter_order: int = Field(gt=0)
    chapter_roots: list[EventChapterRootResponse]
    derived_event_order: list[str]
    event_nodes: list[EventNodeResponse]
    event_edges: list[EventEdgeResponse]
    foreshadowing_edges: list[ForeshadowingEdgeResponse]
