from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from src.storage.models import (
    GraphEntity,
    GraphEntityAlias,
    GraphRelationCurrent,
    GraphRelationEvent,
)
from src.storage.repositories.base import BaseRepository


class GraphRepository(BaseRepository["GraphRepository"]):
    def reset_graph_tables(self, run_id: str) -> None:
        """
        清空指定 run 的 graph_* 权威表数据。

        用于在别名归一化规则发生显著变化后执行全量重建，避免旧投影残留。
        """
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
        if last_action:
            entity.last_action = last_action
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
                "last_action": row.last_action or "",
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

    def fetch_low_confidence_relation_events(
        self,
        run_id: str,
        threshold: float = 0.6,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        events = self.fetch_relation_events(run_id)
        low_confidence = [
            event
            for event in events
            if event["confidence"] is None or float(event["confidence"]) < threshold
        ]
        return low_confidence[:limit] if limit > 0 else low_confidence

    def detect_relation_conflicts(
        self,
        run_id: str,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        current_relations = self.fetch_current_relations(run_id, active_only=active_only)
        pair_map: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for rel in current_relations:
            key = tuple(sorted([rel["from_entity_id"], rel["to_entity_id"]]))
            pair_map.setdefault(key, []).append(rel)

        conflicts: list[dict[str, Any]] = []
        for (left_id, right_id), relations in pair_map.items():
            relation_types = {str(item["type"]) for item in relations if item.get("type")}
            if len(relation_types) < 2:
                continue
            conflicts.append(
                {
                    "entity_pair": (left_id, right_id),
                    "entity_names": sorted(
                        {
                            str(rel_item.get("from_name", left_id))
                            for rel_item in relations
                        }
                        | {
                            str(rel_item.get("to_name", right_id))
                            for rel_item in relations
                        }
                    ),
                    "relation_types": sorted(relation_types),
                    "relation_count": len(relations),
                    "relation_ids": [item.get("relation_id") for item in relations],
                }
            )
        return conflicts

    def fetch_entities(
        self,
        run_id: str,
        entity_type: str | None = None,
    ) -> list[GraphEntity]:
        """
        获取指定运行的图谱实体（ORM 对象）。

        Args:
            run_id: 运行ID
            entity_type: 可选的实体类型过滤（如 "character"）

        Returns:
            GraphEntity ORM 对象列表
        """
        stmt = select(GraphEntity).where(GraphEntity.run_id == run_id)
        if entity_type is not None:
            stmt = stmt.where(GraphEntity.entity_type == entity_type)
        return list(self.session.execute(stmt).scalars().all())

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
