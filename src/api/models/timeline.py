"""
叙事时间轴 API 响应模型。

基于时间轴合同重构后的 v2 节点结构定义时间轴数据结构。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TimelineMeta(BaseModel):
    """时间轴元信息。"""

    novel_id: str = Field(description="小说 ID")
    novel_name: str = Field(description="小说名称")
    total_chunks: int = Field(ge=0, description="总 chunk 数量")
    timeline_contract_version: int = Field(default=2, description="时间轴合同版本")


class TimelinePhase(BaseModel):
    """时间轴阶段。"""

    name: Literal["引入期", "发展期", "高潮期", "收束期"] = Field(description="阶段名称")
    start: int = Field(description="起始 chunk_id")
    end: int = Field(description="结束 chunk_id")
    ratio: float = Field(ge=0, le=1, description="篇幅占比")


class PlotFlags(BaseModel):
    """剧情节点附加标记。"""

    is_pivot: bool = Field(description="是否为转折点")
    is_cliffhanger: bool = Field(description="是否为悬念点")
    tension_percentile: int = Field(ge=0, le=100, description="张力百分位排名")


class RelationTimelineEvent(BaseModel):
    """关系变化事件。"""

    relation_event_id: int = Field(description="关系事件 ID")
    from_char: str = Field(description="源角色名称")
    to_char: str = Field(description="目标角色名称")
    relation_type: str = Field(description="关系类型")
    change_type: Literal["新建", "强化", "弱化", "断裂"] = Field(description="变化类型")
    evidence: str | None = Field(default=None, description="变化依据文本")
    confidence: float | None = Field(default=None, description="关系事件置信度")
    directionality: str | None = Field(default=None, description="关系方向性")


class LifecycleTimelineEvent(BaseModel):
    """角色生命周期事件。"""

    entity_id: int = Field(description="角色实体 ID")
    character_name: str = Field(description="角色名称")
    lifecycle_type: Literal["entry", "exit"] = Field(description="生命周期类型")


class TimelineNode(BaseModel):
    """时间轴节点。"""

    node_id: str = Field(description="节点唯一标识")
    anchor_chunk_id: int = Field(description="节点主锚点 chunk ID")
    progress: float = Field(ge=0, le=1, description="叙事进度 (0-1)")
    importance_score: float = Field(ge=0, description="重要性分数")
    level: Literal[1, 2, 3] = Field(description="重要性级别: 1=重要, 2=较重要, 3=不重要")
    summary: str = Field(description="节点摘要")
    characters: list[str] = Field(default_factory=list, description="涉及角色")
    phase_name: Literal["引入期", "发展期", "高潮期", "收束期"] = Field(description="所属叙事阶段")
    node_type: Literal["plot", "relation", "lifecycle"] = Field(description="节点大类")
    node_subtype: str = Field(description="节点子类型")
    score_breakdown: dict[str, float] = Field(default_factory=dict, description="分项得分")
    plot_flags: PlotFlags | None = Field(default=None, description="剧情节点附加标记")
    relation_events: list[RelationTimelineEvent] | None = Field(default=None, description="关系变化事件")
    lifecycle_events: list[LifecycleTimelineEvent] | None = Field(default=None, description="生命周期事件")


class TimelineResponse(BaseModel):
    """时间轴 API 响应。"""

    meta: TimelineMeta = Field(description="时间轴元信息")
    phases: list[TimelinePhase] = Field(description="四阶段划分")
    nodes: list[TimelineNode] = Field(description="时间轴节点列表")
    tension_curve: list[float] | None = Field(default=None, description="张力曲线数据")
