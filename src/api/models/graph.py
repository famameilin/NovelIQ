"""章节级动态图 API 响应模型"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    """2026-08-08 用于返回目标章节边界的实体节点"""

    entity_id: int = Field(gt=0)
    name: str
    entity_type: Literal["character", "location", "item", "organization"]
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    first_seen_chapter: int = Field(ge=0)
    last_seen_chapter: int = Field(ge=0)
    state_chapter_id: int | None = Field(default=None, ge=0)
    state: dict[str, Any]


class GraphEdge(BaseModel):
    """2026-08-07 用于返回目标章节边界的稳定关系边"""

    relation_id: str
    state_chapter_id: int = Field(gt=0)
    source_entity_id: int = Field(gt=0)
    target_entity_id: int = Field(gt=0)
    source_name: str
    target_name: str
    relation_type: str
    directionality: Literal["directed", "bidirectional"]
    relation_semantics: Literal["ordinary", "same_character"]
    attributes: dict[str, Any]
    is_active: bool
    changes: list[dict[str, Any]]


class GraphSnapshotResponse(BaseModel):
    """2026-08-19 用于返回一个章节边界的实体和有效关系"""

    chapter_id: int = Field(gt=0)
    chapter_order: int = Field(gt=0)
    first_chapter_id: int = Field(ge=0)
    last_chapter_id: int = Field(ge=0)
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class GraphChange(BaseModel):
    """2026-08-19 用于返回由单个章节事实解释的实体或关系变化"""

    change_id: str
    change_kind: Literal["state", "relation"]
    chapter_id: int = Field(gt=0)
    chapter_order: int = Field(gt=0)
    fact_id: str
    effective_chapter_id: int = Field(ge=0)
    changes: list[dict[str, Any]] = Field(min_length=1)
    entity_id: int | None = None
    entity_name: str | None = None
    relation_id: str | None = None
    from_entity_id: int | None = None
    to_entity_id: int | None = None
    from_name: str | None = None
    to_name: str | None = None
    relation_type: str | None = None
    relation_change_kind: str | None = None
    directionality: Literal["directed", "bidirectional"] | None = None
    relation_semantics: Literal["ordinary", "same_character"] | None = None


class GraphChangesPageInfo(BaseModel):
    """2026-08-07 用于返回章节图变化分页游标信息"""

    limit: int = Field(gt=0)
    returned_count: int = Field(ge=0)
    total: int = Field(ge=0)
    has_more: bool
    next_cursor: str | None = None


class GraphChangesResponse(BaseModel):
    """2026-08-07 用于返回按章节倒序排列的实体和关系变化"""

    changes: list[GraphChange]
    page_info: GraphChangesPageInfo
