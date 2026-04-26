from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from src.storage.models import (
    GraphEntity,
    GraphEntityAlias,
    GraphEntityParticipant,
    GraphRelationCurrent,
    GraphRelationEvent,
)
from src.storage.repositories.base import BaseRepository


@dataclass(frozen=True)
class ActiveEntityRow:
    """GraphRepository 活跃实体查询 DTO。

    创建时间: 2026-04-23
    任务: P0-graph-repository-dto-boundary
    说明: 替代 raw dict 返回值，让下游通过具名字段消费 graph repository 边界。
    """

    entity_id: int | None
    name: str
    role: str | None
    entity_type: str
    status: str
    last_action: str
    last_emotion: str
    emotion_score: str | None
    chunk_id: int | None


@dataclass(frozen=True)
class CurrentRelationRow:
    """GraphRepository 当前关系查询 DTO。

    创建时间: 2026-04-23
    任务: P0-graph-repository-dto-boundary
    说明: 明确当前关系快照的字段集合，避免下游依赖 dict[str, Any] 形状。
    """

    relation_id: int | None
    from_entity_id: int
    to_entity_id: int
    from_name: str
    to_name: str
    relation_type: str
    first_seen_chunk: int | None
    last_seen_chunk: int | None
    change_count: int
    support_count: int
    latest_event_id: int | None
    tension_index: float | None
    is_active: bool


@dataclass(frozen=True)
class RelationEventRow:
    """GraphRepository 关系事件查询 DTO。

    创建时间: 2026-04-23
    任务: P0-graph-repository-dto-boundary
    说明: 让关系事件历史以具名字段跨 repository 边界传递。
    """

    relation_event_id: int
    chunk_id: int
    from_entity_id: int
    to_entity_id: int
    from_name: str
    to_name: str
    relation_type: str
    change_type: str
    evidence: str | None
    confidence: float | None
    source_relation_row_id: int | None
    directionality: str | None


@dataclass(frozen=True)
class LowConfidenceRelationEventRow:
    """GraphRepository 低置信度关系事件 DTO。"""

    relation_event_id: int
    chunk_id: int
    from_entity_id: int
    to_entity_id: int
    from_name: str
    to_name: str
    relation_type: str
    change_type: str
    evidence: str | None
    confidence: float | None
    source_relation_row_id: int | None
    directionality: str | None


@dataclass(frozen=True)
class RelationConflictRow:
    """GraphRepository 关系冲突 DTO。"""

    entity_pair: tuple[int, int]
    entity_names: list[str]
    relation_types: list[str]
    relation_count: int
    relation_ids: list[int | None]


@dataclass(frozen=True)
class ParticipantEntityRow:
    """GraphRepository 图谱参与者查询 DTO。"""

    entity_id: int
    name: str
    entity_type: str
    status: str
    primary_role_function: str | None
    first_seen_chunk: int | None
    last_seen_chunk: int | None
    source_confidence: float | None
    relation_event_count: int
    current_degree: int
    historical_degree: int
    first_relation_chunk: int | None
    last_relation_chunk: int | None
    latest_relation_event_id: int | None


