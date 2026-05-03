from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.api.exceptions import GraphReadinessError
from src.models.local.character_reference_policy import is_global_character_surface_name
from src.storage.repositories import AnnotationRepository, GraphRepository
from src.storage.repositories.graph import ActiveEntityRow, CurrentRelationRow, ParticipantEntityRow, RelationEventRow

from .graph_outputs import build_graph_quality_report, build_graph_shared_summary
from .types import (
    ActiveEntityContext,
    AliasMapping,
    CanonicalEntity,
    ConfirmedRelation,
    EntityLifecycle,
    EntityTypeFact,
    ExportGraphAuthorityView,
    ExportRelationSnapshot,
    GraphAuthorityReport,
    GraphAuthorityView,
    Level1AuthoritySnapshot,
    ParticipantState,
    RelationEvent,
    TimelineAuthorityView,
)

BENIGN_GRAPH_PROJECTION_ERRORS = frozenset({"self relation", "unresolved reference endpoint"})


class KnowledgeGraphAuthorityService:
    """Single authority facade for graph consumers outside the repository layer"""

    def __init__(self, graph_repo: GraphRepository, annotation_repo: AnnotationRepository | None = None) -> None:
        self._graph_repo = graph_repo
        self._annotation_repo = annotation_repo or AnnotationRepository(graph_repo.session)

    @classmethod
    def from_session(cls, session: Any) -> KnowledgeGraphAuthorityService:
        return cls(graph_repo=GraphRepository(session), annotation_repo=AnnotationRepository(session))

    def build_level1_snapshot(self, run_id: str) -> Level1AuthoritySnapshot:
        """Level 1 stays intentionally minimal for evidence consumers"""

        entities = self._graph_repo.fetch_entities(run_id)
        return Level1AuthoritySnapshot(
            alias_mappings=self._build_alias_mappings(self._graph_repo.fetch_alias_map(run_id)),
            canonical_entities=self._build_canonical_entities(entities),
            confirmed_relations=self._build_confirmed_relations(
                self._graph_repo.fetch_current_relations(run_id, active_only=True)
            ),
            entity_types=self._build_entity_type_facts(entities),
        )

    def build_timeline_view(self, run_id: str) -> TimelineAuthorityView:
        """
        Build the shared contract consumed by timeline-style downstreams

        The timeline contract intentionally exposes only the character subgraph:
        non-character entities never appear in ``character_entities`` or
        ``entity_lifecycles``, and relation history is filtered so both
        endpoints must belong to that same character set
        """

        self.assert_graph_projection_ready(run_id)
        participant_entities = self._graph_repo.fetch_participant_entities(run_id)
        self._assert_participant_projection_consistency(
            run_id,
            relation_events=[],
            confirmed_relations=[],
            participant_entities=participant_entities,
            relation_endpoint_ids=self._graph_repo.fetch_relation_endpoint_entity_ids(run_id),
        )
        character_entities = self._build_canonical_entities(
            self._graph_repo.fetch_entities(run_id, entity_type="character")
        )
        character_ids = {entity.entity_id for entity in character_entities if entity.entity_id is not None}

        # Freeze the shared timeline contract at the "character subgraph" boundary
        # Downstream consumers should never need to inspect repository rows to
        # figure out whether an organization/group edge belongs on the timeline
        relation_events = [
            event
            for event in self._build_relation_events(self._graph_repo.fetch_relation_events(run_id))
            if event.from_entity_id in character_ids and event.to_entity_id in character_ids
        ]

        return TimelineAuthorityView(
            character_entities=character_entities,
            entity_lifecycles=self._build_entity_lifecycles(character_entities),
            relation_events=relation_events,
        )

    def build_active_entity_view(
        self,
        run_id: str,
        current_chunk: int,
        lookback: int = 10,
    ) -> list[ActiveEntityContext]:
        """Evidence consumers use a stable Level 2 view instead of raw repo rows"""

        rows = self._graph_repo.fetch_active_entities(current_chunk, lookback, run_id)
        return self._build_active_entity_contexts(rows)

    def build_graph_report(self, run_id: str) -> GraphAuthorityReport:
        """
        Build aggregate graph signals for non-product consumers

        Export/diagnosis can reuse these counters as graph-owned inputs, but
        they should still assemble their own higher-level conclusions instead
        of treating this report as the final diagnosis layer
        """

        self.assert_graph_projection_ready(run_id)
        participant_entities = self._graph_repo.fetch_participant_entities(run_id)
        confirmed_relations = self._build_confirmed_relations(
            self._graph_repo.fetch_current_relations(run_id, active_only=True)
        )
        relation_events = self._build_relation_events(self._graph_repo.fetch_relation_events(run_id))
        self._assert_participant_projection_consistency(
            run_id,
            relation_events,
            confirmed_relations,
            participant_entities,
        )
        participant_states = self._build_participant_states(participant_entities)
        return self._assemble_graph_report(participant_states, confirmed_relations, relation_events)

    def build_export_view(self, run_id: str) -> ExportGraphAuthorityView:
        """Return the authority surface used by graph-derived export payloads"""
        self.assert_graph_projection_ready(run_id)
        relation_events = self._build_relation_events(self._graph_repo.fetch_relation_events(run_id))
        participant_entities = self._graph_repo.fetch_participant_entities(run_id)
        self._assert_participant_projection_consistency(
            run_id,
            relation_events=relation_events,
            confirmed_relations=[],
            participant_entities=participant_entities,
            relation_endpoint_ids=self._graph_repo.fetch_relation_endpoint_entity_ids(run_id),
        )
        entities = self._graph_repo.fetch_entities(run_id)
        # export 仍保留部分历史 DTO，这里统一把“当前关系快照 + 关系事件历史”
        # 以及“允许导出的规范实体集合”一起收口成 authority view，避免导出层再直接
        # 依赖 repository/raw projection 做二次过滤
        return ExportGraphAuthorityView(
            canonical_entities=self._build_canonical_entities(entities),
            current_relations=self._build_export_relation_snapshots(
                self._graph_repo.fetch_current_relations(run_id, active_only=False)
            ),
            relation_events=relation_events,
        )

    def build_graph_view(self, run_id: str) -> GraphAuthorityView:
        """Return graph authority facts with full relation history for downstream product assembly"""

        self.assert_graph_projection_ready(run_id)
        participant_entities = self._graph_repo.fetch_participant_entities(run_id)
        confirmed_relations = self._build_confirmed_relations(
            self._graph_repo.fetch_current_relations(run_id, active_only=True)
        )
        relation_events = self._build_relation_events(self._graph_repo.fetch_relation_events(run_id))
        self._assert_participant_projection_consistency(
            run_id, relation_events, confirmed_relations, participant_entities
        )
        participant_states = self._build_participant_states(participant_entities)
        return GraphAuthorityView(
            canonical_entities=self._build_canonical_entities(participant_entities),
            confirmed_relations=confirmed_relations,
            relation_events=relation_events,
            participant_states=participant_states,
        )

    def build_graph_relation_event_page(
        self,
        run_id: str,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[RelationEvent], int]:
        """
        Return one relation-history page plus the full event count

        graph page 的 load-more 只需要"稳定排序后的事件分页 + 总数"，
        不应该每次都重建完整 GraphAuthorityView 再在内存里切片
        """

        self.assert_graph_projection_ready(run_id)
        participant_entities = self._graph_repo.fetch_participant_entities(run_id)
        self._assert_participant_projection_consistency(
            run_id,
            relation_events=[],
            confirmed_relations=[],
            participant_entities=participant_entities,
            relation_endpoint_ids=self._graph_repo.fetch_relation_endpoint_entity_ids(run_id),
        )
        total = self._graph_repo.count_relation_events(run_id)
        relation_events = self._build_relation_events(
            self._graph_repo.fetch_relation_events(run_id, limit=limit, offset=offset)
        )
        return relation_events, total

    def assert_graph_projection_ready(self, run_id: str) -> None:
        """
        2026-04-27，任务：graph readiness consistency fixes
        新建原因：graph-derived authority consumer 必须共用同一套 pending 判定，
        不能只让 `/graph` 路由做局部检查，否则 timeline / aggregate / export 会静默读取半投影图谱
        修改时间：2026-05-02
        修改原因：局部引用端点最终 unresolved 时属于“不可入图但可终态化”的 benign failed，
                  这里需要和 self relation 一起放行，避免 authority 继续被无意义的 failed 行卡死。
        """
        pending_relations = self._annotation_repo.fetch_pending_chunk_relations(run_id, limit=1)
        if pending_relations:
            raise GraphReadinessError(
                "graph projection is still pending; finish projection before reading graph-derived authority views."
            )
        failed_relations = self._annotation_repo.fetch_chunk_relations_window(run_id, projection_status="failed")
        blocking_failures = [
            relation
            for relation in failed_relations
            if getattr(relation, "projection_error", None) not in BENIGN_GRAPH_PROJECTION_ERRORS
        ]
        if blocking_failures:
            raise GraphReadinessError(
                "graph projection has failed rows; "
                "resolve projection failures before reading graph-derived authority views."
            )

    def _build_alias_mappings(self, alias_map: dict[str, str]) -> list[AliasMapping]:
        return [
            AliasMapping(alias=alias, canonical=canonical)
            for alias, canonical in sorted(alias_map.items(), key=lambda item: (item[1], item[0]))
        ]

    def _build_canonical_entities(self, entities: Iterable[Any]) -> list[CanonicalEntity]:
        """
        修改时间: 2026-04-29
        任务: 角色引用分层重构
        修改原因: authority view 最后一层防御过滤未解析代词节点，兼容旧图谱残留和测试替身数据。
        """
        canonical_entities: list[CanonicalEntity] = []
        for entity in sorted(entities, key=lambda row: getattr(row, "canonical_name", getattr(row, "name", ""))):
            canonical_name = getattr(entity, "canonical_name", getattr(entity, "name", ""))
            if not is_global_character_surface_name(canonical_name):
                continue
            canonical_entities.append(
                CanonicalEntity(
                    name=canonical_name,
                    entity_type=entity.entity_type or "character",
                    entity_id=entity.entity_id,
                    first_seen_chunk=entity.first_seen_chunk,
                    last_seen_chunk=entity.last_seen_chunk,
                    primary_role_function=entity.primary_role_function,
                    status=entity.status or "active",
                    source_confidence=entity.source_confidence,
                )
            )
        return canonical_entities

    def _build_confirmed_relations(self, relations: Iterable[CurrentRelationRow]) -> list[ConfirmedRelation]:
        confirmed_relations: list[ConfirmedRelation] = []
        for relation in sorted(
            relations,
            key=lambda row: (str(row.from_name), str(row.to_name), str(row.relation_type)),
        ):
            confirmed_relations.append(
                ConfirmedRelation(
                    from_name=str(relation.from_name),
                    to_name=str(relation.to_name),
                    relation_type=str(relation.relation_type),
                    from_entity_id=relation.from_entity_id,
                    to_entity_id=relation.to_entity_id,
                    is_active=bool(relation.is_active),
                    first_seen_chunk=relation.first_seen_chunk,
                    last_seen_chunk=relation.last_seen_chunk,
                    change_count=relation.change_count,
                    support_count=relation.support_count,
                    latest_event_id=relation.latest_event_id,
                    tension_index=relation.tension_index,
                )
            )
        return confirmed_relations

    def _build_export_relation_snapshots(self, relations: Iterable[CurrentRelationRow]) -> list[ExportRelationSnapshot]:
        export_relations: list[ExportRelationSnapshot] = []
        for relation in sorted(
            relations,
            key=lambda row: (str(row.from_name), str(row.to_name), str(row.relation_type)),
        ):
            export_relations.append(
                ExportRelationSnapshot(
                    relation_id=relation.relation_id,
                    from_name=str(relation.from_name),
                    to_name=str(relation.to_name),
                    relation_type=str(relation.relation_type),
                    first_seen_chunk=relation.first_seen_chunk,
                    last_seen_chunk=relation.last_seen_chunk,
                    latest_event_id=relation.latest_event_id,
                    is_active=bool(relation.is_active),
                )
            )
        return export_relations

    def _build_relation_events(self, events: Iterable[RelationEventRow]) -> list[RelationEvent]:
        relation_events: list[RelationEvent] = []
        for event in events:
            relation_events.append(
                RelationEvent(
                    relation_event_id=int(event.relation_event_id),
                    chunk_id=int(event.chunk_id),
                    from_entity_id=int(event.from_entity_id),
                    to_entity_id=int(event.to_entity_id),
                    from_name=str(event.from_name),
                    to_name=str(event.to_name),
                    relation_type=str(event.relation_type),
                    change_type=str(event.change_type),
                    evidence=str(event.evidence) if event.evidence is not None else None,
                    confidence=float(event.confidence) if event.confidence is not None else None,
                    directionality=str(event.directionality) if event.directionality is not None else None,
                    source_relation_row_id=int(event.source_relation_row_id)
                    if event.source_relation_row_id is not None
                    else None,
                )
            )
        return relation_events

    def _build_entity_type_facts(self, entities: Iterable[Any]) -> list[EntityTypeFact]:
        return [
            EntityTypeFact(name=entity.canonical_name, entity_type=entity.entity_type or "character")
            for entity in sorted(entities, key=lambda row: row.canonical_name)
        ]

    def _build_entity_lifecycles(self, entities: Iterable[CanonicalEntity]) -> list[EntityLifecycle]:
        lifecycles: list[EntityLifecycle] = []
        for entity in entities:
            if entity.entity_id is None:
                continue
            lifecycles.append(
                EntityLifecycle(
                    entity_id=entity.entity_id,
                    name=entity.name,
                    entity_type=entity.entity_type,
                    first_seen_chunk=entity.first_seen_chunk,
                    last_seen_chunk=entity.last_seen_chunk,
                    status=entity.status,
                )
            )
        return lifecycles

    def _build_active_entity_contexts(self, rows: Iterable[ActiveEntityRow]) -> list[ActiveEntityContext]:
        """
        修改时间: 2026-04-29
        任务: 角色引用分层重构
        修改原因: active entity prompt view 不能继续暴露“我”等未解析局部引用节点。
        """
        active_entities: list[ActiveEntityContext] = []
        for row in rows:
            if not is_global_character_surface_name(row.name):
                continue
            # Normalize repository row keys into an authority-owned Level 2 contract
            active_entities.append(
                ActiveEntityContext(
                    name=str(row.name),
                    entity_id=int(row.entity_id) if row.entity_id is not None else None,
                    role=str(row.role) if row.role is not None else None,
                    # Preserve repository-backed authority fields when present
                    entity_type=str(row.entity_type) if row.entity_type is not None else "character",
                    status=str(row.status) if row.status is not None else "active",
                    last_seen_chunk=int(row.chunk_id) if row.chunk_id is not None else None,
                    recent_action=str(row.last_action) if row.last_action else None,
                    recent_emotion=str(row.last_emotion) if row.last_emotion else None,
                )
            )
        return active_entities

    def _build_participant_states(self, participants: Iterable[ParticipantEntityRow]) -> list[ParticipantState]:
        """
        修改时间: 2026-04-29
        任务: 角色引用分层重构
        修改原因: 图谱 authority 的参与者集合只允许 global-character 准入后的节点。
        """
        participant_states: list[ParticipantState] = []
        for participant in sorted(participants, key=lambda row: row.name):
            if not is_global_character_surface_name(participant.name):
                continue
            participant_states.append(
                ParticipantState(
                    entity_id=participant.entity_id,
                    name=participant.name,
                    entity_type=participant.entity_type or "character",
                    status=participant.status or "active",
                    primary_role_function=participant.primary_role_function,
                    first_seen_chunk=participant.first_seen_chunk,
                    last_seen_chunk=participant.last_seen_chunk,
                    source_confidence=participant.source_confidence,
                )
            )
        return participant_states

    def _assert_participant_projection_consistency(
        self,
        run_id: str,
        relation_events: list[RelationEvent],
        confirmed_relations: list[ConfirmedRelation],
        participant_entities: list[ParticipantEntityRow],
        relation_endpoint_ids: set[int] | None = None,
    ) -> None:
        """
        2026-04-26，任务：图谱参与者层落地
        新建原因：旧 run 若只有关系表、却缺少参与者投影，必须显式失败并要求重跑，不能静默回退到全量人物
        """
        participant_entity_ids = {participant.entity_id for participant in participant_entities}
        expected_participant_ids = relation_endpoint_ids or self._collect_relation_endpoint_ids(
            relation_events,
            confirmed_relations,
        )

        if not expected_participant_ids:
            if participant_entity_ids:
                raise GraphReadinessError(
                    "graph participant projection is stale while graph relation tables are empty; "
                    f"re-run analysis for run_id={run_id} to rebuild graph_entity_participants."
                )
            return

        missing_entity_ids = expected_participant_ids - participant_entity_ids
        stale_entity_ids = participant_entity_ids - expected_participant_ids
        if missing_entity_ids or stale_entity_ids:
            raise GraphReadinessError(
                "graph participant projection is stale or incomplete for the current relation graph; "
                f"re-run analysis for run_id={run_id} to rebuild graph_entity_participants."
            )

    def _collect_relation_endpoint_ids(
        self,
        relation_events: Iterable[RelationEvent],
        confirmed_relations: Iterable[ConfirmedRelation],
    ) -> set[int]:
        endpoint_ids = {
            relation_event.from_entity_id
            for relation_event in relation_events
            if relation_event.from_entity_id is not None
        } | {
            relation_event.to_entity_id
            for relation_event in relation_events
            if relation_event.to_entity_id is not None
        }
        endpoint_ids |= {
            relation.from_entity_id
            for relation in confirmed_relations
            if relation.from_entity_id is not None
        }
        endpoint_ids |= {
            relation.to_entity_id
            for relation in confirmed_relations
            if relation.to_entity_id is not None
        }
        return endpoint_ids

    def _assemble_graph_report(
        self,
        participant_states: list[ParticipantState],
        confirmed_relations: list[ConfirmedRelation],
        relation_events: list[RelationEvent],
    ) -> GraphAuthorityReport:
        return GraphAuthorityReport(
            summary=build_graph_shared_summary(participant_states, confirmed_relations),
            quality=build_graph_quality_report(confirmed_relations, relation_events),
        )
