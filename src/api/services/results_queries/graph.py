"""章节级动态图查询组装器"""

from __future__ import annotations

import binascii
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

from loguru import logger

from src.api.models.responses import CharacterRelation, HierarchicalRelation
from src.knowledge.authority import ExportGraphAuthorityView, KnowledgeGraphAuthorityService
from src.knowledge.authority.alias import build_alias_resolution
from src.storage.repositories import AnnotationRepository, GraphRepository

GRAPH_CHANGE_LIMIT = 200

HIERARCHICAL_RELATION_TYPES = {
    "隶属",
}


def _encode_graph_changes_cursor(offset: int) -> str:
    """2026-08-07 用于把图变化分页偏移编码为稳定游标"""
    payload = json.dumps({"offset": offset}, separators=(",", ":")).encode("utf-8")
    return urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_graph_changes_cursor(cursor: str | None) -> int:
    """2026-08-07 用于校验并解析图变化分页游标"""
    if not cursor:
        return 0
    padded_cursor = cursor + ("=" * (-len(cursor) % 4))
    try:
        payload = json.loads(urlsafe_b64decode(padded_cursor.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise ValueError("invalid graph changes cursor") from exc
    offset = payload.get("offset")
    if type(offset) is not int or offset < 0:
        raise ValueError("invalid graph changes cursor")
    return offset


def _build_graph_changes_page_info(
    *,
    start: int,
    page_limit: int,
    returned_count: int,
    total: int,
) -> dict[str, Any]:
    """2026-08-07 用于组装图变化分页状态"""
    end = start + returned_count
    next_cursor = _encode_graph_changes_cursor(end) if end < total else None
    return {
        "limit": page_limit,
        "returned_count": returned_count,
        "total": total,
        "has_more": next_cursor is not None,
        "next_cursor": next_cursor,
    }


def _fetch_character_relations(
    run_id: str,
    annotation_repo: AnnotationRepository,
    valid_character_names: set[str] | None = None,
    export_graph_view: ExportGraphAuthorityView | None = None,
) -> list[CharacterRelation]:
    """2026-08-07 用于从最新章节关系版本生成角色关系导出数据"""
    authority_service = KnowledgeGraphAuthorityService.from_session(annotation_repo.session)
    authority_service.assert_graph_ready(run_id)
    if export_graph_view is None:
        export_graph_view = authority_service.build_export_view(run_id)

    result: list[CharacterRelation] = []
    for relation in export_graph_view.current_relations:
        if not relation.is_active:
            continue
        from_char = relation.from_name
        to_char = relation.to_name
        if valid_character_names is not None and (
            from_char not in valid_character_names or to_char not in valid_character_names
        ):
            continue
        chunk_id = relation.last_seen_chunk or relation.first_seen_chunk
        if chunk_id is None:
            logger.warning(
                "跳过缺少 chunk_id 的当前关系快照: from_char={}, to_char={}, type={}",
                from_char,
                to_char,
                relation.relation_type,
            )
            continue
        result.append(
            CharacterRelation(
                chunk_id=chunk_id,
                from_char=from_char,
                to_char=to_char,
                type=relation.relation_type,
                change="汇总",
            )
        )
    return result


def _fetch_hierarchical_relations(
    run_id: str,
    export_graph_view: ExportGraphAuthorityView,
    valid_character_names: set[str] | None = None,
) -> list[HierarchicalRelation]:
    """2026-08-07 用于从最新章节关系版本生成层级关系导出数据"""
    del run_id
    hierarchical_types = HIERARCHICAL_RELATION_TYPES
    valid_entity_names = {
        entity.name for entity in export_graph_view.canonical_entities if entity.name
    }
    result: list[HierarchicalRelation] = []
    for relation in export_graph_view.current_relations:
        if not relation.is_active or relation.relation_type not in hierarchical_types:
            continue
        allowed_names = valid_entity_names or valid_character_names
        if allowed_names is not None and (
            relation.from_name not in allowed_names or relation.to_name not in allowed_names
        ):
            continue
        if relation.relation_id is None:
            raise ValueError("章节关系快照缺少稳定 relation_id")
        result.append(
            HierarchicalRelation(
                rel_id=relation.relation_id,
                rel_type=relation.relation_type,
                first_chunk=relation.first_seen_chunk,
                last_chunk=relation.last_seen_chunk,
                from_entity=relation.from_name,
                to_entity=relation.to_name,
            )
        )
    return result


def _fetch_graph_snapshot(
    run_id: str,
    annotation_repo: AnnotationRepository,
    *,
    chapter_id: int | None = None,
    graph_version_id: str | None = None,
) -> dict[str, Any]:
    """2026-08-07 用于直接返回目标章节图版本的实体状态和有效关系"""
    snapshot = GraphRepository(annotation_repo.session).fetch_snapshot(
        run_id,
        chapter_id=chapter_id,
        graph_version_id=graph_version_id,
    )
    if snapshot is None:
        raise LookupError("当前 run 尚无匹配的章节图版本")
    version = snapshot.graph_version
    entity_names = {entity.entity_id: entity.name for entity in snapshot.entities}
    resolution = build_alias_resolution(snapshot.relations, entity_names=entity_names)
    nodes = [
        {
            "entity_id": entity.entity_id,
            "name": entity.name,
            "entity_type": entity.entity_type,
            "tags": entity.tags,
            "aliases": resolution.aliases_by_representative.get(entity.entity_id, []),
            "first_seen_chunk": entity.first_seen_chunk,
            "last_seen_chunk": entity.last_seen_chunk,
            "state_revision": entity.state_revision,
            "state": entity.state,
        }
        for entity in snapshot.entities
        if entity.entity_id not in resolution.representative_by_alias
    ]
    edges: list[dict[str, Any]] = []
    for relation in snapshot.relations:
        if relation.relation_semantics == "same_character":
            continue
        from_entity_id = resolution.resolve_entity_id(relation.from_entity_id)
        to_entity_id = resolution.resolve_entity_id(relation.to_entity_id)
        edges.append(
            {
                "relation_id": relation.relation_id,
                "relation_version_id": relation.relation_version_id,
                "relation_revision": relation.relation_revision,
                "source_entity_id": from_entity_id,
                "target_entity_id": to_entity_id,
                "source_name": resolution.resolve_name(relation.from_name),
                "target_name": resolution.resolve_name(relation.to_name),
                "relation_type": relation.relation_type,
                "directionality": relation.directionality,
                "relation_semantics": relation.relation_semantics,
                "attributes": relation.attributes,
                "is_active": relation.is_active,
                "changes": relation.changes,
            }
        )
    return {
        "graph_version_id": version.graph_version_id,
        "chapter_id": version.chapter_id,
        "chapter_order": version.chapter_order,
        "first_chunk_id": version.first_chunk_id,
        "last_chunk_id": version.last_chunk_id,
        "nodes": nodes,
        "edges": edges,
    }


def _fetch_graph_changes_page(
    run_id: str,
    annotation_repo: AnnotationRepository,
    *,
    chapter_id: int | None = None,
    changes_cursor: str | None = None,
    changes_limit: int = GRAPH_CHANGE_LIMIT,
) -> dict[str, Any]:
    """2026-08-07 用于按章节倒序分页返回实体与关系版本变化"""
    start = _decode_graph_changes_cursor(changes_cursor)
    page_limit = max(1, min(changes_limit, GRAPH_CHANGE_LIMIT))
    rows, total = GraphRepository(annotation_repo.session).fetch_changes(
        run_id,
        chapter_id=chapter_id,
        offset=start,
        limit=page_limit,
    )
    if start > total:
        raise ValueError("graph changes cursor is out of range")
    return {
        "changes": [
            {
                "change_id": row.change_id,
                "change_kind": row.change_kind,
                "graph_version_id": row.graph_version_id,
                "chapter_id": row.chapter_id,
                "chapter_order": row.chapter_order,
                "fact_id": row.fact_id,
                "fact_revision": row.fact_revision,
                "effective_chunk_id": row.effective_chunk_id,
                "changes": row.changes,
                "evidence": row.evidence.model_dump(mode="json"),
                "entity_id": row.entity_id,
                "entity_name": row.entity_name,
                "relation_id": row.relation_id,
                "relation_version_id": row.relation_version_id,
                "relation_revision": row.relation_revision,
                "from_entity_id": row.from_entity_id,
                "to_entity_id": row.to_entity_id,
                "from_name": row.from_name,
                "to_name": row.to_name,
                "relation_type": row.relation_type,
                "relation_change_kind": (
                    str(row.changes[0].get("change_kind"))
                    if row.change_kind == "relation" and row.changes and row.changes[0].get("change_kind") is not None
                    else None
                ),
                "directionality": row.directionality,
                "relation_semantics": row.relation_semantics,
            }
            for row in rows
        ],
        "page_info": _build_graph_changes_page_info(
            start=start,
            page_limit=page_limit,
            returned_count=len(rows),
            total=total,
        ),
    }


__all__ = [
    "GRAPH_CHANGE_LIMIT",
    "_fetch_character_relations",
    "_fetch_graph_changes_page",
    "_fetch_graph_snapshot",
    "_fetch_hierarchical_relations",
]
