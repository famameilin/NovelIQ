"""
图谱查询组装器。

创建时间: 2026-04-23
创建者: Codex
任务: p1-api-route-service-decouple
说明: 承载 graph 相关查询组装逻辑。
"""

from __future__ import annotations

import binascii
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

from loguru import logger

from src.api.exceptions import GraphReadinessError
from src.api.models.responses import CharacterRelation, HierarchicalRelation
from src.knowledge.authority import (
    GRAPH_PAGE_AUTHORITY_DEPENDENCY_FIELDS,
    ExportGraphAuthorityView,
    GraphPageQualityDetails,
    GraphPageSummary,
    KnowledgeGraphAuthorityService,
)
from src.knowledge.authority.graph_outputs import build_graph_page_quality, build_graph_page_summary
from src.storage.repositories import AnnotationRepository

from .common import _normalize_name

GRAPH_PAGE_EVENT_LIMIT = 200


def _encode_graph_events_cursor(offset: int) -> str:
    payload = json.dumps({"offset": offset}, separators=(",", ":")).encode("utf-8")
    return urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_graph_events_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0

    padded_cursor = cursor + ("=" * (-len(cursor) % 4))
    try:
        payload = json.loads(urlsafe_b64decode(padded_cursor.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise ValueError("invalid graph events cursor") from exc

    offset = payload.get("offset")
    if type(offset) is not int or offset < 0:
        raise ValueError("invalid graph events cursor")
    return offset


def _serialize_graph_event(event: Any) -> dict[str, Any]:
    return {
        "relation_event_id": event.relation_event_id,
        "chunk_id": event.chunk_id,
        "from_entity_id": event.from_entity_id,
        "to_entity_id": event.to_entity_id,
        "from_name": event.from_name,
        "to_name": event.to_name,
        "relation_type": event.relation_type,
        "change_type": event.change_type,
        "evidence": event.evidence,
        "confidence": event.confidence,
        "source_relation_row_id": event.source_relation_row_id,
        "directionality": event.directionality,
    }


def _serialize_graph_page_summary(summary: GraphPageSummary) -> dict[str, Any]:
    """Convert graph-page summary facts into the public DTO."""
    return {
        "node_count": summary.node_count,
        "edge_count": summary.edge_count,
        "density": summary.density,
        "core_characters": list(summary.core_characters),
        "key_relations": [
            {
                "from": relation.from_name,
                "to": relation.to_name,
                "type": relation.relation_type,
                "support_count": relation.support_count,
            }
            for relation in summary.key_relations
        ],
    }


def _serialize_graph_page_quality(quality: GraphPageQualityDetails) -> dict[str, Any]:
    """Convert graph-page quality facts into the public DTO."""
    return {
        "conflict_count": quality.conflict_count,
        "low_confidence_count": quality.low_confidence_count,
        "conflicts": [
            {
                "entity_pair": list(conflict.entity_pair),
                "entity_names": list(conflict.entity_names),
                "relation_types": list(conflict.relation_types),
                "relation_count": conflict.relation_count,
                "latest_event_ids": list(conflict.latest_event_ids),
            }
            for conflict in quality.conflicts
        ],
        "low_confidence_samples": [
            {
                "relation_event_id": event.relation_event_id,
                "chunk_id": event.chunk_id,
                "from_name": event.from_name,
                "to_name": event.to_name,
                "relation_type": event.relation_type,
                "change_type": event.change_type,
                "confidence": event.confidence,
            }
            for event in quality.low_confidence_samples
        ],
    }


def _validate_authority_dependency_items(
    items: list[Any],
    required_fields: tuple[str, ...],
    *,
    contract_name: str,
) -> None:
    for item in items:
        missing_fields = [field_name for field_name in required_fields if not hasattr(item, field_name)]
        if missing_fields:
            raise RuntimeError(f"{contract_name} is missing required authority fields: {', '.join(missing_fields)}")


def _resolve_graph_page_authority_contract(graph_view: Any) -> tuple[list[Any], list[Any], list[Any]]:
    participant_states = list(getattr(graph_view, "participant_states", []))
    confirmed_relations = list(getattr(graph_view, "confirmed_relations", []))
    relation_events = list(getattr(graph_view, "relation_events", []))

    required_slices = {
        "participant_states": participant_states,
        "confirmed_relations": confirmed_relations,
        "relation_events": relation_events,
    }
    for slice_name, slice_items in required_slices.items():
        if not hasattr(graph_view, slice_name):
            raise RuntimeError(f"graph page authority contract is missing required slice: {slice_name}")
        _validate_authority_dependency_items(
            slice_items,
            GRAPH_PAGE_AUTHORITY_DEPENDENCY_FIELDS[slice_name],
            contract_name=f"graph page authority contract.{slice_name}",
        )

    return participant_states, confirmed_relations, relation_events


def _paginate_graph_relation_events(
    relation_events: list[Any],
    *,
    cursor: str | None = None,
    limit: int = GRAPH_PAGE_EVENT_LIMIT,
) -> tuple[list[Any], dict[str, Any]]:
    page_limit = max(1, min(limit, GRAPH_PAGE_EVENT_LIMIT))
    start = _decode_graph_events_cursor(cursor)
    total = len(relation_events)
    if start > total:
        raise ValueError("graph events cursor is out of range")

    end = min(start + page_limit, total)
    next_cursor = _encode_graph_events_cursor(end) if end < total else None
    page_info = {
        "limit": page_limit,
        "returned_count": end - start,
        "total": total,
        "has_more": next_cursor is not None,
        "next_cursor": next_cursor,
    }
    return relation_events[start:end], page_info


def _build_graph_events_page_info(
    *,
    start: int,
    page_limit: int,
    returned_count: int,
    total: int,
) -> dict[str, Any]:
    end = start + returned_count
    next_cursor = _encode_graph_events_cursor(end) if end < total else None
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
    alias_map: dict[str, str] | None = None,
    valid_character_names: set[str] | None = None,
    export_graph_view: ExportGraphAuthorityView | None = None,
) -> list:
    """获取角色关系数据。"""
    if export_graph_view is None:
        export_graph_view = KnowledgeGraphAuthorityService.from_session(annotation_repo.session).build_export_view(
            run_id
        )

    if not export_graph_view.current_relations:
        pending_relations = annotation_repo.fetch_pending_chunk_relations(run_id, limit=1)
        if pending_relations:
            raise GraphReadinessError(
                "graph current relations are empty while pending relations still exist; "
                "run graph projection before reading character relations."
            )

    result: list[CharacterRelation] = []
    for relation in export_graph_view.current_relations:
        from_char = _normalize_name(relation.from_name, alias_map) or relation.from_name
        to_char = _normalize_name(relation.to_name, alias_map) or relation.to_name
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
    alias_map: dict[str, str] | None = None,
    valid_character_names: set[str] | None = None,
) -> list:
    """获取层级关系数据。"""
    hierarchical_types = {"child_of", "parent_of", "father_of", "son_of", "sibling_of", "spouse_of"}
    result = []
    for relation in export_graph_view.current_relations:
        rel_type = relation.relation_type
        if rel_type not in hierarchical_types:
            continue
        from_name_raw = relation.from_name
        to_name_raw = relation.to_name
        from_entity = _normalize_name(from_name_raw, alias_map) or from_name_raw
        to_entity = _normalize_name(to_name_raw, alias_map) or to_name_raw
        if valid_character_names is not None and (
            from_entity not in valid_character_names or to_entity not in valid_character_names
        ):
            continue
        rel_id = relation.relation_id
        if rel_id is None:
            continue
        result.append(
            HierarchicalRelation(
                rel_id=rel_id,
                rel_type=rel_type,
                first_chunk=relation.first_seen_chunk,
                last_chunk=relation.last_seen_chunk,
                from_entity=from_entity,
                to_entity=to_entity,
            )
        )
    return result