class GraphRepository(BaseRepository["GraphRepository"]):
    def reset_graph_tables(self, run_id: str) -> None:
        """
        清空指定 run 的 graph_* 权威表数据。

        用于在别名归一化规则发生显著变化后执行全量重建，避免旧投影残留。
        """
        self.session.execute(delete(GraphEntityParticipant).where(GraphEntityParticipant.run_id == run_id))
        self.session.execute(delete(GraphRelationCurrent).where(GraphRelationCurrent.run_id == run_id))
        self.session.execute(delete(GraphRelationEvent).where(GraphRelationEvent.run_id == run_id))
        self.session.execute(delete(GraphEntityAlias).where(GraphEntityAlias.run_id == run_id))
        self.session.execute(delete(GraphEntity).where(GraphEntity.run_id == run_id))
        self.session.flush()

    def get_entity_by_canonical(self, run_id: str, canonical_name: str) -> GraphEntity | None:
        stmt = select(GraphEntity).where(
            GraphEntity.run_id == run_id,
            GraphEntity.canonical_name == canonical_name,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert_entity(
        self,
        run_id: str,
        canonical_name: str,
        entity_type: str = "character",
        first_seen_chunk: int | None = None,
        last_seen_chunk: int | None = None,
        primary_role_function: str | None = None,
        last_emotion_score: str | None = None,
        last_action: str | None = None,
        source_confidence: float | None = None,
        status: str | None = None,
    ) -> GraphEntity:
        entity = self.get_entity_by_canonical(run_id, canonical_name)
        if entity is None:
            entity = GraphEntity(
                run_id=run_id,
                canonical_name=canonical_name,
                entity_type=entity_type,
                first_seen_chunk=first_seen_chunk,
                last_seen_chunk=last_seen_chunk,
                primary_role_function=primary_role_function,
                last_emotion_score=last_emotion_score,
                last_action=last_action,
                source_confidence=source_confidence,
                status=status or "active",
            )
            self.session.add(entity)
            self.session.flush()
            return entity

        if first_seen_chunk is not None:
            entity.first_seen_chunk = min(entity.first_seen_chunk or first_seen_chunk, first_seen_chunk)
        if last_seen_chunk is not None:
            entity.last_seen_chunk = max(entity.last_seen_chunk or last_seen_chunk, last_seen_chunk)
        # Update entity_type if the new value differs and is not the generic default
        if entity_type and entity_type != "character" and entity.entity_type != entity_type:
            from loguru import logger

            logger.info(
                "Updating entity_type for '{}': {} -> {}",
                canonical_name,
                entity.entity_type,
                entity_type,
            )
            entity.entity_type = entity_type
        if primary_role_function is not None:
            entity.primary_role_function = primary_role_function
        if last_emotion_score is not None:
            entity.last_emotion_score = last_emotion_score
        if last_action is not None:
            entity.last_action = last_action
        if source_confidence is not None:
            entity.source_confidence = source_confidence
        if status is not None:
            entity.status = status
        entity.updated_at = datetime.now(UTC)
        self.session.flush()
        return entity

    def upsert_alias(
        self,
        run_id: str,
        entity_id: int,
        alias: str,
        source_chunk_id: int | None,
        evidence: str | None,
        confidence: float | None,
        source_type: str,
        is_primary: bool = False,
    ) -> None:
        stmt = (
            insert(GraphEntityAlias)
            .values(
                run_id=run_id,
                entity_id=entity_id,
                alias=alias,
                source_chunk_id=source_chunk_id,
                evidence=evidence,
                confidence=confidence,
                source_type=source_type,
                is_primary=is_primary,
            )
            .on_conflict_do_update(
                constraint="uq_graph_entity_aliases_entity_alias",
                set_={
                    "source_chunk_id": source_chunk_id,
                    "evidence": evidence,
                    "confidence": confidence,
                    "source_type": source_type,
                    "is_primary": is_primary,
                },
            )
        )
        self.session.execute(stmt)

    def insert_relation_event(
        self,
        run_id: str,
        from_entity_id: int,
        to_entity_id: int,
        relation_type: str,
        change_type: str,
        chunk_id: int,
        evidence: str | None,
        confidence: float | None,
        source_relation_row_id: int | None,
        directionality: str | None,
    ) -> GraphRelationEvent | None:
        stmt = (
            insert(GraphRelationEvent)
            .values(
                run_id=run_id,
                from_entity_id=from_entity_id,
                to_entity_id=to_entity_id,
                relation_type=relation_type,
                change_type=change_type,
                chunk_id=chunk_id,
                evidence=evidence,
                confidence=confidence,
                source_relation_row_id=source_relation_row_id,
                directionality=directionality,
            )
            .on_conflict_do_nothing(constraint="uq_graph_relation_events_source_row")
            .returning(GraphRelationEvent)
        )
        event = self.session.execute(stmt).scalar_one_or_none()
        if event:
            return event
        if source_relation_row_id is None:
            return None
        return self.session.execute(
            select(GraphRelationEvent).where(
                GraphRelationEvent.run_id == run_id,
                GraphRelationEvent.source_relation_row_id == source_relation_row_id,
            )
        ).scalar_one_or_none()

    def refresh_current_relation(self, run_id: str, from_entity_id: int, to_entity_id: int) -> None:
        events = list(
            self.session.execute(
                select(GraphRelationEvent)
                .where(
                    GraphRelationEvent.run_id == run_id,
                    GraphRelationEvent.from_entity_id == from_entity_id,
                    GraphRelationEvent.to_entity_id == to_entity_id,
                )
                .order_by(GraphRelationEvent.chunk_id, GraphRelationEvent.relation_event_id)
            )
            .scalars()
            .all()
        )
        if not events:
            return

        latest = events[-1]
        first = events[0]
        change_count = sum(1 for event in events if event.change_type and event.change_type != "无变化")
        tension_index = 0.0
        for event in events:
            if event.relation_type == "敌对":
                tension_index += event.confidence or 0.5
            elif event.relation_type in {"盟友", "友情"}:
                tension_index -= (event.confidence or 0.5) * 0.5

        existing = self.session.execute(
            select(GraphRelationCurrent).where(
                GraphRelationCurrent.run_id == run_id,
                GraphRelationCurrent.from_entity_id == from_entity_id,
                GraphRelationCurrent.to_entity_id == to_entity_id,
            )
        ).scalar_one_or_none()

        if existing is None:
            existing = GraphRelationCurrent(
                run_id=run_id,
                from_entity_id=from_entity_id,
                to_entity_id=to_entity_id,
                current_type=latest.relation_type,
                first_seen_chunk=first.chunk_id,
                last_seen_chunk=latest.chunk_id,
                change_count=change_count,
                support_count=len(events),
                latest_event_id=latest.relation_event_id,
                tension_index=tension_index,
                is_active=latest.change_type != "断裂",
            )
            self.session.add(existing)
        else:
            existing.current_type = latest.relation_type
            existing.first_seen_chunk = first.chunk_id
            existing.last_seen_chunk = latest.chunk_id
            existing.change_count = change_count
            existing.support_count = len(events)
            existing.latest_event_id = latest.relation_event_id
            existing.tension_index = tension_index
            existing.is_active = latest.change_type != "断裂"
            existing.updated_at = datetime.now(UTC)
        self.session.flush()

    def refresh_relation_projections(
        self,
        run_id: str,
        entity_pairs: Iterable[tuple[int, int]],
    ) -> None:
        """
        2026-04-27，任务：graph participant projection consistency fixes
        新建原因：关系写入后必须把 current relation 和 participant projection 一起刷新，
        避免调用方只补其中一层导致图谱节点与关系历史失配。
        """
        normalized_pairs = sorted(
            {
                (int(from_entity_id), int(to_entity_id))
                for from_entity_id, to_entity_id in entity_pairs
                if from_entity_id is not None and to_entity_id is not None
            }
        )
        if not normalized_pairs:
            return

        affected_entity_ids: set[int] = set()
        for from_entity_id, to_entity_id in normalized_pairs:
            self.refresh_current_relation(run_id, from_entity_id, to_entity_id)
            affected_entity_ids.add(from_entity_id)
            affected_entity_ids.add(to_entity_id)

        self.refresh_entity_participants(run_id, affected_entity_ids)

    def refresh_entity_participants(self, run_id: str, entity_ids: Iterable[int]) -> None:
        """
        2026-04-26，任务：图谱参与者层落地
        新建原因：图谱参与者表是最终人物图谱节点资格的持久投影，必须在关系投影后按受影响实体增量刷新。
        """
        normalized_entity_ids = sorted({int(entity_id) for entity_id in entity_ids if entity_id is not None})
        if not normalized_entity_ids:
            return

        for entity_id in normalized_entity_ids:
            event_rows = list(
                self.session.execute(
                    select(GraphRelationEvent)
                    .where(
                        GraphRelationEvent.run_id == run_id,
                        or_(
                            GraphRelationEvent.from_entity_id == entity_id,
                            GraphRelationEvent.to_entity_id == entity_id,
                        ),
                    )
                    .order_by(GraphRelationEvent.chunk_id.asc(), GraphRelationEvent.relation_event_id.asc())
                )
                .scalars()
                .all()
            )
            current_rows = list(
                self.session.execute(
                    select(GraphRelationCurrent)
                    .where(
                        GraphRelationCurrent.run_id == run_id,
                        GraphRelationCurrent.is_active.is_(True),
                        or_(
                            GraphRelationCurrent.from_entity_id == entity_id,
                            GraphRelationCurrent.to_entity_id == entity_id,
                        ),
                    )
                )
                .scalars()
                .all()
            )

            if not event_rows and not current_rows:
                self.session.execute(
                    delete(GraphEntityParticipant).where(
                        GraphEntityParticipant.run_id == run_id,
                        GraphEntityParticipant.entity_id == entity_id,
                    )
                )
                continue

            historical_counterpart_ids = {
                event.to_entity_id if event.from_entity_id == entity_id else event.from_entity_id
                for event in event_rows
            }
            current_counterpart_ids = {
                relation.to_entity_id if relation.from_entity_id == entity_id else relation.from_entity_id
                for relation in current_rows
            }
            first_relation_chunk = min(
                [event.chunk_id for event in event_rows]
                + [relation.first_seen_chunk for relation in current_rows if relation.first_seen_chunk is not None],
                default=None,
            )
            last_relation_chunk = max(
                [event.chunk_id for event in event_rows]
                + [relation.last_seen_chunk for relation in current_rows if relation.last_seen_chunk is not None],
                default=None,
            )
            latest_event_candidates = [event.relation_event_id for event in event_rows] + [
                relation.latest_event_id for relation in current_rows if relation.latest_event_id is not None
            ]
            latest_relation_event_id = max(latest_event_candidates, default=None)

            stmt = (
                insert(GraphEntityParticipant)
                .values(
                    run_id=run_id,
                    entity_id=entity_id,
                    relation_event_count=len(event_rows),
                    current_degree=len(current_counterpart_ids),
                    historical_degree=len(historical_counterpart_ids),
                    first_relation_chunk=first_relation_chunk,
                    last_relation_chunk=last_relation_chunk,
                    latest_relation_event_id=latest_relation_event_id,
                )
                .on_conflict_do_update(
                    constraint="uq_graph_entity_participants_run_entity",
                    set_={
                        "relation_event_count": len(event_rows),
                        "current_degree": len(current_counterpart_ids),
                        "historical_degree": len(historical_counterpart_ids),
                        "first_relation_chunk": first_relation_chunk,
                        "last_relation_chunk": last_relation_chunk,
                        "latest_relation_event_id": latest_relation_event_id,
                        "updated_at": datetime.now(UTC),
                    },
                )
            )
            self.session.execute(stmt)

        self.session.flush()

    def fetch_alias_map(self, run_id: str) -> dict[str, str]:
        rows = self.session.execute(
            select(GraphEntityAlias.alias, GraphEntity.canonical_name)
            .join(GraphEntity, GraphEntityAlias.entity_id == GraphEntity.entity_id)
            .where(GraphEntityAlias.run_id == run_id)
        ).fetchall()
        alias_pairs: list[tuple[str, str]] = [(row.alias, row.canonical_name) for row in rows]
        alias_map: dict[str, str] = dict(alias_pairs)
        for canonical in list(alias_map.values()):
            alias_map.setdefault(canonical, canonical)
        return alias_map

    def fetch_active_entities(
        self,
        current_chunk_id: int,
        lookback: int = 10,
        run_id: str | None = None,
    ) -> list[ActiveEntityRow]:
        """
        查询近期活跃实体。

        修改时间: 2026-04-23
        任务: P0-graph-repository-dto-boundary
        修改内容: 返回 ActiveEntityRow DTO，替代 raw dict[str, Any]。
        """
        if run_id is None:
            return []
        start_chunk = max(0, current_chunk_id - lookback)
        rows = (
            self.session.execute(
                select(GraphEntity)
                .where(
                    GraphEntity.run_id == run_id,
                    GraphEntity.last_seen_chunk.is_not(None),
                    GraphEntity.last_seen_chunk >= start_chunk,
                    GraphEntity.last_seen_chunk <= current_chunk_id,
                    GraphEntity.status == "active",
                )
                .order_by(GraphEntity.last_seen_chunk.desc(), GraphEntity.entity_id.asc())
            )
            .scalars()
            .all()
        )
        return [
            ActiveEntityRow(
                entity_id=row.entity_id,
                name=row.canonical_name,
                role=row.primary_role_function,
                entity_type=row.entity_type,
                status=row.status,
                last_action=row.last_action or "",
                last_emotion=row.last_emotion_score or "",
                emotion_score=row.last_emotion_score,
                chunk_id=row.last_seen_chunk,
            )
            for row in rows
        ]

    def fetch_current_relations(
        self,
        run_id: str,
        active_only: bool = True,
    ) -> list[CurrentRelationRow]:
        """
        查询当前关系快照。

        修改时间: 2026-04-23
        任务: P0-graph-repository-dto-boundary
        修改内容: 返回 CurrentRelationRow DTO，替代 raw dict[str, Any]。
        """
        stmt = select(GraphRelationCurrent).where(GraphRelationCurrent.run_id == run_id)
        if active_only:
            stmt = stmt.where(GraphRelationCurrent.is_active.is_(True))
        current_rows = self.session.execute(stmt).scalars().all()

        entity_names = {
            row.entity_id: row.canonical_name
            for row in self.session.execute(
                select(GraphEntity.entity_id, GraphEntity.canonical_name).where(GraphEntity.run_id == run_id)
            ).fetchall()
        }

        result: list[CurrentRelationRow] = []
        for current in current_rows:
            result.append(
                CurrentRelationRow(
                    relation_id=current.relation_id,
                    from_entity_id=current.from_entity_id,
                    to_entity_id=current.to_entity_id,
                    from_name=entity_names.get(current.from_entity_id, str(current.from_entity_id)),
                    to_name=entity_names.get(current.to_entity_id, str(current.to_entity_id)),
                    relation_type=current.current_type,
                    first_seen_chunk=current.first_seen_chunk,
                    last_seen_chunk=current.last_seen_chunk,
                    change_count=current.change_count,
                    support_count=current.support_count,
                    latest_event_id=current.latest_event_id,
                    tension_index=current.tension_index,
                    is_active=current.is_active,
                )
            )
        return result

    def count_current_relations(self, run_id: str, active_only: bool | None = None) -> int:
        """返回指定运行的当前关系总数。"""
        stmt = select(func.count()).select_from(GraphRelationCurrent).where(GraphRelationCurrent.run_id == run_id)
        if active_only is True:
            stmt = stmt.where(GraphRelationCurrent.is_active.is_(True))
        elif active_only is False:
            stmt = stmt.where(GraphRelationCurrent.is_active.is_(False))
        return int(self.session.execute(stmt).scalar() or 0)

    def count_entity_participants(self, run_id: str) -> int:
        """返回指定运行的图谱参与者总数。"""
        return int(
            self.session.execute(
                select(func.count()).select_from(GraphEntityParticipant).where(GraphEntityParticipant.run_id == run_id)
            ).scalar()
            or 0
        )

    def fetch_relation_endpoint_entity_ids(self, run_id: str) -> set[int]:
        """返回关系历史和当前关系中涉及到的全部实体 ID。"""
        event_ids = {
            int(entity_id)
            for entity_id in self.session.execute(
                select(GraphRelationEvent.from_entity_id).where(GraphRelationEvent.run_id == run_id)
            ).scalars()
            if entity_id is not None
        } | {
            int(entity_id)
            for entity_id in self.session.execute(
                select(GraphRelationEvent.to_entity_id).where(GraphRelationEvent.run_id == run_id)
            ).scalars()
            if entity_id is not None
        }
        current_ids = {
            int(entity_id)
            for entity_id in self.session.execute(
                select(GraphRelationCurrent.from_entity_id).where(GraphRelationCurrent.run_id == run_id)
            ).scalars()
            if entity_id is not None
        } | {
            int(entity_id)
            for entity_id in self.session.execute(
                select(GraphRelationCurrent.to_entity_id).where(GraphRelationCurrent.run_id == run_id)
            ).scalars()
            if entity_id is not None
        }
        return event_ids | current_ids

    def count_relation_events(self, run_id: str) -> int:
        """返回指定运行的关系事件总数。"""
        return int(
            self.session.execute(
                select(func.count()).select_from(GraphRelationEvent).where(GraphRelationEvent.run_id == run_id)
            ).scalar()
            or 0
        )

    def fetch_relation_events(
        self,
        run_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[RelationEventRow]:
        """
        查询关系事件历史。

        修改时间: 2026-04-23
        任务: P0-graph-repository-dto-boundary
        修改内容: 返回 RelationEventRow DTO，替代 raw dict[str, Any]。
        """
        entity_names = {
            row.entity_id: row.canonical_name
            for row in self.session.execute(
                select(GraphEntity.entity_id, GraphEntity.canonical_name).where(GraphEntity.run_id == run_id)
            ).fetchall()
        }
        stmt = (
            select(GraphRelationEvent)
            .where(GraphRelationEvent.run_id == run_id)
            .order_by(
                GraphRelationEvent.chunk_id.desc(),
                GraphRelationEvent.relation_event_id.desc(),
            )
        )
        if offset > 0:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = self.session.execute(stmt).scalars().all()
        return [
            RelationEventRow(
                relation_event_id=row.relation_event_id,
                chunk_id=row.chunk_id,
                from_entity_id=row.from_entity_id,
                to_entity_id=row.to_entity_id,
                from_name=entity_names.get(row.from_entity_id, str(row.from_entity_id)),
                to_name=entity_names.get(row.to_entity_id, str(row.to_entity_id)),
                relation_type=row.relation_type,
                change_type=row.change_type,
                evidence=row.evidence,
                confidence=row.confidence,
                source_relation_row_id=row.source_relation_row_id,
                directionality=row.directionality,
            )
            for row in rows
        ]

    def fetch_low_confidence_relation_events(
        self,
        run_id: str,
        threshold: float = 0.6,
        limit: int = 100,
    ) -> list[LowConfidenceRelationEventRow]:
        events = self.fetch_relation_events(run_id)
        low_confidence = [event for event in events if event.confidence is None or float(event.confidence) < threshold]
        selected_events = low_confidence[:limit] if limit > 0 else low_confidence
        return [
            LowConfidenceRelationEventRow(
                relation_event_id=event.relation_event_id,
                chunk_id=event.chunk_id,
                from_entity_id=event.from_entity_id,
                to_entity_id=event.to_entity_id,
                from_name=event.from_name,
                to_name=event.to_name,
                relation_type=event.relation_type,
                change_type=event.change_type,
                evidence=event.evidence,
                confidence=event.confidence,
                source_relation_row_id=event.source_relation_row_id,
                directionality=event.directionality,
            )
            for event in selected_events
        ]

    def detect_relation_conflicts(
        self,
        run_id: str,
        active_only: bool = True,
    ) -> list[RelationConflictRow]:
        current_relations = self.fetch_current_relations(run_id, active_only=active_only)
        pair_map: dict[tuple[int, int], list[CurrentRelationRow]] = {}
        for rel in current_relations:
            left_id = rel.from_entity_id
            right_id = rel.to_entity_id
            key = (left_id, right_id) if left_id <= right_id else (right_id, left_id)
            pair_map.setdefault(key, []).append(rel)

        conflicts: list[RelationConflictRow] = []
        for (left_id, right_id), relations in pair_map.items():
            relation_types = {str(item.relation_type) for item in relations if item.relation_type}
            if len(relation_types) < 2:
                continue
            conflicts.append(
                RelationConflictRow(
                    entity_pair=(left_id, right_id),
                    entity_names=sorted(
                        {str(rel_item.from_name or left_id) for rel_item in relations}
                        | {str(rel_item.to_name or right_id) for rel_item in relations}
                    ),
                    relation_types=sorted(relation_types),
                    relation_count=len(relations),
                    relation_ids=[item.relation_id for item in relations],
                )
            )
        return conflicts

    def fetch_entities(
        self,
        run_id: str,
        entity_type: str | None = None,
        status: str | None = None,
    ) -> list[GraphEntity]:
        """
        获取指定运行的图谱实体（ORM 对象）。

        修改时间: 2026-04-02
        修改者: TraeAI
        任务: P2.1-downstream-switch
        修改内容: 新增 status 参数支持按状态过滤

        Args:
            run_id: 运行ID
            entity_type: 可选的实体类型过滤（如 "character"）
            status: 可选的状态过滤（如 "active"）

        Returns:
            GraphEntity ORM 对象列表
        """
        stmt = select(GraphEntity).where(GraphEntity.run_id == run_id)
        if entity_type is not None:
            stmt = stmt.where(GraphEntity.entity_type == entity_type)
        if status is not None:
            stmt = stmt.where(GraphEntity.status == status)
        return list(self.session.execute(stmt).scalars().all())

    def fetch_participant_entities(
        self,
        run_id: str,
        entity_type: str | None = None,
        status: str | None = None,
    ) -> list[ParticipantEntityRow]:
        """
        2026-04-26，任务：图谱参与者层落地
        新建原因：最终人物图谱、graph authority report 等 consumer
        需要稳定读取“有关系资格”的参与者集合，而不是全量人物。
        """
        stmt = (
            select(GraphEntityParticipant, GraphEntity)
            .join(GraphEntity, GraphEntityParticipant.entity_id == GraphEntity.entity_id)
            .where(
                GraphEntityParticipant.run_id == run_id,
                GraphEntity.run_id == run_id,
            )
            .order_by(GraphEntity.canonical_name.asc(), GraphEntity.entity_id.asc())
        )
        if entity_type is not None:
            stmt = stmt.where(GraphEntity.entity_type == entity_type)
        if status is not None:
            stmt = stmt.where(GraphEntity.status == status)

        rows = self.session.execute(stmt).all()
        return [
            ParticipantEntityRow(
                entity_id=entity.entity_id,
                name=entity.canonical_name,
                entity_type=entity.entity_type,
                status=entity.status,
                primary_role_function=entity.primary_role_function,
                first_seen_chunk=entity.first_seen_chunk,
                last_seen_chunk=entity.last_seen_chunk,
                source_confidence=entity.source_confidence,
                relation_event_count=participant.relation_event_count,
                current_degree=participant.current_degree,
                historical_degree=participant.historical_degree,
                first_relation_chunk=participant.first_relation_chunk,
                last_relation_chunk=participant.last_relation_chunk,
                latest_relation_event_id=participant.latest_relation_event_id,
            )
            for participant, entity in rows
        ]

    def fetch_relation_event_models(self, run_id: str) -> list[GraphRelationEvent]:
        """
        获取指定运行的关系事件（ORM 对象）。

        与 fetch_relation_events() 不同，本方法返回 ORM 对象而非 dict，
        适用于需要访问原始属性（如 chunk_id、from_entity_id）的场景。

        Args:
            run_id: 运行ID

        Returns:
            GraphRelationEvent ORM 对象列表
        """
        stmt = (
            select(GraphRelationEvent)
            .where(GraphRelationEvent.run_id == run_id)
            .order_by(GraphRelationEvent.chunk_id.desc(), GraphRelationEvent.relation_event_id.desc())
        )
        return list(self.session.execute(stmt).scalars().all())
