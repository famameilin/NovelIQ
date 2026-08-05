"""
数据库图事实读侧仓储
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from src.models.local.character_reference_policy import (
    is_global_character_surface_name,
    is_reference_surface_name,
)
from src.storage.models import GraphEntity, GraphEntityAlias, GraphFact, GraphFactSource
from src.storage.repositories.base import BaseRepository

_CHANGE_LABELS = {
    "assert": "新建",
    "reinforce": "强化",
    "refine": "强化",
    "supersede": "强化",
    "weaken": "弱化",
    "break": "断裂",
    "retract": "断裂",
}
_CONFIDENCE_SCORES = {"high": 0.9, "medium": 0.7, "low": 0.5}


@dataclass(frozen=True)
class ActiveEntityRow:
    """2026-08-05 用于返回近期活动实体的具名读模型"""

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
    """2026-08-05 用于返回关系事实推导的当前快照"""

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
    """2026-08-05 用于返回数据库图关系事实历史事件"""

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
    """2026-08-05 用于返回低置信关系事实事件"""

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
    """2026-08-05 用于返回同一实体对的当前关系冲突"""

    entity_pair: tuple[int, int]
    entity_names: list[str]
    relation_types: list[str]
    relation_count: int
    relation_ids: list[int | None]


@dataclass(frozen=True)
class ParticipantEntityRow:
    """2026-08-05 用于返回关系事实端点参与者的统计视图"""

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


@dataclass(frozen=True)
class _RelationFact:
    """2026-08-05 用于承载关系 GraphFact 到公开 DTO 之间的内部结构"""

    event_id: int
    chunk_id: int
    from_name: str
    to_name: str
    relation_type: str
    change_type: str
    evidence: str | None
    confidence: float | None
    directionality: str


class GraphRepository(BaseRepository[GraphFact]):
    """2026-08-05 用于统一从 graph_facts 读取实体关系与事实历史"""

    def _entity_maps(self, run_id: str) -> tuple[dict[str, GraphEntity], dict[int, GraphEntity]]:
        """2026-08-05 用于构建规范实体名称与 ID 双向查询映射"""
        rows = list(
            self.session.execute(
                select(GraphEntity).where(GraphEntity.run_id == run_id)
            )
            .scalars()
            .all()
        )
        valid = [row for row in rows if is_global_character_surface_name(row.canonical_name)]
        return (
            {row.canonical_name: row for row in valid},
            {row.entity_id: row for row in valid},
        )

    def _chapter_anchor_chunks(self, run_id: str) -> dict[int, int]:
        """2026-08-05 用于把章节 Evidence 锚点转换为关系事件 chunk_id"""
        from src.storage.models import Chunk

        rows = self.session.execute(
            select(Chunk.chapter_id, func.min(Chunk.chunk_id).label("chunk_id"))
            .where(Chunk.run_id == run_id)
            .group_by(Chunk.chapter_id)
        ).all()
        return {int(row.chapter_id): int(row.chunk_id) for row in rows}

    def _relation_facts(self, run_id: str) -> list[_RelationFact]:
        """2026-08-05 用于从章节关系与连续性关系 GraphFact 生成统一历史"""
        anchor_chunks = self._chapter_anchor_chunks(run_id)
        stmt = (
            select(GraphFact, GraphFactSource)
            .join(GraphFactSource, GraphFactSource.graph_fact_id == GraphFact.graph_fact_id)
            .where(
                GraphFact.run_id == run_id,
                GraphFactSource.run_id == run_id,
            )
            .order_by(GraphFact.graph_fact_id)
        )
        facts: list[_RelationFact] = []
        for fact, source in self.session.execute(stmt).all():
            content = fact.content if isinstance(fact.content, dict) else {}
            kind = content.get("kind")
            from_name = ""
            to_name = ""
            directionality = "directed"
            change_kind = "assert"
            chunk_id: int | None = None
            if kind == "relations":
                from_entity = content.get("from_entity")
                to_entity = content.get("to_entity")
                if not isinstance(from_entity, dict) or not isinstance(to_entity, dict):
                    continue
                from_name = str(from_entity.get("name") or "").strip()
                to_name = str(to_entity.get("name") or "").strip()
                directionality = str(content.get("directionality") or "directed")
                change_kind = str(content.get("change_kind") or "assert")
                chunk_id = int(content["chunk_id"])
            elif kind == "continuity_fact" and isinstance(fact.object, dict):
                from_name = fact.subject_name.strip()
                to_name = str(fact.object.get("name") or "").strip()
                change_kind = str(content.get("change_kind") or "assert")
                evidence_chapter = source.evidence.get("chapterid") if isinstance(source.evidence, dict) else None
                if isinstance(evidence_chapter, int):
                    chunk_id = anchor_chunks.get(evidence_chapter)
            else:
                continue
            if (
                chunk_id is None
                or not is_global_character_surface_name(from_name)
                or not is_global_character_surface_name(to_name)
            ):
                continue
            reason = source.evidence.get("reason") if isinstance(source.evidence, dict) else None
            facts.append(
                _RelationFact(
                    event_id=fact.graph_fact_id,
                    chunk_id=chunk_id,
                    from_name=from_name,
                    to_name=to_name,
                    relation_type=fact.predicate,
                    change_type=_CHANGE_LABELS.get(change_kind, change_kind),
                    evidence=str(reason) if reason else None,
                    confidence=_CONFIDENCE_SCORES.get(fact.confidence),
                    directionality=directionality,
                )
            )
        return facts

    def _relation_event_rows(self, run_id: str) -> list[RelationEventRow]:
        """2026-08-05 用于把内部关系事实关联到规范实体 ID"""
        by_name, _ = self._entity_maps(run_id)
        rows: list[RelationEventRow] = []
        for fact in self._relation_facts(run_id):
            from_entity = by_name.get(fact.from_name)
            to_entity = by_name.get(fact.to_name)
            if from_entity is None or to_entity is None:
                continue
            rows.append(
                RelationEventRow(
                    relation_event_id=fact.event_id,
                    chunk_id=fact.chunk_id,
                    from_entity_id=from_entity.entity_id,
                    to_entity_id=to_entity.entity_id,
                    from_name=fact.from_name,
                    to_name=fact.to_name,
                    relation_type=fact.relation_type,
                    change_type=fact.change_type,
                    evidence=fact.evidence,
                    confidence=fact.confidence,
                    source_relation_row_id=None,
                    directionality=fact.directionality,
                )
            )
        return rows

    def fetch_alias_map(self, run_id: str) -> dict[str, str]:
        """2026-08-05 用于从数据库图别名表读取规范映射"""
        rows = self.session.execute(
            select(GraphEntityAlias.alias, GraphEntity.canonical_name)
            .join(GraphEntity, GraphEntityAlias.entity_id == GraphEntity.entity_id)
            .where(GraphEntityAlias.run_id == run_id)
        ).all()
        alias_map = {
            str(row.alias): str(row.canonical_name)
            for row in rows
            if not is_reference_surface_name(row.alias)
            and is_global_character_surface_name(row.canonical_name)
        }
        for canonical in set(alias_map.values()):
            alias_map.setdefault(canonical, canonical)
        return alias_map

    def fetch_active_entities(
        self,
        current_chunk_id: int,
        lookback: int = 10,
        run_id: str | None = None,
    ) -> list[ActiveEntityRow]:
        """2026-08-05 用于从实体投影与最新人物事实读取近期活动实体"""
        if run_id is None:
            return []
        start_chunk = max(0, current_chunk_id - lookback)
        latest_character_fact: dict[str, dict[str, Any]] = {}
        stmt = (
            select(GraphFact)
            .where(GraphFact.run_id == run_id, GraphFact.active.is_(True))
            .order_by(GraphFact.graph_fact_id)
        )
        for fact in self.session.execute(stmt).scalars().all():
            content = fact.content if isinstance(fact.content, dict) else {}
            entity = content.get("entity")
            chunk_id = content.get("chunk_id")
            if (
                content.get("kind") != "characters"
                or not isinstance(entity, dict)
                or not isinstance(chunk_id, int)
                or chunk_id < start_chunk
                or chunk_id > current_chunk_id
            ):
                continue
            latest_character_fact[str(entity.get("name") or "")] = content

        entity_stmt = (
            select(GraphEntity)
            .where(
                GraphEntity.run_id == run_id,
                GraphEntity.last_seen_chunk.is_not(None),
                GraphEntity.last_seen_chunk >= start_chunk,
                GraphEntity.last_seen_chunk <= current_chunk_id,
                GraphEntity.status == "active",
            )
            .order_by(GraphEntity.last_seen_chunk.desc(), GraphEntity.entity_id)
        )
        result: list[ActiveEntityRow] = []
        for entity in self.session.execute(entity_stmt).scalars().all():
            if not is_global_character_surface_name(entity.canonical_name):
                continue
            content = latest_character_fact.get(entity.canonical_name, {})
            result.append(
                ActiveEntityRow(
                    entity_id=entity.entity_id,
                    name=entity.canonical_name,
                    role=str(content.get("role_function") or entity.primary_role_function or "") or None,
                    entity_type=entity.entity_type,
                    status=entity.status,
                    last_action=str(content.get("action") or entity.last_action or ""),
                    last_emotion=str(content.get("emotion") or entity.last_emotion_score or ""),
                    emotion_score=str(content.get("emotion") or entity.last_emotion_score or "") or None,
                    chunk_id=(
                        int(content["chunk_id"])
                        if isinstance(content.get("chunk_id"), int)
                        else entity.last_seen_chunk
                    ),
                )
            )
        return result

    def fetch_current_relations(self, run_id: str, active_only: bool = True) -> list[CurrentRelationRow]:
        """2026-08-05 用于按关系 GraphFact 历史推导当前关系快照"""
        grouped: dict[tuple[int, int], list[RelationEventRow]] = {}
        for event in self._relation_event_rows(run_id):
            if event.directionality == "bidirectional":
                left_id, right_id = sorted((event.from_entity_id, event.to_entity_id))
                key = (left_id, right_id)
            else:
                key = (event.from_entity_id, event.to_entity_id)
            grouped.setdefault(key, []).append(event)
        rows: list[CurrentRelationRow] = []
        for events in grouped.values():
            ordered = sorted(events, key=lambda item: (item.chunk_id, item.relation_event_id))
            first = ordered[0]
            latest = ordered[-1]
            is_active = latest.change_type != "断裂"
            if active_only and not is_active:
                continue
            tension = 0.0
            for event in ordered:
                confidence = event.confidence or 0.5
                if event.relation_type == "敌对":
                    tension += confidence
                elif event.relation_type in {"盟友", "友情"}:
                    tension -= confidence * 0.5
            rows.append(
                CurrentRelationRow(
                    relation_id=latest.relation_event_id,
                    from_entity_id=latest.from_entity_id,
                    to_entity_id=latest.to_entity_id,
                    from_name=latest.from_name,
                    to_name=latest.to_name,
                    relation_type=latest.relation_type,
                    first_seen_chunk=first.chunk_id,
                    last_seen_chunk=latest.chunk_id,
                    change_count=sum(1 for event in ordered if event.change_type != "新建"),
                    support_count=len(ordered),
                    latest_event_id=latest.relation_event_id,
                    tension_index=tension,
                    is_active=is_active,
                )
            )
        return rows

    def count_current_relations(self, run_id: str, active_only: bool | None = None) -> int:
        """2026-08-05 用于统计关系事实推导的当前关系数量"""
        if active_only is None:
            return len(self.fetch_current_relations(run_id, active_only=False))
        return sum(
            1
            for row in self.fetch_current_relations(run_id, active_only=False)
            if row.is_active is active_only
        )

    def fetch_relation_endpoint_entity_ids(self, run_id: str) -> set[int]:
        """2026-08-05 用于返回全部关系事实端点实体 ID"""
        return {
            entity_id
            for event in self._relation_event_rows(run_id)
            for entity_id in (event.from_entity_id, event.to_entity_id)
        }

    def count_relation_events(self, run_id: str) -> int:
        """2026-08-05 用于统计关系 GraphFact 历史事件数量"""
        return len(self._relation_event_rows(run_id))

    def fetch_relation_events(
        self,
        run_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[RelationEventRow]:
        """2026-08-05 用于按最新优先顺序分页读取关系 GraphFact 历史"""
        rows = sorted(
            self._relation_event_rows(run_id),
            key=lambda row: (row.chunk_id, row.relation_event_id),
            reverse=True,
        )
        end = None if limit is None else offset + limit
        return rows[offset:end]

    def fetch_low_confidence_relation_events(
        self,
        run_id: str,
        threshold: float = 0.6,
        limit: int = 100,
    ) -> list[LowConfidenceRelationEventRow]:
        """2026-08-05 用于筛选低置信关系 GraphFact 历史"""
        events = [
            event
            for event in self.fetch_relation_events(run_id)
            if event.confidence is None or event.confidence < threshold
        ]
        selected = events[:limit] if limit > 0 else events
        return [LowConfidenceRelationEventRow(**event.__dict__) for event in selected]

    def detect_relation_conflicts(
        self,
        run_id: str,
        active_only: bool = True,
    ) -> list[RelationConflictRow]:
        """2026-08-05 用于检测同一实体对的当前关系类型冲突"""
        pair_map: dict[tuple[int, int], list[CurrentRelationRow]] = {}
        for relation in self.fetch_current_relations(run_id, active_only=active_only):
            left_id, right_id = sorted((relation.from_entity_id, relation.to_entity_id))
            key = (left_id, right_id)
            pair_map.setdefault(key, []).append(relation)
        conflicts: list[RelationConflictRow] = []
        for key, relations in pair_map.items():
            relation_types = sorted({row.relation_type for row in relations})
            if len(relation_types) < 2:
                continue
            conflicts.append(
                RelationConflictRow(
                    entity_pair=key,
                    entity_names=sorted(
                        {row.from_name for row in relations} | {row.to_name for row in relations}
                    ),
                    relation_types=relation_types,
                    relation_count=len(relations),
                    relation_ids=[row.relation_id for row in relations],
                )
            )
        return conflicts

    def fetch_entities(
        self,
        run_id: str,
        entity_type: str | None = None,
        status: str | None = None,
    ) -> list[GraphEntity]:
        """2026-08-05 用于读取数据库图规范实体"""
        stmt = select(GraphEntity).where(GraphEntity.run_id == run_id)
        if entity_type is not None:
            stmt = stmt.where(GraphEntity.entity_type == entity_type)
        if status is not None:
            stmt = stmt.where(GraphEntity.status == status)
        return [
            entity
            for entity in self.session.execute(stmt).scalars().all()
            if is_global_character_surface_name(entity.canonical_name)
        ]

    def fetch_participant_entities(
        self,
        run_id: str,
        entity_type: str | None = None,
        status: str | None = None,
    ) -> list[ParticipantEntityRow]:
        """2026-08-05 用于从关系 GraphFact 端点推导参与者统计视图"""
        events = self._relation_event_rows(run_id)
        active_relations = self.fetch_current_relations(run_id, active_only=True)
        _, by_id = self._entity_maps(run_id)
        endpoint_ids = {
            entity_id
            for event in events
            for entity_id in (event.from_entity_id, event.to_entity_id)
        }
        rows: list[ParticipantEntityRow] = []
        for entity_id in sorted(endpoint_ids):
            entity = by_id.get(entity_id)
            if entity is None:
                continue
            if entity_type is not None and entity.entity_type != entity_type:
                continue
            if status is not None and entity.status != status:
                continue
            entity_events = [
                event
                for event in events
                if entity_id in {event.from_entity_id, event.to_entity_id}
            ]
            current_counterparts = {
                relation.to_entity_id if relation.from_entity_id == entity_id else relation.from_entity_id
                for relation in active_relations
                if entity_id in {relation.from_entity_id, relation.to_entity_id}
            }
            historical_counterparts = {
                event.to_entity_id if event.from_entity_id == entity_id else event.from_entity_id
                for event in entity_events
            }
            rows.append(
                ParticipantEntityRow(
                    entity_id=entity.entity_id,
                    name=entity.canonical_name,
                    entity_type=entity.entity_type,
                    status=entity.status,
                    primary_role_function=entity.primary_role_function,
                    first_seen_chunk=entity.first_seen_chunk,
                    last_seen_chunk=entity.last_seen_chunk,
                    source_confidence=entity.source_confidence,
                    relation_event_count=len(entity_events),
                    current_degree=len(current_counterparts),
                    historical_degree=len(historical_counterparts),
                    first_relation_chunk=min((event.chunk_id for event in entity_events), default=None),
                    last_relation_chunk=max((event.chunk_id for event in entity_events), default=None),
                    latest_relation_event_id=max(
                        (event.relation_event_id for event in entity_events),
                        default=None,
                    ),
                )
            )
        return rows

    def count_entity_participants(self, run_id: str) -> int:
        """2026-08-05 用于统计关系 GraphFact 端点参与者数量"""
        return len(self.fetch_participant_entities(run_id))
