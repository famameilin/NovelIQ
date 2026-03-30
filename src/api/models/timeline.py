"""
叙事时间轴 API 响应模型。

基于设计文档 v2.0 定义时间轴数据结构。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TimelineMeta(BaseModel):
    """时间轴元信息"""

    novel_id: str = Field(description="小说 ID")
    novel_name: str = Field(description="小说名称")
    total_chunks: int = Field(ge=0, description="总 chunk 数量")


class TimelinePhase(BaseModel):
    """时间轴阶段"""

    name: Literal["引入期", "发展期", "高潮期", "收束期"] = Field(description="阶段名称")
    start: int = Field(description="起始 chunk_id")
    end: int = Field(description="结束 chunk_id")
    ratio: float = Field(ge=0, le=1, description="篇幅占比")


class RelationChangeEvent(BaseModel):
    """关系变化事件"""

    from_char: str = Field(description="源角色名称")
    to_char: str = Field(description="目标角色名称")
    relation_type: str = Field(description="关系类型：敌对/盟友/师徒/家族等")
    change_type: str = Field(description="变化类型：建立/断裂/转化")
    evidence: str | None = Field(default=None, description="变化依据文本")


class TimelineNode(BaseModel):
    """时间轴节点"""

    chunk_id: int = Field(description="所属 chunk ID")
    progress: float = Field(ge=0, le=1, description="叙事进度 (0-1)")
    importance_score: float = Field(ge=0, le=11, description="重要性分数（最高 11 分）")
    level: Literal[1, 2, 3] = Field(description="重要性级别: 1=重要, 2=较重要, 3=不重要")
    event: str = Field(description="事件描述")
    characters: list[str] = Field(default_factory=list, description="涉及角色")
    is_pivot: bool = Field(description="是否为转折点")
    is_cliffhanger: bool = Field(description="是否为悬念点")
    tension_percentile: int = Field(ge=0, le=100, description="张力百分位排名")
    node_type: Literal["plot", "character_entry", "character_exit", "relation_change"] = Field(
        default="plot",
        description="节点类型",
    )
    relation_changes: list[RelationChangeEvent] | None = Field(default=None)
    character_entries: list[str] | None = Field(default=None)
    character_exits: list[str] | None = Field(default=None)


class TimelineResponse(BaseModel):
    """时间轴 API 响应"""

    meta: TimelineMeta = Field(description="时间轴元信息")
    phases: list[TimelinePhase] = Field(description="四阶段划分")
    nodes: list[TimelineNode] = Field(description="时间轴节点列表")
    tension_curve: list[float] | None = Field(default=None, description="张力曲线数据")
