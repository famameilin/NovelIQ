from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.storage.models import (
    Entity,
    EntityAlias,
    GraphEntity,
    GraphEntityAlias,
    GraphRelationCurrent,
    GraphRelationEvent,
)
from src.storage.repositories.base import BaseRepository


class GraphRepository(BaseRepository["GraphRepository"]):
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
        source_confidence: float | None = None,
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
                source_confidence=source_confidence,
            )
            self.session.add(entity)
            self.session.flush()
            return entity

        if first_seen_chunk is not None:
            entity.first_seen_chunk = min(entity.first_seen_chunk or first_seen_chunk, first_seen_chunk)
        if last_seen_chunk is not None:
            entity.last_seen_chunk = max(entity.last_seen_chunk or last_seen_chunk, last_seen_chunk)
        if primary_role_function:
            entity.primary_role_function = primary_role_function
        if last_emotion_score:
            entity.last_emotion_score = last_emotion_score
        if source_confidence is not None:
            entity.source_confidence = source_confidence
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
        row = self.session.execute(stmt).fetchone()
        if row:
            return row[0]
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
            ).scalars().all()
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

    def fetch_alias_map(self, run_id: str) -> dict[str, str]:
        rows = self.session.execute(
            select(GraphEntityAlias.alias, GraphEntity.canonical_name)
            .join(GraphEntity, GraphEntityAlias.entity_id == GraphEntity.entity_id)
            .where(GraphEntityAlias.run_id == run_id)
        ).fetchall()
        alias_pairs: list[tuple[str, str]] = [(row[0], row[1]) for row in rows]
        alias_map: dict[str, str] = dict(alias_pairs)
        for canonical in list(alias_map.values()):
            alias_map.setdefault(canonical, canonical)
        return alias_map

    def fetch_active_entities(
        self,
        current_chunk_id: int,
        lookback: int = 10,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if run_id is None:
            return []
        start_chunk = max(0, current_chunk_id - lookback)
        rows = self.session.execute(
            select(GraphEntity)
            .where(
                GraphEntity.run_id == run_id,
                GraphEntity.last_seen_chunk.is_not(None),
                GraphEntity.last_seen_chunk >= start_chunk,
                GraphEntity.last_seen_chunk <= current_chunk_id,
                GraphEntity.status == "active",
            )
            .order_by(GraphEntity.last_seen_chunk.desc(), GraphEntity.entity_id.asc())
        ).scalars().all()
        return [
            {
                "entity_id": row.entity_id,
                "name": row.canonical_name,
                "role": row.primary_role_function,
                "last_action": "",
                "last_emotion": row.last_emotion_score or "",
                "emotion_score": row.last_emotion_score,
                "chunk_id": row.last_seen_chunk,
            }
            for row in rows
        ]

    def fetch_current_relations(
        self,
        run_id: str,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(
                GraphRelationCurrent,
                GraphEntity.canonical_name,
                GraphEntity.entity_id,
            )
            .join(GraphEntity, GraphRelationCurrent.from_entity_id == GraphEntity.entity_id)
            .where(GraphRelationCurrent.run_id == run_id)
        )
        if active_only:
            stmt = stmt.where(GraphRelationCurrent.is_active.is_(True))
        current_rows = self.session.execute(stmt).fetchall()

        entity_names = {
            row.entity_id: row.canonical_name
            for row in self.session.execute(
                select(GraphEntity.entity_id, GraphEntity.canonical_name).where(GraphEntity.run_id == run_id)
            ).fetchall()
        }

        result: list[dict[str, Any]] = []
        for current, _from_name, _entity_id in current_rows:
            result.append(
                {
                    "relation_id": current.relation_id,
                    "from_entity_id": current.from_entity_id,
                    "to_entity_id": current.to_entity_id,
                    "from_name": entity_names.get(current.from_entity_id, str(current.from_entity_id)),
                    "to_name": entity_names.get(current.to_entity_id, str(current.to_entity_id)),
                    "type": current.current_type,
                    "first_seen_chunk": current.first_seen_chunk,
                    "last_seen_chunk": current.last_seen_chunk,
                    "change_count": current.change_count,
                    "support_count": current.support_count,
                    "latest_event_id": current.latest_event_id,
                    "tension_index": current.tension_index,
                    "is_active": current.is_active,
                }
            )
        return result

    def fetch_relation_events(self, run_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        entity_names = {
            row.entity_id: row.canonical_name
            for row in self.session.execute(
                select(GraphEntity.entity_id, GraphEntity.canonical_name).where(GraphEntity.run_id == run_id)
            ).fetchall()
        }
        stmt = select(GraphRelationEvent).where(GraphRelationEvent.run_id == run_id).order_by(
            GraphRelationEvent.chunk_id.desc(),
            GraphRelationEvent.relation_event_id.desc(),
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = self.session.execute(stmt).scalars().all()
        return [
            {
                "relation_event_id": row.relation_event_id,
                "chunk_id": row.chunk_id,
                "from_entity_id": row.from_entity_id,
                "to_entity_id": row.to_entity_id,
                "from_name": entity_names.get(row.from_entity_id, str(row.from_entity_id)),
                "to_name": entity_names.get(row.to_entity_id, str(row.to_entity_id)),
                "relation_type": row.relation_type,
                "change_type": row.change_type,
                "evidence": row.evidence,
                "confidence": row.confidence,
                "source_relation_row_id": row.source_relation_row_id,
                "directionality": row.directionality,
            }
            for row in rows
        ]

    def sync_entity_aliases_to_legacy(self, run_id: str, novel_id: str) -> None:
        entities_by_canonical: dict[str, Entity] = {
            entity.canonical: entity
            for entity in self.session.execute(
                select(Entity).where(Entity.run_id == run_id, Entity.novel_id == novel_id)
            ).scalars().all()
        }
        graph_entities = self.session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars().all()
        for graph_entity in graph_entities:
            legacy_entity = entities_by_canonical.get(graph_entity.canonical_name)
            if legacy_entity is None:
                legacy_entity = Entity(
                    novel_id=novel_id,
                    canonical=graph_entity.canonical_name,
                    entity_type=graph_entity.entity_type,
                    first_chunk=graph_entity.first_seen_chunk,
                    last_chunk=graph_entity.last_seen_chunk,
                    description=None,
                    confidence=graph_entity.source_confidence or 1.0,
                    run_id=run_id,
                )
                self.session.add(legacy_entity)
                self.session.flush()
                entities_by_canonical[graph_entity.canonical_name] = legacy_entity
            else:
                legacy_entity.last_chunk = graph_entity.last_seen_chunk
                legacy_entity.first_chunk = graph_entity.first_seen_chunk
                legacy_entity.entity_type = graph_entity.entity_type

        aliases = self.session.execute(select(GraphEntityAlias).where(GraphEntityAlias.run_id == run_id)).scalars().all()
        for alias in aliases:
            alias_owner = next((item for item in graph_entities if item.entity_id == alias.entity_id), None)
            if alias_owner is None:
                continue
            legacy_entity = entities_by_canonical.get(alias_owner.canonical_name)
            if legacy_entity is None or legacy_entity.entity_id is None:
                continue
            stmt = (
                insert(EntityAlias)
                .values(
                    entity_id=legacy_entity.entity_id,
                    alias=alias.alias,
                    alias_type="graph_mirror" if not alias.is_primary else "canonical",
                    source_chunk=alias.source_chunk_id,
                    confirm_count=1,
                    run_id=run_id,
                )
                .on_conflict_do_nothing(constraint="uq_entity_aliases_entity_alias")
            )
            self.session.execute(stmt)
