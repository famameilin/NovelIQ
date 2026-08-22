from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.api.exceptions import GraphReadinessError
from src.models.local.character_reference_policy import is_global_character_surface_name
from src.storage.repositories import AnnotationRepository, GraphRepository
from src.storage.repositories.graph import EntitySnapshotRow, GraphChangeRow, RelationSnapshotRow

from .alias import AliasResolution, build_alias_resolution
from .graph_outputs import build_graph_quality_report, build_graph_shared_summary
from .types import (
    CanonicalEntity,
    ConfirmedRelation,
    EntityLifecycle,
    EntityTypeFact,
    ExportGraphAuthorityView,
    ExportRelationSnapshot,
    GraphAuthorityReport,
    GraphAuthorityView,
    GraphChange,
    Level1AuthoritySnapshot,
    ParticipantState,
    TimelineAuthorityView,
)


class KnowledgeGraphAuthorityService:
    """2026-08-07 用于把章节版本 Repository 转换为各后端消费者的受控视图"""

    def __init__(self, graph_repo: GraphRepository, annotation_repo: AnnotationRepository | None = None) -> None:
        """2026-08-07 用于绑定图版本仓储与章节标注读侧"""
        self._graph_repo = graph_repo
        self._annotation_repo = annotation_repo or AnnotationRepository(graph_repo.session)

    @classmethod
    def from_session(cls, session: Any) -> KnowledgeGraphAuthorityService:
        """2026-08-07 用于从同一数据库 Session 构造章节版本 authority"""
        return cls(graph_repo=GraphRepository(session), annotation_repo=AnnotationRepository(session))

    def build_level1_snapshot(self, run_id: str) -> Level1AuthoritySnapshot:
        """2026-08-07 用于提供最新章节实体与有效关系的最小只读视图"""
        entities = self._graph_repo.fetch_latest_entities(run_id)
        relations = self._graph_repo.fetch_latest_relations(run_id, active_only=True)
        resolution = self._build_alias_resolution(relations, entities)
        return Level1AuthoritySnapshot(
            canonical_entities=self._build_canonical_entities(entities, resolution=resolution),
            confirmed_relations=self._build_confirmed_relations(relations, resolution=resolution),
            entity_types=[
                EntityTypeFact(name=entity.name, entity_type=entity.entity_type)
                for entity in entities
                if int(entity.entity_id) not in resolution.representative_by_alias
            ],
        )

    def build_timeline_view(self, run_id: str) -> TimelineAuthorityView:
        """2026-08-07 用于提供章节关系版本变化与角色状态生命周期"""
        self.assert_graph_ready(run_id)
        characters = self._graph_repo.fetch_latest_entities(run_id, entity_type="character")
        relations = self._graph_repo.fetch_latest_relations(run_id, active_only=True)
        resolution = self._build_alias_resolution(relations, characters)
        character_ids = {
            int(entity.entity_id)
            for entity in characters
            if int(entity.entity_id) not in resolution.representative_by_alias
        }
        changes, _total = self._graph_repo.fetch_changes(run_id, limit=None)
        graph_changes = [
            change
            for change in changes
            if (change.change_kind == "state" and change.entity_id in character_ids)
            or (
                change.change_kind == "relation"
                and change.from_entity_id in character_ids
                and change.to_entity_id in character_ids
                and change.relation_semantics != "same_character"
            )
        ]
        canonical_entities = self._build_canonical_entities(characters, resolution=resolution)
        return TimelineAuthorityView(
            character_entities=canonical_entities,
            entity_lifecycles=[
                EntityLifecycle(
                    entity_id=entity.entity_id,
                    name=entity.name,
                    entity_type=entity.entity_type,
                    first_seen_chapter=entity.first_seen_chapter,
                    last_seen_chapter=entity.last_seen_chapter,
                    status=str(entity.state.get("status") or "active"),
                )
                for entity in characters
                if int(entity.entity_id) not in resolution.representative_by_alias
            ],
            graph_changes=self._build_graph_changes(graph_changes),
        )

    def build_graph_report(self, run_id: str) -> GraphAuthorityReport:
        """2026-08-07 用于向诊断和导出提供章节版本图的聚合信号"""
        graph_view = self.build_representative_graph_view(run_id)
        return GraphAuthorityReport(
            summary=build_graph_shared_summary(
                graph_view.participant_states,
                graph_view.confirmed_relations,
            ),
            quality=build_graph_quality_report(
                graph_view.confirmed_relations,
                graph_view.graph_changes,
            ),
        )

    def build_export_view(self, run_id: str) -> ExportGraphAuthorityView:
        """2026-08-07 用于提供导出需要的最新实体关系和章节关系变化"""
        self.assert_graph_ready(run_id)
        entities = self._graph_repo.fetch_latest_entities(run_id)
        current_relations = self._graph_repo.fetch_latest_relations(run_id, active_only=False)
        changes, _total = self._graph_repo.fetch_changes(run_id, limit=None)
        resolution = self._build_alias_resolution(current_relations, entities)
        return ExportGraphAuthorityView(
            canonical_entities=self._build_canonical_entities(entities, resolution=resolution),
            current_relations=self._build_export_relation_snapshots(current_relations),
            graph_changes=self._build_graph_changes(changes),
        )

    def build_graph_view(self, run_id: str) -> GraphAuthorityView:
        """2026-08-07 用于提供最新章节图与完整关系版本变化"""
        self.assert_graph_ready(run_id)
        entities = self._graph_repo.fetch_latest_entities(run_id)
        relations = self._graph_repo.fetch_latest_relations(run_id, active_only=True)
        changes, _total = self._graph_repo.fetch_changes(run_id, limit=None)
        resolution = self._build_alias_resolution(relations, entities)
        return GraphAuthorityView(
            canonical_entities=self._build_canonical_entities(entities, resolution=resolution),
            confirmed_relations=self._build_confirmed_relations(relations, resolution=resolution),
            graph_changes=self._build_graph_changes(changes),
            participant_states=self._build_participant_states(entities, resolution=resolution),
        )

    def build_representative_graph_view(self, run_id: str) -> GraphAuthorityView:
        """2026-08-07 用于向聚合与诊断提供排除 same_character 边的最新图"""
        self.assert_graph_ready(run_id)
        relations = [
            relation
            for relation in self._graph_repo.fetch_latest_relations(run_id, active_only=True)
            if relation.relation_semantics != "same_character"
        ]
        endpoint_ids = {
            entity_id for relation in relations for entity_id in (relation.from_entity_id, relation.to_entity_id)
        }
        entities = [
            entity for entity in self._graph_repo.fetch_latest_entities(run_id) if entity.entity_id in endpoint_ids
        ]
        changes, _total = self._graph_repo.fetch_changes(run_id, limit=None)
        graph_changes = [
            change
            for change in changes
            if change.change_kind != "relation" or change.relation_semantics != "same_character"
        ]
        resolution = self._build_alias_resolution(relations, entities)
        return GraphAuthorityView(
            canonical_entities=self._build_canonical_entities(entities, resolution=resolution),
            confirmed_relations=self._build_confirmed_relations(relations, resolution=resolution),
            graph_changes=self._build_graph_changes(graph_changes),
            participant_states=self._build_participant_states(entities, resolution=resolution),
        )

    def assert_graph_ready(self, run_id: str) -> None:
        """2026-08-07 用于确认当前 run 至少存在一个成功章节图版本"""
        if self._graph_repo.resolve_chapter_boundary(run_id) is None:
            raise GraphReadinessError(f"run 尚无已完成章节图数据: {run_id}")

    def _build_alias_resolution(
        self,
        relations: Iterable[RelationSnapshotRow],
        entities: Iterable[EntitySnapshotRow],
    ) -> AliasResolution:
        """2026-08-11 用于从同一人物关系与实体属性构建别名归并映射"""
        return build_alias_resolution(list(relations), entities=list(entities))

    def _build_canonical_entities(
        self,
        entities: Iterable[EntitySnapshotRow],
        resolution: AliasResolution | None = None,
    ) -> list[CanonicalEntity]:
        """2026-08-07 用于把实体状态快照转换为规范实体合同"""
        rows = sorted(entities, key=lambda row: row.name)
        if resolution is not None:
            rows = [row for row in rows if int(row.entity_id) not in resolution.representative_by_alias]
        result: list[CanonicalEntity] = []
        for entity in rows:
            if not is_global_character_surface_name(entity.name):
                continue
            aliases = (
                resolution.aliases_by_representative.get(int(entity.entity_id), []) if resolution is not None else []
            )
            result.append(
                CanonicalEntity(
                    name=entity.name,
                    entity_type=entity.entity_type,
                    entity_id=entity.entity_id,
                    first_seen_chapter=entity.first_seen_chapter,
                    last_seen_chapter=entity.last_seen_chapter,
                    primary_role_function=str(entity.state.get("role_function") or "") or None,
                    status=str(entity.state.get("status") or "active"),
                    source_confidence=None,
                    aliases=aliases,
                )
            )
        return result

    def _build_confirmed_relations(
        self,
        relations: Iterable[RelationSnapshotRow],
        resolution: AliasResolution | None = None,
    ) -> list[ConfirmedRelation]:
        """2026-08-07 用于把稳定关系最新版本转换为当前关系合同"""
        result: list[ConfirmedRelation] = []
        for relation in sorted(
            relations,
            key=lambda row: (row.from_name, row.to_name, row.relation_type),
        ):
            if relation.relation_semantics == "same_character":
                continue
            from_name = resolution.resolve_name(relation.from_name) if resolution is not None else relation.from_name
            to_name = resolution.resolve_name(relation.to_name) if resolution is not None else relation.to_name
            from_entity_id = (
                resolution.resolve_entity_id(relation.from_entity_id)
                if resolution is not None
                else relation.from_entity_id
            )
            to_entity_id = (
                resolution.resolve_entity_id(relation.to_entity_id) if resolution is not None else relation.to_entity_id
            )
            result.append(
                ConfirmedRelation(
                    from_name=from_name or "",
                    to_name=to_name or "",
                    relation_type=relation.relation_type,
                    from_entity_id=from_entity_id,
                    to_entity_id=to_entity_id,
                    is_active=relation.is_active,
                    first_seen_chapter=relation.first_seen_chapter,
                    last_seen_chapter=relation.last_seen_chapter,
                    change_count=len(relation.changes),
                    support_count=int(relation.attributes.get("support_count", 1)),
                    tension_index=float(relation.attributes.get("tension_index", 0.0)),
                )
            )
        return result

    def _build_export_relation_snapshots(
        self,
        relations: Iterable[RelationSnapshotRow],
    ) -> list[ExportRelationSnapshot]:
        """2026-08-07 用于把稳定关系最新版本转换为导出关系快照"""
        return [
            ExportRelationSnapshot(
                relation_id=relation.relation_id,
                from_name=relation.from_name,
                to_name=relation.to_name,
                relation_type=relation.relation_type,
                first_seen_chapter=relation.first_seen_chapter,
                last_seen_chapter=relation.last_seen_chapter,
                is_active=relation.is_active,
            )
            for relation in relations
        ]

    def _build_graph_changes(
        self,
        rows: Iterable[GraphChangeRow],
    ) -> list[GraphChange]:
        """2026-08-07 用于把 Repository 章节变化转换为共享双源合同"""
        return [
            GraphChange(
                change_id=row.change_id,
                change_kind=row.change_kind,
                chapter_id=row.chapter_id,
                chapter_order=row.chapter_order,
                fact_id=row.fact_id,
                effective_chapter_id=row.effective_chapter_id,
                confidence=row.confidence,
                changes=list(row.changes),
                entity_id=row.entity_id,
                entity_name=row.entity_name,
                entity_type=row.entity_type,
                relation_id=row.relation_id,
                from_entity_id=row.from_entity_id,
                to_entity_id=row.to_entity_id,
                from_name=row.from_name,
                to_name=row.to_name,
                relation_type=row.relation_type,
                directionality=row.directionality,
                relation_semantics=row.relation_semantics,
            )
            for row in rows
        ]

    def _build_participant_states(
        self,
        entities: Iterable[EntitySnapshotRow],
        resolution: AliasResolution | None = None,
    ) -> list[ParticipantState]:
        """2026-08-07 用于把实体状态快照转换为图参与者合同"""
        return [
            ParticipantState(
                entity_id=entity.entity_id,
                name=entity.name,
                entity_type=entity.entity_type,
                status=str(entity.state.get("status") or "active"),
                primary_role_function=str(entity.state.get("role_function") or "") or None,
                first_seen_chapter=entity.first_seen_chapter,
                last_seen_chapter=entity.last_seen_chapter,
                source_confidence=None,
                is_representative=(
                    resolution is None or int(entity.entity_id) not in resolution.representative_by_alias
                ),
            )
            for entity in entities
            if is_global_character_surface_name(entity.name)
            and (resolution is None or int(entity.entity_id) not in resolution.representative_by_alias)
        ]