def _fetch_graph_snapshot(
    run_id: str,
    annotation_repo: AnnotationRepository,
    *,
    events_cursor: str | None = None,
    events_limit: int = GRAPH_PAGE_EVENT_LIMIT,
) -> dict[str, Any]:
    """获取知识图谱快照（nodes/edges/events/summary）。"""
    pending_relations = annotation_repo.fetch_pending_chunk_relations(run_id, limit=1)
    if pending_relations:
        raise GraphReadinessError("graph projection is still pending; finish projection before reading graph snapshot.")

    authority_service = KnowledgeGraphAuthorityService.from_session(annotation_repo.session)
    graph_view = authority_service.build_graph_view(run_id)
    participant_states, confirmed_relations, relation_events = _resolve_graph_page_authority_contract(graph_view)

    nodes = [
        {
            "entity_id": str(row.entity_id),
            "name": row.name,
            "entity_type": row.entity_type,
            "first_seen_chunk": row.first_seen_chunk,
            "last_seen_chunk": row.last_seen_chunk,
            "role": row.primary_role_function,
            "status": row.status,
        }
        for row in participant_states
    ]
    edges = [
        {
            "source": str(edge.from_entity_id) if edge.from_entity_id is not None else edge.from_name,
            "target": str(edge.to_entity_id) if edge.to_entity_id is not None else edge.to_name,
            "relation_type": edge.relation_type,
            "weight": edge.support_count or 1,
            "from_name": edge.from_name,
            "to_name": edge.to_name,
            "change_count": edge.change_count,
            "tension_index": edge.tension_index,
            "is_active": edge.is_active,
        }
        for edge in confirmed_relations
    ]
    paged_relation_events, events_page = _paginate_graph_relation_events(
        relation_events,
        cursor=events_cursor,
        limit=events_limit,
    )
    events = [_serialize_graph_event(event) for event in paged_relation_events]
    summary = _serialize_graph_page_summary(build_graph_page_summary(participant_states, confirmed_relations))
    quality = _serialize_graph_page_quality(build_graph_page_quality(confirmed_relations, relation_events))

    return {
        "nodes": nodes,
        "edges": edges,
        "events": events,
        "events_page": events_page,
        "summary": summary,
        "quality": quality,
    }


