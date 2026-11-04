"""事件响应与实体身份的只读装配"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.event_trees.read.forest import EventForestQuery
from src.event_trees.read.models import EventForestSnapshot
from src.event_trees.read.organization import EventTreeQuery
from src.fact_graph.read.references import EntityReferenceProjection
from src.fact_graph.read.storage_projection import graph_projection
from src.storage import Storage


class EventTreeReadService:
    """组合事件正文与同一运行、章节范围内的正式身份"""

    def __init__(self, storage: Storage, run_id: str) -> None:
        self.storage, self.run_id = storage, run_id
        self.events = EventTreeQuery(storage, run_id)
        self._identities: EntityReferenceProjection | None = None

    def _projection(self) -> EntityReferenceProjection:
        if self._identities is None:
            self._identities = EntityReferenceProjection.load(self.storage, self.run_id)
        return self._identities

    def fetch(self) -> dict[str, Any]:
        "读取完整事件树、包含关系和实际结果"
        return self.events.fetch()

    def _characters(self, event_id: str) -> list[dict[str, Any]]:
        characters: dict[str, dict[str, Any]] = {}
        for participant in self._projection().participants(self.events.participant_references(event_id)):
            entity = participant.get("entity") or {}
            identifier = entity.get("entity_id")
            if entity.get("entity_type") != "character" or identifier is None or identifier in characters:
                continue
            characters[identifier] = {
                "entity_id": identifier, "name": entity.get("name"), "role": participant.get("role")
            }
        return list(characters.values())

    def detail(self, node_id: str) -> dict[str, Any]:
        "将事件详情中的人物引用投影为本运行的正式身份"
        result = self.events.detail(node_id)
        result["characters"] = self._characters(node_id)
        return result

    def evidence(self, node_id: str) -> list[dict[str, Any]]:
        "读取事件证据时不装配无关的人物身份投影"
        return self.events.detail(node_id)["evidence"]

    def chapter_detail(self, chapter_id: int, event_id: str) -> dict[str, Any]:
        "按指定章节边界装配参与者，保留动作与情绪的独立陈述"
        result = self.events.chapter_detail(chapter_id, event_id)
        boundary = graph_projection(self.storage.graph).resolve_chapter_boundary(self.run_id, chapter_id=chapter_id)
        if boundary is None:
            raise LookupError("NODE_NOT_FOUND")
        projection = EntityReferenceProjection.load(self.storage, self.run_id, boundary=boundary)
        result["participants"] = projection.participants(result["participants"])
        return result

    def export(self) -> dict[str, Any]:
        "全量事件导出复用同一批身份映射"
        result = self.events.export()
        for detail in result["details"]:
            detail["characters"] = self._characters(detail["event_id"])
        return result


def project_forest_entities(snapshot: EventForestSnapshot, storage: Storage, run_id: str) -> EventForestSnapshot:
    """整批投影使用同一章节边界，不改写事件记录"""
    boundary = EventForestQuery(storage).resolve_chapter_boundary(run_id, chapter_id=snapshot.chapter_id)
    projection = EntityReferenceProjection.load(storage, run_id, boundary=boundary)
    return replace(
        snapshot,
        event_nodes=[
            replace(node, participants=projection.participants(node.participants)) for node in snapshot.event_nodes
        ],
    )
