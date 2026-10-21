"图谱查询的普通结果记录"

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ChapterBoundary:
    "用于表示由章节身份派生的图谱边界"

    run_id: str
    chapter_id: int
    chapter_order: int
    first_chapter_id: int
    last_chapter_id: int
    annotation_id: str


@dataclass(frozen=True, slots=True)
class EntitySnapshotRow:
    "用于返回目标章节边界的实体身份与完整状态"

    entity_id: str
    name: str
    entity_type: str
    tags: list[str]
    attributes: dict[str, Any]
    first_seen_chapter: int | None
    last_seen_chapter: int | None
    state_chapter_id: int | None
    state: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RelationSnapshotRow:
    "用于返回目标章节边界的稳定关系状态"

    chapter_id: int | None
    relation_id: str
    from_entity_id: str
    to_entity_id: str
    from_name: str
    to_name: str
    relation_type: str
    directionality: str | None
    relation_semantics: str | None
    attributes: dict[str, Any]
    is_active: bool
    changes: list[dict[str, Any]]
    first_seen_chapter: int | None
    last_seen_chapter: int | None


@dataclass(frozen=True, slots=True)
class GraphChangeRow:
    "用于返回按章节与事实拆分的实体或关系变化"

    change_id: str
    change_kind: Literal["state", "relation"]
    chapter_id: int
    chapter_order: int
    fact_id: str
    effective_chapter_id: int
    confidence: str
    changes: list[dict[str, Any]]
    entity_id: str | None = None
    entity_name: str | None = None
    entity_type: str | None = None
    relation_id: str | None = None
    from_entity_id: str | None = None
    to_entity_id: str | None = None
    from_name: str | None = None
    to_name: str | None = None
    relation_type: str | None = None
    directionality: str | None = None
    relation_semantics: str | None = None


@dataclass(frozen=True, slots=True)
class GraphSnapshotRow:
    "用于承载一个章节边界的实体与有效关系"

    chapter_boundary: ChapterBoundary
    entities: list[EntitySnapshotRow]
    relations: list[RelationSnapshotRow]
