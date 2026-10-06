"""事件森林 / 事件树 / 时间轴 API 响应模型（树内图外）

2026-08-19：事件层改为「树视图 + 树间边」——event_trees 为事件树列表（树根/主链/次因分支），
causal_edges 只含因果关联边（contains 派生化不再返回）。
2026-08-20：时间轴合同（一树一节点）复用同一批节点/边模型，仅补充阶段与进度字段。
"""

from __future__ import annotations

from datetime import datetime
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
    evidence: list[dict[str, Any]] = Field(min_length=1)
    causal_event_refs: list[str] = Field(default_factory=list)
    tree_id: str = Field(min_length=1)
    cause_role: Literal["root", "main", "secondary"]
    parent_event_id: str | None = None
    evidence_scope: Literal["chapter", "paragraph"]


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


class EventTimelineCausalEdge(EventEdgeResponse):
    """2026-08-20 时间轴用的全量因果边（含已失效边，故补 expired_at）"""

    expired_at: datetime | None = None


class ForeshadowingEdgeResponse(BaseModel):
    """2026-09-13 用于返回伏笔边（伏笔即事件树）"""

    root_event_id: str
    tree_id: str
    payoff_event_id: str | None = None
    first_chapter_id: int = Field(gt=0)
    last_chapter_id: int = Field(gt=0)
    description: str
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


class EventSourceParagraphResponse(BaseModel):
    """按章原文中的一个有序段落"""

    paragraph_id: int = Field(ge=0)
    paragraph_index: int = Field(ge=0)
    text: str


class EventSourceChapterResponse(BaseModel):
    """事件树阅读区按需加载的章节原文"""

    chapter_id: int = Field(gt=0)
    title: str
    paragraphs: list[EventSourceParagraphResponse]


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
    secondary_groups: list[EventSecondaryGroupResponse] = Field(default_factory=list)
    causal_in: int = Field(ge=0)
    causal_out: int = Field(ge=0)
    node_type: Literal["event"] = "event"


class EventTimelineResponse(BaseModel):
    """2026-08-20 用于返回事件森林时间轴（一树一节点）"""

    meta: EventTimelineMeta = Field(description="时间轴元信息")
    phases: list[EventTimelinePhase] = Field(description="四阶段划分")
    nodes: list[EventTimelineNode] = Field(description="事件节点列表（一树一节点）")
    causal_edges: list[EventTimelineCausalEdge] = Field(default_factory=list, description="全量因果边")
    foreshadowing_edges: list[ForeshadowingEdgeResponse] = Field(default_factory=list, description="伏笔边")
    derived_event_order: list[str] = Field(default_factory=list, description="派生事件顺序")
    tension_curve: list[float] | None = Field(default=None, description="张力曲线数据")
    phase_basis: Literal["tension", "fixed_percentage"] = Field(default="tension", description="四阶段划分依据")
    total_chapters: int = Field(ge=0, description="总章节数量（冗余便于前端）")
