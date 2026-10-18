"在事实图领域解释关系类型，不向 Storage 下放业务词表"

from __future__ import annotations

from dataclasses import replace

from src.fact_graph.vocabulary import RELATION_DEFINITIONS
from src.storage.records.graph import ChapterBoundary, GraphChangeRow, GraphSnapshotRow, RelationSnapshotRow


def _project(value):
    if isinstance(value, (RelationSnapshotRow, GraphChangeRow)) and value.relation_type is not None:
        definition = RELATION_DEFINITIONS.get(value.relation_type) or {}
        return replace(
            value,
            directionality=str(definition.get("directionality", "directed")),
            relation_semantics=str(definition.get("semantics", "ordinary")),
        )
    if isinstance(value, GraphSnapshotRow):
        return replace(value, relations=[_project(row) for row in value.relations])
    if isinstance(value, list):
        return [_project(row) for row in value]
    if isinstance(value, tuple):
        return tuple(_project(row) for row in value)
    return value


class GraphProjection:
    "只消费普通记录并补充本领域关系语义"

    def __init__(self, source):
        self._source = source

    def run_exists(self, run_id: str):
        return _project(self._source.run_exists(run_id))

    def resolve_chapter_boundary(self, run_id: str, *, chapter_id: int | None = None):
        return _project(self._source.resolve_chapter_boundary(run_id, chapter_id=chapter_id))

    def resolve_persisted_boundary(self, run_id: str):
        return _project(self._source.resolve_persisted_boundary(run_id))

    def fetch_entity_snapshots(self, boundary: ChapterBoundary):
        return _project(self._source.fetch_entity_snapshots(boundary))

    def fetch_relation_snapshots(self, boundary: ChapterBoundary, *, active_only: bool = True):
        return _project(self._source.fetch_relation_snapshots(boundary, active_only=active_only))

    def fetch_snapshot(self, run_id: str, *, chapter_id: int | None = None):
        return _project(self._source.fetch_snapshot(run_id, chapter_id=chapter_id))

    def fetch_changes(self, run_id: str, *, chapter_id: int | None = None, offset: int = 0, limit: int | None = 200):
        return _project(self._source.fetch_changes(run_id, chapter_id=chapter_id, offset=offset, limit=limit))

    def fetch_latest_entity_rows(self, run_id: str, *, entity_type: str | None = None):
        return _project(self._source.fetch_latest_entity_rows(run_id, entity_type=entity_type))

    def fetch_latest_relations(self, run_id: str, *, active_only: bool = True):
        return _project(self._source.fetch_latest_relations(run_id, active_only=active_only))

    def fetch_relation_history(self, run_id: str):
        return _project(self._source.fetch_relation_history(run_id))

    def fetch_relation_changes(self, run_id: str, *, limit: int | None = None):
        return _project(self._source.fetch_relation_changes(run_id, limit=limit))

    def count_chapters(self, run_id: str):
        return _project(self._source.count_chapters(run_id))


def graph_projection(source):
    return source if isinstance(source, GraphProjection) else GraphProjection(source)
