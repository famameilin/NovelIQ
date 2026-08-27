"""
事件森林时间轴 API 响应模型（一树一节点）

2026-08-20：新合同，替换旧 TimelineResponse。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class EventTimelineMeta(BaseModel):
    """时间轴元信息"""

    novel_id: str = Field(description="小说 ID")
    novel_name: str = Field(description="小说名称")
    total_chapters: int = Field(ge=0, description="总章节数量")


class EventTimelinePhase(BaseModel):
    """时间轴阶段"""

    name: Literal["引入期", "发展期", "高潮期", "收束期"] = Field(description="阶段名称")
    start: int = Field(description="起始 chapter_id")
    end: int = Field(description="结束 chapter_id")
    ratio: float = Field(ge=0, le=1, description="篇幅占比")


class EventSecondaryGroup(BaseModel):
    """次因分支"""

    target_event_id: str
    branch: list[str]


class EventTimelineNode(BaseModel):
    """2026-08-20 用于返回事件时间轴节点（一树一节点）"""

    tree_id: str = Field(min_length=1)
    root_event_id: str
    title: str
    summary: str
    anchor_chapter_id: int = Field(gt=0)
    anchor_chapter_order: int = Field(gt=0)
    start_chapter_id: int = Field(gt=0)
    end_chapter_id: int = Field(gt=0)
    start_progress: float = Field(ge=0, le=1)
    end_progress: float = Field(ge=0, le=1)
    progress: float = Field(ge=0, le=1)
    chapter_ids: list[int]
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    participants: list[dict[str, Any]] = Field(
        default_factory=list,
        description="参与者透传 list[dict{name, entity_type, role, entity_id?}]",
    )
    character_names: list[str] = Field(default_factory=list, description="角色名派生")
    importance_score: float = Field(ge=0)
    level: Literal[1, 2, 3]
    phase_name: Literal["引入期", "发展期", "高潮期", "收束期"]
    main_chain: list[str]
    secondary_groups: list[EventSecondaryGroup] = Field(default_factory=list)
    causal_in: int = Field(ge=0)
    causal_out: int = Field(ge=0)
    node_type: Literal["event"] = "event"


class EventTimelineCausalEdge(BaseModel):
    """2026-08-20 用于返回全量因果边（含 inactive）"""

    edge_id: str
    edge_type: Literal["causal"]
    source_event_id: str
    target_event_id: str
    source_chapter_id: int = Field(gt=0)
    target_chapter_id: int = Field(gt=0)
    is_active: bool
    evidence: list[dict[str, Any]] = Field(min_length=1)
    expired_at: datetime | None = None


class EventTimelineForeshadowingEdge(BaseModel):
    """2026-08-20 用于返回伏笔边"""

    setup_id: str
    setup_event_id: str
    payoff_event_id: str | None = None
    first_chapter_id: int = Field(gt=0)
    last_chapter_id: int = Field(gt=0)
    setup_summary: str
    status: str
    active: bool


class EventTimelineResponse(BaseModel):
    """2026-08-20 用于返回事件森林时间轴（一树一节点）"""

    meta: EventTimelineMeta = Field(description="时间轴元信息")
    phases: list[EventTimelinePhase] = Field(description="四阶段划分")
    nodes: list[EventTimelineNode] = Field(description="事件节点列表（一树一节点）")
    causal_edges: list[EventTimelineCausalEdge] = Field(default_factory=list, description="全量因果边")
    foreshadowing_edges: list[EventTimelineForeshadowingEdge] = Field(default_factory=list, description="伏笔边")
    derived_event_order: list[str] = Field(default_factory=list, description="派生事件顺序")
    tension_curve: list[float] | None = Field(default=None, description="张力曲线数据")
    phase_basis: Literal["tension", "fixed_percentage"] = Field(default="tension", description="四阶段划分依据")
    total_chapters: int = Field(ge=0, description="总章节数量（冗余便于前端）")