def _fetch_graph_events_page(
    run_id: str,
    annotation_repo: AnnotationRepository,
    *,
    events_cursor: str | None = None,
    events_limit: int = GRAPH_PAGE_EVENT_LIMIT,
) -> dict[str, Any]:
    """获取 graph page relation events 的增量分页结果。"""
    pending_relations = annotation_repo.fetch_pending_chunk_relations(run_id, limit=1)
    if pending_relations:
        raise GraphReadinessError("graph projection is still pending; finish projection before reading graph events.")

    authority_service = KnowledgeGraphAuthorityService.from_session(annotation_repo.session)
    start = _decode_graph_events_cursor(events_cursor)
    page_limit = max(1, min(events_limit, GRAPH_PAGE_EVENT_LIMIT))
    paged_relation_events, total = authority_service.build_graph_relation_event_page(
        run_id,
        offset=start,
        limit=page_limit,
    )
    if start > total:
        raise ValueError("graph events cursor is out of range")
    page_info = _build_graph_events_page_info(
        start=start,
        page_limit=page_limit,
        returned_count=len(paged_relation_events),
        total=total,
    )

    return {
        "events": [_serialize_graph_event(event) for event in paged_relation_events],
        "page_info": page_info,
    }


__all__ = [
    "GRAPH_PAGE_EVENT_LIMIT",
    "_fetch_character_relations",
    "_fetch_graph_events_page",
    "_fetch_graph_snapshot",
    "_fetch_hierarchical_relations",
    "_serialize_graph_page_quality",
    "_serialize_graph_page_summary",
]
