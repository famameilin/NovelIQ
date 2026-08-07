from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.models.local.character_reference_policy import is_global_character_surface_name
from src.storage.repositories import AnnotationRepository, GraphRepository
from src.storage.repositories.graph import EntitySnapshotRow, GraphChangeRow, RelationSnapshotRow

from .graph_outputs import build_graph_quality_report, build_graph_shared_summary
from .types import (
    ActiveEntityContext,
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
        return Level1AuthoritySnapshot(
            canonical_entities=self._build_canonical_entities(entities),
            confirmed_relations=self._build_confirmed_relations(relations),
            entity_types=[
                EntityTypeFact(name=entity.name, entity_type=entity.entity_type)
                for entity in entities
            ],
        )

    def build_timeline_view(self, run_id: str) -> TimelineAuthorityView:
        """2026-08-07 用于提供章节关系版本变化与角色状态生命周期"""
        self.assert_graph_ready(run_id)
        characters = self._graph_repo.fetch_latest_entities(run_id, entity_type="character")
        character_ids = {entity.entity_id for entity in characters}
        changes, _total = self._graph_repo.fetch_changes(run_id, limit=None)
        graph_changes = [
            change
            for change in changes
            if (
                change.change_kind == "state"
                and change.entity_id in character_ids
            )
            or (
                change.change_kind == "relation"
                and change.from_entity_id in character_ids
                and change.to_entity_id in character_ids
                and change.relation_semantics != "same_character"
            )
        ]
        canonical_entities = self._build_canonical_entities(characters)
        return TimelineAuthorityView(
            character_entities=canonical_entities,
            entity_lifecycles=[
                EntityLifecycle(
                    entity_id=entity.entity_id,
                    name=entity.name,
                    entity_type=entity.entity_type,
                    first_seen_chunk=entity.first_seen_chunk,
                    last_seen_chunk=entity.last_seen_chunk,
                    status=str(entity.state.get("status") or "active"),
                )
                for entity in characters
            ],
            graph_changes=self._build_graph_changes(graph_changes),
        )

    def build_active_entity_view(
        self,
        run_id: str,
        current_chunk: int,
        lookback: int = 10,
    ) -> list[ActiveEntityContext]:
        """2026-08-07 用于从最新章节状态筛选当前位置附近活动实体"""
        minimum_chunk = max(0, current_chunk - lookback)
        return [
            ActiveEntityContext(
                name=entity.name,
                entity_id=entity.entity_id,
                role=str(entity.state.get("role_function") or "") or None,
                entity_type=entity.entity_type,
                status=str(entity.state.get("status") or "active"),
                last_seen_chunk=entity.last_seen_chunk,
                recent_action=str(entity.state.get("action") or "") or None,
                recent_emotion=str(entity.state.get("emotion") or "") or None,
            )
            for entity in self._graph_repo.fetch_latest_entities(run_id)
            if minimum_chunk <= entity.last_seen_chunk <= current_chunk
        ]

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
        return ExportGraphAuthorityView(
            canonical_entities=self._build_canonical_entities(entities),
            current_relations=self._build_export_relation_snapshots(current_relations),
            graph_changes=self._build_graph_changes(changes),
        )

    def build_graph_view(self, run_id: str) -> GraphAuthorityView:
        """2026-08-07 用于提供最新章节图与完整关系版本变化"""
        self.assert_graph_ready(run_id)
        entities = self._graph_repo.fetch_latest_entities(run_id)
        relations = self._graph_repo.fetch_latest_relations(run_id, active_only=True)
        changes, _total = self._graph_repo.fetch_changes(run_id, limit=None)
        return GraphAuthorityView(
            canonical_entities=self._build_canonical_entities(entities),
            confirmed_relations=self._build_confirmed_relations(relations),
            graph_changes=self._build_graph_changes(changes),
            participant_states=self._build_participant_states(entities),
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
            entity_id
            for relation in relations
            for entity_id in (relation.from_entity_id, relation.to_entity_id)
        }
        entities = [
            entity
            for entity in self._graph_repo.fetch_latest_entities(run_id)
            if entity.entity_id in endpoint_ids
        ]
        changes, _total = self._graph_repo.fetch_changes(run_id, limit=None)
        graph_changes = [
            change
            for change in changes
            if change.change_kind != "relation"
            or change.relation_semantics != "same_character"
        ]
        return GraphAuthorityView(
            canonical_entities=self._build_canonical_entities(entities),
            confirmed_relations=self._build_confirmed_relations(relations),
            graph_changes=self._build_graph_changes(graph_changes),
            participant_states=self._build_participant_states(entities),
        )

    def assert_graph_ready(self, run_id: str) -> None:
        """2026-08-07 用于确认当前 run 至少存在一个成功章节图版本"""
        if self._graph_repo.resolve_graph_version(run_id) is None:
            raise ValueError(f"run 尚无已完成章节图版本: {run_id}")

    def _build_canonical_entities(self, entities: Iterable[EntitySnapshotRow]) -> list[CanonicalEntity]:
        """2026-08-07 用于把实体状态快照转换为规范实体合同"""
        return [
            CanonicalEntity(
                name=entity.name,
                entity_type=entity.entity_type,
                entity_id=entity.entity_id,
                first_seen_chunk=entity.first_seen_chunk,
                last_seen_chunk=entity.last_seen_chunk,
                primary_role_function=str(entity.state.get("role_function") or "") or None,
                status=str(entity.state.get("status") or "active"),
                source_confidence=None,
            )
            for entity in sorted(entities, key=lambda row: row.name)
            if is_global_character_surface_name(entity.name)
        ]

    def _build_confirmed_relations(
        self,
        relations: Iterable[RelationSnapshotRow],
    ) -> list[ConfirmedRelation]:
        """2026-08-07 用于把稳定关系最新版本转换为当前关系合同"""
        return [
            ConfirmedRelation(
                from_name=relation.from_name,
                to_name=relation.to_name,
                relation_type=relation.relation_type,
                from_entity_id=relation.from_entity_id,
                to_entity_id=relation.to_entity_id,
                is_active=relation.is_active,
                first_seen_chunk=relation.first_seen_chunk,
                last_seen_chunk=relation.last_seen_chunk,
                change_count=len(relation.changes),
                support_count=int(relation.attributes.get("support_count", 1)),
                latest_relation_version_id=relation.relation_version_id,
                tension_index=float(relation.attributes.get("tension_index", 0.0)),
            )
            for relation in sorted(
                relations,
                key=lambda row: (row.from_name, row.to_name, row.relation_type),
            )
        ]

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
                first_seen_chunk=relation.first_seen_chunk,
                last_seen_chunk=relation.last_seen_chunk,
                relation_version_id=relation.relation_version_id,
                is_active=relation.is_active,
            )
            for relation in relations
        ]

    def _build_graph_changes(
        self,
        rows: Iterable[GraphChangeRow],
    ) -> list[GraphChange]:
        """2026-08-07 用于把 Repository 章节变化转换为共享双源 Evidence 合同"""
        return [
            GraphChange(
                change_id=row.change_id,
                change_kind=row.change_kind,
                graph_version_id=row.graph_version_id,
                chapter_id=row.chapter_id,
                chapter_order=row.chapter_order,
                fact_id=row.fact_id,
                fact_revision=row.fact_revision,
                effective_chunk_id=row.effective_chunk_id,
                confidence=row.confidence,
                changes=list(row.changes),
                evidence=row.evidence.model_dump(mode="json"),
                entity_id=row.entity_id,
                entity_name=row.entity_name,
                entity_type=row.entity_type,
                relation_id=row.relation_id,
                relation_version_id=row.relation_version_id,
                relation_revision=row.relation_revision,
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
    ) -> list[ParticipantState]:
        """2026-08-07 用于把实体状态快照转换为图参与者合同"""
        return [
            ParticipantState(
                entity_id=entity.entity_id,
                name=entity.name,
                entity_type=entity.entity_type,
                status=str(entity.state.get("status") or "active"),
                primary_role_function=str(entity.state.get("role_function") or "") or None,
                first_seen_chunk=entity.first_seen_chunk,
                last_seen_chunk=entity.last_seen_chunk,
                source_confidence=None,
                is_representative=True,
            )
            for entity in entities
            if is_global_character_surface_name(entity.name)
        ]
