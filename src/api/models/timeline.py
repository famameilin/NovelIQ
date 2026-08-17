"""
叙事时间轴 API 响应模型
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TimelineMeta(BaseModel):
    """时间轴元信息"""

    novel_id: str = Field(description="小说 ID")
    novel_name: str = Field(description="小说名称")
    total_chapters: int = Field(ge=0, description="总章节数量")


class TimelinePhase(BaseModel):
    """时间轴阶段"""

    name: Literal["引入期", "发展期", "高潮期", "收束期"] = Field(description="阶段名称")
    start: int = Field(description="起始 chapter_id")
    end: int = Field(description="结束 chapter_id")
    ratio: float = Field(ge=0, le=1, description="篇幅占比")


class PlotFlags(BaseModel):
    """剧情节点附加标记"""

    is_pivot: bool = Field(description="是否为转折点")
    is_cliffhanger: bool = Field(description="是否为悬念点")
    tension_percentile: int = Field(ge=0, le=100, description="张力百分位排名")


class GraphTimelineChange(BaseModel):
    """2026-08-07 用于返回时间轴中的实体状态或关系章节变化"""

    change_id: str
    change_kind: Literal["state", "relation"]
    graph_version_id: str
    chapter_id: int = Field(gt=0)
    fact_id: str
    fact_revision: int = Field(gt=0)
    effective_chapter_id: int = Field(ge=0)
    changes: list[dict[str, Any]] = Field(min_length=1)
    entity_id: int | None = None
    entity_name: str | None = None
    relation_id: str | None = None
    relation_version_id: int | None = None
    relation_revision: int | None = None
    from_char: str | None = None
    to_char: str | None = None
    relation_type: str | None = None
    relation_change_kind: str | None = None
    directionality: str | None = None


class LifecycleTimelineEvent(BaseModel):
    """角色生命周期事件"""

    entity_id: int = Field(description="角色实体 ID")
    character_name: str = Field(description="角色名称")
    lifecycle_type: Literal["entry", "exit"] = Field(description="生命周期类型")


class TimelineNode(BaseModel):
    """时间轴节点"""

    node_id: str = Field(description="节点唯一标识")
    anchor_chapter_id: int = Field(description="节点主锚点章节 ID")
    progress: float = Field(ge=0, le=1, description="叙事进度 (0-1)")
    importance_score: float = Field(ge=0, description="重要性分数")
    level: Literal[1, 2, 3] = Field(description="重要性级别: 1=重要, 2=较重要, 3=不重要")
    summary: str = Field(description="节点摘要")
    characters: list[str] = Field(default_factory=list, description="涉及角色")
    phase_name: Literal["引入期", "发展期", "高潮期", "收束期"] = Field(description="所属叙事阶段")
    node_type: Literal["plot", "state", "relation", "lifecycle"] = Field(description="节点大类")
    node_subtype: str = Field(description="节点子类型")
    score_breakdown: dict[str, float] = Field(default_factory=dict, description="分项得分")
    plot_flags: PlotFlags | None = Field(default=None, description="剧情节点附加标记")
    graph_changes: list[GraphTimelineChange] | None = Field(default=None, description="章节图变化")
    lifecycle_events: list[LifecycleTimelineEvent] | None = Field(default=None, description="生命周期事件")


class TimelineCompositeNode(BaseModel):
    """时间轴复合节点"""

    node_id: str = Field(description="复合节点唯一标识")
    anchor_chapter_id: int = Field(description="复合节点主锚点章节 ID")
    start_chapter_id: int = Field(description="复合节点起始章节 ID")
    end_chapter_id: int = Field(description="复合节点结束章节 ID")
    progress: float = Field(ge=0, le=1, description="代表节点叙事进度 (0-1)")
    start_progress: float = Field(ge=0, le=1, description="起始进度 (0-1)")
    end_progress: float = Field(ge=0, le=1, description="结束进度 (0-1)")
    importance_score: float = Field(ge=0, description="重要性分数")
    level: Literal[1, 2, 3] = Field(description="重要性级别: 1=重要, 2=较重要, 3=不重要")
    summary: str = Field(description="复合节点摘要")
    characters: list[str] = Field(default_factory=list, description="涉及角色")
    phase_name: Literal["引入期", "发展期", "高潮期", "收束期"] = Field(description="所属叙事阶段")
    node_type: Literal["plot", "state", "relation", "lifecycle"] = Field(description="节点大类")
    node_subtypes: list[str] = Field(default_factory=list, description="复合节点包含的子类型")
    representative_node_id: str = Field(description="代表原子节点 ID")
    child_node_ids: list[str] = Field(default_factory=list, description="包含的原子节点 ID 列表")


class TimelineResponse(BaseModel):
    """时间轴 API 响应"""

    meta: TimelineMeta = Field(description="时间轴元信息")
    phases: list[TimelinePhase] = Field(description="四阶段划分")
    composite_nodes: list[TimelineCompositeNode] = Field(description="默认概览使用的复合节点列表")
    atomic_nodes: list[TimelineNode] = Field(description="全量原子节点列表")
    tension_curve: list[float] | None = Field(default=None, description="张力曲线数据")
    phase_basis: Literal["tension", "fixed_percentage"] = Field(
        default="tension",
        description="四阶段划分依据：少于 20 章时为固定百分比估计，否则读张力曲线",
    )
