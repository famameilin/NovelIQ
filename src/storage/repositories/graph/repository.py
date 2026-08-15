"""
章节级事实图版本查询仓储
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal
from typing import cast as type_cast

from sqlalchemy import String, func, or_, select, text
from sqlalchemy import cast as sql_cast

from src.models.local.character_reference_policy import is_global_character_surface_name
from src.storage.models import (
    EntityStateVersion,
    GraphEntity,
    GraphFact,
    GraphRelation,
    GraphRelationVersion,
    GraphVersion,
)
from src.storage.repositories.base import BaseRepository


@dataclass(frozen=True, slots=True)
class EntitySnapshotRow:
    """2026-08-08 用于返回目标章节边界的实体身份与完整状态"""

    entity_id: int
    name: str
    entity_type: str
    tags: list[str]
    attributes: dict[str, Any]
    first_seen_chapter: int
    last_seen_chapter: int
    state_revision: int
    state: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RelationSnapshotRow:
    """2026-08-07 用于返回目标章节边界的稳定关系最新版本"""

    relation_version_id: int
    graph_version_id: str
    chapter_id: int
    relation_id: str
    relation_revision: int
    from_entity_id: int
    to_entity_id: int
    from_name: str
    to_name: str
    relation_type: str
    directionality: str
    relation_semantics: str
    attributes: dict[str, Any]
    is_active: bool
    changes: list[dict[str, Any]]
    first_seen_chapter: int
    last_seen_chapter: int


@dataclass(frozen=True, slots=True)
class GraphChangeRow:
    """2026-08-07 用于返回按原因事实拆分的实体或关系章节变化"""

    change_id: str
    change_kind: Literal["state", "relation"]
    graph_version_id: str
    chapter_id: int
    chapter_order: int
    fact_id: str
    fact_revision: int
    effective_chapter_id: int
    confidence: str
    changes: list[dict[str, Any]]
    entity_id: int | None = None
    entity_name: str | None = None
    entity_type: str | None = None
    relation_id: str | None = None
    relation_version_id: int | None = None
    relation_revision: int | None = None
    from_entity_id: int | None = None
    to_entity_id: int | None = None
    from_name: str | None = None
    to_name: str | None = None
    relation_type: str | None = None
    directionality: str | None = None
    relation_semantics: str | None = None


@dataclass(frozen=True, slots=True)
class GraphSnapshotRow:
    """2026-08-07 用于承载一个章节图版本的实体与有效关系"""

    graph_version: GraphVersion
    entities: list[EntitySnapshotRow]
    relations: list[RelationSnapshotRow]


class GraphRepository(BaseRepository[GraphFact]):
    """2026-08-07 用于按章节图版本直接查询事实实体状态和关系版本"""

    def resolve_graph_version(
        self,
        run_id: str,
        *,
        chapter_id: int | None = None,
        graph_version_id: str | None = None,
    ) -> GraphVersion | None:
        """2026-08-07 用于解析显式章节图版本或当前 run 最新章节版本"""
        if chapter_id is not None and graph_version_id is not None:
            raise ValueError("chapter_id 与 graph_version_id 只能选择一个")
        stmt = select(GraphVersion).where(GraphVersion.run_id == run_id)
        if graph_version_id is not None:
            stmt = stmt.where(GraphVersion.graph_version_id == graph_version_id)
        elif chapter_id is not None:
            stmt = stmt.where(GraphVersion.chapter_id == chapter_id)
        else:
            stmt = stmt.order_by(GraphVersion.chapter_order.desc()).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

    def previous_graph_version(
        self,
        run_id: str,
        *,
        chapter_order: int,
    ) -> GraphVersion | None:
        """2026-08-07 用于按章节顺序读取最近已完成的上一章节图版本"""
        return self.session.execute(
            select(GraphVersion)
            .where(
                GraphVersion.run_id == run_id,
                GraphVersion.chapter_order < chapter_order,
            )
            .order_by(GraphVersion.chapter_order.desc())
            .limit(1)
        ).scalar_one_or_none()

    def fetch_fact_version(
        self,
        run_id: str,
        fact_id: str,
        fact_revision: int,
    ) -> GraphFact | None:
        """2026-08-07 用于按同 run 事实 ID 与修订号读取不可变事实版本"""
        return self.session.execute(
            select(GraphFact).where(
                GraphFact.run_id == run_id,
                GraphFact.fact_id == fact_id,
                GraphFact.fact_revision == fact_revision,
            )
        ).scalar_one_or_none()

    def _latest_state_rows(self, boundary: GraphVersion) -> dict[int, EntityStateVersion]:
        """2026-08-07 用于读取目标章节及以前每个实体最近的状态版本"""
        rows = self.session.execute(
            select(EntityStateVersion)
            .join(GraphVersion, GraphVersion.graph_version_id == EntityStateVersion.graph_version_id)
            .where(
                EntityStateVersion.run_id == boundary.run_id,
                GraphVersion.chapter_order <= boundary.chapter_order,
            )
            .distinct(EntityStateVersion.entity_id)
            .order_by(
                EntityStateVersion.entity_id,
                GraphVersion.chapter_order.desc(),
                EntityStateVersion.state_revision.desc(),
            )
        ).scalars()
        return {int(row.entity_id): row for row in rows}

    def fetch_entity_snapshots(self, boundary: GraphVersion) -> list[EntitySnapshotRow]:
        """2026-08-07 用于选择目标章节及以前最近状态并继承无变化实体"""
        latest_states = self._latest_state_rows(boundary)
        entities = self.session.execute(
            select(GraphEntity)
            .where(
                GraphEntity.run_id == boundary.run_id,
                GraphEntity.first_seen_chapter <= boundary.last_chapter_id,
            )
            .order_by(GraphEntity.entity_id)
        ).scalars()
        return [
            EntitySnapshotRow(
                entity_id=int(entity.entity_id),
                name=str(entity.canonical_name),
                entity_type=str(entity.entity_type),
                tags=list(entity.tags or []),
                attributes=dict(entity.attributes or {}),
                first_seen_chapter=int(entity.first_seen_chapter),
                last_seen_chapter=min(int(entity.last_seen_chapter), int(boundary.last_chapter_id)),
                state_revision=(
                    int(latest_states[entity.entity_id].state_revision)
                    if entity.entity_id in latest_states
                    else 0
                ),
                state=(
                    dict(latest_states[entity.entity_id].state)
                    if entity.entity_id in latest_states
                    else {}
                ),
            )
            for entity in entities
        ]

    def _latest_relation_versions(
        self,
        boundary: GraphVersion,
    ) -> list[tuple[GraphRelationVersion, GraphRelation, GraphVersion]]:
        """2026-08-07 用于读取目标章节及以前每条稳定关系最近的关系版本"""
        statement = (
            select(GraphRelationVersion, GraphRelation, GraphVersion)
            .join(GraphRelation, GraphRelation.relation_id == GraphRelationVersion.relation_id)
            .join(GraphVersion, GraphVersion.graph_version_id == GraphRelationVersion.graph_version_id)
            .where(
                GraphRelationVersion.run_id == boundary.run_id,
                GraphVersion.chapter_order <= boundary.chapter_order,
            )
            .distinct(GraphRelationVersion.relation_id)
            .order_by(
                GraphRelationVersion.relation_id,
                GraphVersion.chapter_order.desc(),
                GraphRelationVersion.relation_revision.desc(),
            )
        )
        return list(self.session.execute(statement).tuples().all())

    def fetch_relation_snapshots(
        self,
        boundary: GraphVersion,
        *,
        active_only: bool = True,
    ) -> list[RelationSnapshotRow]:
        """2026-08-07 用于选择目标章节及以前最近关系版本并过滤活动状态"""
        entity_names = {
            int(row.entity_id): str(row.canonical_name)
            for row in self.session.execute(
                select(GraphEntity).where(GraphEntity.run_id == boundary.run_id)
            ).scalars()
        }
        first_seen_by_relation = {
            str(row.relation_id): int(row.first_seen_chapter)
            for row in self.session.execute(
                select(
                    GraphRelationVersion.relation_id,
                    func.min(GraphVersion.first_chapter_id).label("first_seen_chapter"),
                )
                .join(GraphVersion, GraphVersion.graph_version_id == GraphRelationVersion.graph_version_id)
                .where(
                    GraphRelationVersion.run_id == boundary.run_id,
                    GraphVersion.chapter_order <= boundary.chapter_order,
                )
                .group_by(GraphRelationVersion.relation_id)
            ).all()
        }
        rows: list[RelationSnapshotRow] = []
        for version, relation, graph_version in self._latest_relation_versions(boundary):
            if active_only and not version.is_active:
                continue
            rows.append(
                RelationSnapshotRow(
                    relation_version_id=int(version.relation_version_id),
                    graph_version_id=str(version.graph_version_id),
                    chapter_id=int(version.chapter_id),
                    relation_id=str(relation.relation_id),
                    relation_revision=int(version.relation_revision),
                    from_entity_id=int(relation.from_entity_id),
                    to_entity_id=int(relation.to_entity_id),
                    from_name=entity_names[int(relation.from_entity_id)],
                    to_name=entity_names[int(relation.to_entity_id)],
                    relation_type=str(version.relation_type),
                    directionality=str(relation.directionality),
                    relation_semantics=str(relation.relation_semantics),
                    attributes=dict(version.attributes),
                    is_active=bool(version.is_active),
                    changes=list(version.changes),
                    first_seen_chapter=first_seen_by_relation[str(relation.relation_id)],
                    last_seen_chapter=int(graph_version.last_chapter_id),
                )
            )
        return rows

    def fetch_snapshot(
        self,
        run_id: str,
        *,
        chapter_id: int | None = None,
        graph_version_id: str | None = None,
    ) -> GraphSnapshotRow | None:
        """2026-08-07 用于返回目标章节边界的实体状态与有效关系快照"""
        boundary = self.resolve_graph_version(
            run_id,
            chapter_id=chapter_id,
            graph_version_id=graph_version_id,
        )
        if boundary is None:
            return None
        return GraphSnapshotRow(
            graph_version=boundary,
            entities=self.fetch_entity_snapshots(boundary),
            relations=self.fetch_relation_snapshots(boundary, active_only=True),
        )

    def fetch_visible_facts(
        self,
        boundary: GraphVersion,
        *,
        query: str | None = None,
        limit: int = 50,
    ) -> list[GraphFact]:
        """2026-08-07 用于读取目标章节边界可见的每个事实最新修订"""
        stmt = (
            select(GraphFact)
            .join(GraphVersion, GraphVersion.graph_version_id == GraphFact.graph_version_id)
            .where(
                GraphFact.run_id == boundary.run_id,
                GraphVersion.chapter_order <= boundary.chapter_order,
            )
        )
        normalized_query = (query or "").strip()
        if normalized_query:
            tokens = [token for token in re.split(r"[\s,，、；;]+", normalized_query) if token]
            if tokens:
                stmt = stmt.where(
                    or_(
                        *[
                            or_(
                                GraphFact.predicate.ilike(f"%{token}%"),
                                sql_cast(GraphFact.content, String).ilike(f"%{token}%"),
                            )
                            for token in tokens
                        ]
                    )
                )
        stmt = (
            stmt.distinct(GraphFact.fact_id)
            .order_by(
                GraphFact.fact_id,
                GraphFact.fact_revision.desc(),
                GraphVersion.chapter_order.desc(),
            )
            .limit(max(1, limit))
        )
        return list(self.session.execute(stmt).scalars().all())

    def fetch_changes(
        self,
        run_id: str,
        *,
        chapter_id: int | None = None,
        offset: int = 0,
        limit: int | None = 200,
    ) -> tuple[list[GraphChangeRow], int]:
        """2026-08-07 用于在 PostgreSQL 中按章节倒序分页返回变化及根事实"""
        if offset < 0:
            raise ValueError("graph changes offset 不能小于 0")
        page_limit = None if limit is None else max(1, min(limit, 200))
        chapter_filter = ""
        parameters: dict[str, Any] = {"run_id": run_id, "offset": offset}
        if chapter_id is not None:
            chapter_filter = "AND graph_version.chapter_id = :chapter_id"
            parameters["chapter_id"] = chapter_id
        limit_clause = ""
        if page_limit is not None:
            limit_clause = "AND numbered_rows.row_number <= :page_end"
            parameters["page_end"] = offset + page_limit

        # 变化原因直接在数据库中按事实版本聚合，避免先装载完整历史再在 Python 中切页
        statement = text(
            f"""
            WITH state_causes AS (
                SELECT
                    'state:' || state_version.state_version_id::text
                        || ':' || (cause.change ->> 'fact_id')
                        || ':' || ((cause.change ->> 'fact_revision')::integer)::text AS change_id,
                    'state'::text AS change_kind,
                    graph_version.graph_version_id,
                    graph_version.chapter_id,
                    graph_version.chapter_order,
                    cause.change ->> 'fact_id' AS fact_id,
                    (cause.change ->> 'fact_revision')::integer AS fact_revision,
                    MIN(cause.ordinality) AS cause_order,
                    jsonb_agg(cause.change ORDER BY cause.ordinality) AS changes,
                    0 AS kind_order,
                    state_version.state_version_id AS version_row_id,
                    entity.entity_id,
                    entity.canonical_name AS entity_name,
                    entity.entity_type,
                    NULL::varchar AS relation_id,
                    NULL::integer AS relation_version_id,
                    NULL::integer AS relation_revision,
                    NULL::integer AS from_entity_id,
                    NULL::integer AS to_entity_id,
                    NULL::varchar AS from_name,
                    NULL::varchar AS to_name,
                    NULL::varchar AS relation_type,
                    NULL::varchar AS directionality,
                    NULL::varchar AS relation_semantics
                FROM graph_versions AS graph_version
                JOIN entity_state_versions AS state_version
                  ON state_version.graph_version_id = graph_version.graph_version_id
                JOIN graph_entities AS entity
                  ON entity.entity_id = state_version.entity_id
                 AND entity.run_id = graph_version.run_id
                CROSS JOIN LATERAL jsonb_array_elements(state_version.changes)
                    WITH ORDINALITY AS cause(change, ordinality)
                WHERE graph_version.run_id = :run_id
                {chapter_filter}
                GROUP BY
                    state_version.state_version_id,
                    graph_version.graph_version_id,
                    graph_version.chapter_id,
                    graph_version.chapter_order,
                    cause.change ->> 'fact_id',
                    (cause.change ->> 'fact_revision')::integer,
                    entity.entity_id,
                    entity.canonical_name,
                    entity.entity_type
            ),
            relation_causes AS (
                SELECT
                    'relation:' || relation_version.relation_version_id::text
                        || ':' || (cause.change ->> 'fact_id')
                        || ':' || ((cause.change ->> 'fact_revision')::integer)::text AS change_id,
                    'relation'::text AS change_kind,
                    graph_version.graph_version_id,
                    graph_version.chapter_id,
                    graph_version.chapter_order,
                    cause.change ->> 'fact_id' AS fact_id,
                    (cause.change ->> 'fact_revision')::integer AS fact_revision,
                    MIN(cause.ordinality) AS cause_order,
                    jsonb_agg(cause.change ORDER BY cause.ordinality) AS changes,
                    1 AS kind_order,
                    relation_version.relation_version_id AS version_row_id,
                    NULL::integer AS entity_id,
                    NULL::varchar AS entity_name,
                    NULL::varchar AS entity_type,
                    relation.relation_id,
                    relation_version.relation_version_id,
                    relation_version.relation_revision,
                    relation.from_entity_id,
                    relation.to_entity_id,
                    from_entity.canonical_name AS from_name,
                    to_entity.canonical_name AS to_name,
                    relation_version.relation_type,
                    relation.directionality,
                    relation.relation_semantics
                FROM graph_versions AS graph_version
                JOIN graph_relation_versions AS relation_version
                  ON relation_version.graph_version_id = graph_version.graph_version_id
                JOIN graph_relations AS relation
                  ON relation.relation_id = relation_version.relation_id
                 AND relation.run_id = graph_version.run_id
                JOIN graph_entities AS from_entity
                  ON from_entity.entity_id = relation.from_entity_id
                 AND from_entity.run_id = graph_version.run_id
                JOIN graph_entities AS to_entity
                  ON to_entity.entity_id = relation.to_entity_id
                 AND to_entity.run_id = graph_version.run_id
                CROSS JOIN LATERAL jsonb_array_elements(relation_version.changes)
                    WITH ORDINALITY AS cause(change, ordinality)
                WHERE graph_version.run_id = :run_id
                {chapter_filter}
                GROUP BY
                    relation_version.relation_version_id,
                    graph_version.graph_version_id,
                    graph_version.chapter_id,
                    graph_version.chapter_order,
                    cause.change ->> 'fact_id',
                    (cause.change ->> 'fact_revision')::integer,
                    relation.relation_id,
                    relation_version.relation_revision,
                    relation.from_entity_id,
                    relation.to_entity_id,
                    from_entity.canonical_name,
                    to_entity.canonical_name,
                    relation_version.relation_type,
                    relation.directionality,
                    relation.relation_semantics
            ),
            cause_rows AS (
                SELECT * FROM state_causes
                UNION ALL
                SELECT * FROM relation_causes
            ),
            enriched_rows AS (
                SELECT
                    cause_rows.*,
                    fact.effective_chapter_id,
                    fact.confidence
                FROM cause_rows
                LEFT JOIN graph_facts AS fact
                  ON fact.run_id = :run_id
                 AND fact.fact_id = cause_rows.fact_id
                 AND fact.fact_revision = cause_rows.fact_revision
            ),
            numbered_rows AS (
                SELECT
                    enriched_rows.*,
                    row_number() OVER (
                        ORDER BY
                            chapter_order DESC,
                            kind_order,
                            version_row_id,
                            cause_order
                    ) AS row_number
                FROM enriched_rows
            ),
            total_row AS (
                SELECT count(*)::integer AS total
                FROM enriched_rows
            ),
            page_rows AS (
                SELECT *
                FROM numbered_rows
                WHERE numbered_rows.row_number > :offset
                {limit_clause}
            )
            SELECT page_rows.*, total_row.total
            FROM total_row
            LEFT JOIN page_rows ON TRUE
            ORDER BY page_rows.row_number
            """
        )
        result_rows = list(self.session.execute(statement, parameters).mappings())
        total = int(result_rows[0]["total"]) if result_rows else 0
        rows: list[GraphChangeRow] = []
        for result in result_rows:
            if result["change_id"] is None:
                continue
            if result["effective_chapter_id"] is None:
                reference = (str(result["fact_id"]), int(result["fact_revision"]))
                raise ValueError(f"图变化引用了不存在的事实版本: {reference}")
            rows.append(
                GraphChangeRow(
                    change_id=str(result["change_id"]),
                    change_kind=type_cast(Literal["state", "relation"], str(result["change_kind"])),
                    graph_version_id=str(result["graph_version_id"]),
                    chapter_id=int(result["chapter_id"]),
                    chapter_order=int(result["chapter_order"]),
                    fact_id=str(result["fact_id"]),
                    fact_revision=int(result["fact_revision"]),
                    effective_chapter_id=int(result["effective_chapter_id"]),
                    confidence=str(result["confidence"]),
                    changes=list(result["changes"]),
                    entity_id=int(result["entity_id"]) if result["entity_id"] is not None else None,
                    entity_name=str(result["entity_name"]) if result["entity_name"] is not None else None,
                    entity_type=str(result["entity_type"]) if result["entity_type"] is not None else None,
                    relation_id=str(result["relation_id"]) if result["relation_id"] is not None else None,
                    relation_version_id=(
                        int(result["relation_version_id"])
                        if result["relation_version_id"] is not None
                        else None
                    ),
                    relation_revision=(
                        int(result["relation_revision"])
                        if result["relation_revision"] is not None
                        else None
                    ),
                    from_entity_id=(
                        int(result["from_entity_id"])
                        if result["from_entity_id"] is not None
                        else None
                    ),
                    to_entity_id=(
                        int(result["to_entity_id"])
                        if result["to_entity_id"] is not None
                        else None
                    ),
                    from_name=str(result["from_name"]) if result["from_name"] is not None else None,
                    to_name=str(result["to_name"]) if result["to_name"] is not None else None,
                    relation_type=(
                        str(result["relation_type"])
                        if result["relation_type"] is not None
                        else None
                    ),
                    directionality=(
                        str(result["directionality"])
                        if result["directionality"] is not None
                        else None
                    ),
                    relation_semantics=(
                        str(result["relation_semantics"])
                        if result["relation_semantics"] is not None
                        else None
                    ),
                )
            )
        return rows, total

    def fetch_latest_entities(
        self,
        run_id: str,
        *,
        entity_type: str | None = None,
    ) -> list[EntitySnapshotRow]:
        """2026-08-07 用于读取最新章节图版本中的实体状态"""
        boundary = self.resolve_graph_version(run_id)
        if boundary is None:
            return []
        rows = self.fetch_entity_snapshots(boundary)
        return [
            row
            for row in rows
            if (entity_type is None or row.entity_type == entity_type)
            and (
                row.entity_type != "character"
                or is_global_character_surface_name(row.name)
            )
        ]

    def fetch_latest_relations(
        self,
        run_id: str,
        *,
        active_only: bool = True,
    ) -> list[RelationSnapshotRow]:
        """2026-08-07 用于读取最新章节图版本中的关系快照"""
        boundary = self.resolve_graph_version(run_id)
        if boundary is None:
            return []
        return self.fetch_relation_snapshots(boundary, active_only=active_only)

    def fetch_relation_history(self, run_id: str) -> list[RelationSnapshotRow]:
        """2026-08-07 用于按章节顺序读取全部不可变关系版本"""
        entity_names = {
            int(row.entity_id): str(row.canonical_name)
            for row in self.session.execute(
                select(GraphEntity).where(GraphEntity.run_id == run_id)
            ).scalars()
        }
        first_seen_by_relation: dict[str, int] = {}
        rows: list[RelationSnapshotRow] = []
        statement = (
            select(GraphRelationVersion, GraphRelation, GraphVersion)
            .join(GraphRelation, GraphRelation.relation_id == GraphRelationVersion.relation_id)
            .join(GraphVersion, GraphVersion.graph_version_id == GraphRelationVersion.graph_version_id)
            .where(GraphRelationVersion.run_id == run_id)
            .order_by(
                GraphVersion.chapter_order,
                GraphRelationVersion.relation_version_id,
            )
        )
        for version, relation, graph_version in self.session.execute(statement).all():
            relation_id = str(relation.relation_id)
            first_seen_by_relation.setdefault(relation_id, int(graph_version.first_chapter_id))
            rows.append(
                RelationSnapshotRow(
                    relation_version_id=int(version.relation_version_id),
                    graph_version_id=str(version.graph_version_id),
                    chapter_id=int(version.chapter_id),
                    relation_id=relation_id,
                    relation_revision=int(version.relation_revision),
                    from_entity_id=int(relation.from_entity_id),
                    to_entity_id=int(relation.to_entity_id),
                    from_name=entity_names[int(relation.from_entity_id)],
                    to_name=entity_names[int(relation.to_entity_id)],
                    relation_type=str(version.relation_type),
                    directionality=str(relation.directionality),
                    relation_semantics=str(relation.relation_semantics),
                    attributes=dict(version.attributes),
                    is_active=bool(version.is_active),
                    changes=list(version.changes),
                    first_seen_chapter=first_seen_by_relation[relation_id],
                    last_seen_chapter=int(graph_version.last_chapter_id),
                )
            )
        return rows

    def fetch_relation_changes(
        self,
        run_id: str,
        *,
        limit: int | None = None,
    ) -> list[GraphChangeRow]:
        """2026-08-07 用于读取诊断时间轴需要的关系变化事实"""
        rows, _total = self.fetch_changes(run_id, limit=None)
        relation_rows = [row for row in rows if row.change_kind == "relation"]
        return relation_rows if limit is None else relation_rows[:limit]

    def count_graph_versions(self, run_id: str) -> int:
        """2026-08-07 用于统计当前 run 已成功提交的章节图版本数量"""
        return int(
            self.session.execute(
                select(func.count())
                .select_from(GraphVersion)
                .where(GraphVersion.run_id == run_id)
            ).scalar_one()
            or 0
        )
