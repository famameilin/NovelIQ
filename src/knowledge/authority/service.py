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


class KnowledgeGraphAuthorityService:
    """面向 repository 层外图谱消费者的统一 authority 门面"""

    def __init__(self, graph_repo: GraphRepository, annotation_repo: AnnotationRepository | None = None) -> None:
        self._graph_repo = graph_repo
        self._annotation_repo = annotation_repo or AnnotationRepository(graph_repo.session)

    @classmethod
    def from_session(cls, session: Any) -> KnowledgeGraphAuthorityService:
        return cls(graph_repo=GraphRepository(session), annotation_repo=AnnotationRepository(session))

    def build_level1_snapshot(self, run_id: str) -> Level1AuthoritySnapshot:
        """Level 1 对证据消费者刻意保持最小边界"""

        entities = self._graph_repo.fetch_representative_entities(run_id)
        return Level1AuthoritySnapshot(
            canonical_entities=self._build_canonical_entities(entities),
            confirmed_relations=self._build_confirmed_relations(
                self._graph_repo.fetch_representative_current_relations(run_id, active_only=True)
            ),
            entity_types=self._build_entity_type_facts(entities),
        )

    def build_timeline_view(self, run_id: str) -> TimelineAuthorityView:
        """
        构建供时间轴类下游复用的共享合同

        时间轴合同刻意只暴露角色子图：
        非角色实体不会出现在 `character_entities` 或 `entity_lifecycles` 中，
        关系历史也会被过滤，保证两端都属于同一批角色集合
        """

        self.assert_graph_ready(run_id)
        participant_entities = self._graph_repo.fetch_participant_entities(run_id)
        self._assert_participant_graph_consistency(
            run_id,
            relation_events=[],
            confirmed_relations=[],
            participant_entities=participant_entities,
            relation_endpoint_ids=self._graph_repo.fetch_relation_endpoint_entity_ids(run_id),
        )
        character_entities = self._build_canonical_entities(
            self._graph_repo.fetch_representative_entities(run_id, entity_type="character")
        )
        character_ids = {entity.entity_id for entity in character_entities if entity.entity_id is not None}

        # 把共享时间轴合同固定在“角色子图”边界，
        # 下游消费者不应再去检查 repository 原始行，
        # 判断组织/群体边是否该出现在时间轴上
        relation_events = [
            event
            for event in self._build_relation_events(
                self._graph_repo.fetch_representative_relation_events(run_id)
            )
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
        """证据消费者使用稳定的 Level 2 视图，而不是直接吃原始 repo 行"""

        rows = self._graph_repo.fetch_active_entities(current_chunk, lookback, run_id)
        return self._build_active_entity_contexts(rows)

    def build_graph_report(self, run_id: str) -> GraphAuthorityReport:
        """
        为非产品层消费者构建聚合图谱信号

        export / diagnosis 可以复用这些计数器作为图谱侧输入，
        但它们仍应自行组装更高层结论，
        不能把这个 report 直接当成最终 diagnosis 层
        """

        representative_view = self.build_representative_graph_view(run_id)
        return self._assemble_graph_report(
            representative_view.participant_states,
            representative_view.confirmed_relations,
            representative_view.relation_events,
        )

    def build_export_view(self, run_id: str) -> ExportGraphAuthorityView:
        """返回图谱导出 payload 使用的 authority 视图"""
        self.assert_graph_ready(run_id)
        relation_events = self._build_relation_events(
            self._graph_repo.fetch_representative_relation_events(run_id)
        )
        participant_entities = self._graph_repo.fetch_participant_entities(run_id)
        self._assert_participant_graph_consistency(
            run_id,
            relation_events=relation_events,
            confirmed_relations=[],
            participant_entities=participant_entities,
            relation_endpoint_ids=self._graph_repo.fetch_relation_endpoint_entity_ids(run_id),
        )
        entities = self._graph_repo.fetch_representative_entities(run_id)
        # export 仍保留部分历史 DTO，这里统一把“当前关系快照 + 关系事件历史”
        # 以及“允许导出的规范实体集合”一起收口成 authority view，避免导出层再直接
        # 依赖 repository 原始行做二次过滤
        return ExportGraphAuthorityView(
            canonical_entities=self._build_canonical_entities(entities),
            current_relations=self._build_export_relation_snapshots(
                self._graph_repo.fetch_representative_current_relations(run_id, active_only=False)
            ),
            relation_events=relation_events,
        )

    def build_graph_view(self, run_id: str) -> GraphAuthorityView:
        """返回带完整关系历史的图谱 authority 事实，供下游产品层组装"""

        self.assert_graph_ready(run_id)
        participant_entities = self._graph_repo.fetch_participant_entities(run_id)
        confirmed_relations = self._build_confirmed_relations(
            self._graph_repo.fetch_current_relations(run_id, active_only=True)
        )
        relation_events = self._build_relation_events(self._graph_repo.fetch_relation_events(run_id))
        self._assert_participant_graph_consistency(
            run_id, relation_events, confirmed_relations, participant_entities
        )
        participant_states = self._build_participant_states(participant_entities)
        return GraphAuthorityView(
            canonical_entities=self._build_canonical_entities(participant_entities),
            confirmed_relations=confirmed_relations,
            relation_events=relation_events,
            participant_states=participant_states,
        )

    def build_representative_graph_view(self, run_id: str) -> GraphAuthorityView:
        """2026-08-06 用于向诊断与聚合提供按常用人物节点收口的关系图"""
        self.assert_graph_ready(run_id)
        entities = self._graph_repo.fetch_representative_entities(run_id)
        relations = self._graph_repo.fetch_representative_current_relations(
            run_id,
            active_only=True,
        )
        events = self._graph_repo.fetch_representative_relation_events(run_id)
        endpoint_ids = {
            entity_id
            for relation in relations
            for entity_id in (relation.from_entity_id, relation.to_entity_id)
        } | {
            entity_id
            for event in events
            for entity_id in (event.from_entity_id, event.to_entity_id)
        }
        participant_entities = [
            entity
            for entity in entities
            if entity.entity_id in endpoint_ids
        ]
        return GraphAuthorityView(
            canonical_entities=self._build_canonical_entities(participant_entities),
            confirmed_relations=self._build_confirmed_relations(relations),
            relation_events=self._build_relation_events(events),
            participant_states=self._build_entity_participant_states(participant_entities),
        )

    def build_graph_relation_event_page(
        self,
        run_id: str,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[RelationEvent], int]:
        """
        返回一页关系历史事件以及总事件数

        graph page 的 load-more 只需要"稳定排序后的事件分页 + 总数"，
        不应该每次都重建完整 GraphAuthorityView 再在内存里切片
        """

        self.assert_graph_ready(run_id)
        participant_entities = self._graph_repo.fetch_participant_entities(run_id)
        self._assert_participant_graph_consistency(
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

    def assert_graph_ready(self, run_id: str) -> None:
        """2026-08-05 用于确认数据库图读侧可直接按最终事实查询"""
        del run_id

    def _build_canonical_entities(self, entities: Iterable[Any]) -> list[CanonicalEntity]:
        """
        修改时间: 2026-04-29
        任务: 角色引用分层重构
        修改原因: authority view 最后一层过滤未解析代词节点，确保数据库图只暴露全局实体
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
            # 把 repository 行键名归一化为 authority 自有的 Level 2 合同
            active_entities.append(
                ActiveEntityContext(
                    name=str(row.name),
                    entity_id=int(row.entity_id) if row.entity_id is not None else None,
                    role=str(row.role) if row.role is not None else None,
                    # 在字段存在时保留 repository 提供的 authority 字段
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
                    is_representative=participant.is_representative,
                )
            )
        return participant_states

    def _build_entity_participant_states(self, entities: Iterable[Any]) -> list[ParticipantState]:
        """2026-08-06 用于把常用实体节点转换为诊断与聚合关系参与者"""
        return [
            ParticipantState(
                entity_id=int(entity.entity_id),
                name=str(entity.canonical_name),
                entity_type=str(entity.entity_type or "character"),
                status=str(entity.status or "active"),
                primary_role_function=entity.primary_role_function,
                first_seen_chunk=entity.first_seen_chunk,
                last_seen_chunk=entity.last_seen_chunk,
                source_confidence=entity.source_confidence,
                is_representative=True,
            )
            for entity in sorted(entities, key=lambda row: row.canonical_name)
            if is_global_character_surface_name(entity.canonical_name)
        ]

    def _assert_participant_graph_consistency(
        self,
        run_id: str,
        relation_events: list[RelationEvent],
        confirmed_relations: list[ConfirmedRelation],
        participant_entities: list[ParticipantEntityRow],
        relation_endpoint_ids: set[int] | None = None,
    ) -> None:
        """
        2026-08-05 用于确认关系事实端点与参与者事实视图严格一致
        """
        participant_entity_ids = {participant.entity_id for participant in participant_entities}
        expected_participant_ids = relation_endpoint_ids or self._collect_relation_endpoint_ids(
            relation_events,
            confirmed_relations,
        )

        if not expected_participant_ids:
            if participant_entity_ids:
                raise GraphReadinessError(
                    "graph participant state is stale while graph relation tables are empty; "
                    f"re-run analysis for run_id={run_id} to rebuild graph_entity_participants."
                )
            return

        missing_entity_ids = expected_participant_ids - participant_entity_ids
        stale_entity_ids = participant_entity_ids - expected_participant_ids
        if missing_entity_ids or stale_entity_ids:
            raise GraphReadinessError(
                "graph participant state is stale or incomplete for the current relation graph; "
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
