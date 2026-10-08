"""章节图谱查询仓储"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import (
    AnalysisOutput,
    Chapter,
    EntityState,
    GraphEntity,
    GraphFact,
    GraphRelation,
    RelationState,
)
from src.storage.models.graph import ChapterBoundary
from src.storage.repositories.base import BaseRepository


@dataclass(frozen=True, slots=True)
class EntitySnapshotRow:
    """2026-08-19 用于返回目标章节边界的实体身份与完整状态

    2026-09-19 entity_id 随图实体主键改 uuid（String(36)）。
    """

    entity_id: str
    name: str
    entity_type: str
    tags: list[str]
    attributes: dict[str, Any]
    first_seen_chapter: int
    last_seen_chapter: int
    state_chapter_id: int | None
    state: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RelationSnapshotRow:
    """2026-08-19 用于返回目标章节边界的稳定关系状态"""

    chapter_id: int
    relation_id: str
    from_entity_id: str
    to_entity_id: str
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
    """2026-08-19 用于返回按章节与事实拆分的实体或关系变化"""

    change_id: str
    change_kind: Literal["state", "relation"]
    chapter_id: int
    chapter_order: int
    fact_id: str
    effective_chapter_id: int
    confidence: str
    changes: list[dict[str, Any]]
    entity_id: str | None = None
    entity_name: str | None = None
    entity_type: str | None = None
    relation_id: str | None = None
    from_entity_id: str | None = None
    to_entity_id: str | None = None
    from_name: str | None = None
    to_name: str | None = None
    relation_type: str | None = None
    directionality: str | None = None
    relation_semantics: str | None = None


@dataclass(frozen=True, slots=True)
class GraphSnapshotRow:
    """2026-08-19 用于承载一个章节边界的实体与有效关系"""

    chapter_boundary: ChapterBoundary
    entities: list[EntitySnapshotRow]
    relations: list[RelationSnapshotRow]


class GraphRepository(BaseRepository[GraphFact]):
    def __init__(self, session: Session, *, internal: bool = False) -> None:
        super().__init__(session)
        self.internal = internal

    def _require_visible(self, run_id: str) -> None:
        """只有释放事务内部可绕过最终边界，普通查询不能读未发布的物化状态"""
        from src.storage.models import AnalysisRun

        if self.session.get(AnalysisRun, run_id) is None:
            raise ValueError(f"run_id={run_id} 不存在")

    def _filter_current_facts(self, run_id: str, facts: list[GraphFact]) -> list[GraphFact]:
        from src.storage.models import AnnotationWork

        saved = set(
            self.session.execute(
                select(AnnotationWork.work_id).where(AnnotationWork.run_id == run_id, AnnotationWork.state == "saved")
            ).scalars()
        )
        return [row for row in facts if row.author_work_id in saved]

    def _chapter_rows(self, run_id: str) -> list[Chapter]:
        """2026-08-19 用于读取当前运行的有正文章节并确定顺序"""
        self._require_visible(run_id)
        return list(
            self.session.execute(
                select(Chapter)
                .where(Chapter.run_id == run_id, Chapter.text.isnot(None))
                .order_by(Chapter.sequence, Chapter.chapter_id)
            ).scalars()
        )

    def _chapter_order_map(self, run_id: str) -> dict[int, int]:
        """2026-08-19 用于把章节身份映射为历史排序"""
        return {int(chapter.chapter_id): index for index, chapter in enumerate(self._chapter_rows(run_id), start=1)}

    def resolve_chapter_boundary(self, run_id: str, *, chapter_id: int | None = None) -> ChapterBoundary | None:
        """2026-08-19 用于解析显式章节或当前运行最后章节"""
        from src.storage.models import AnnotationWork

        chapters = self._chapter_rows(run_id)
        records = {
            row.chapter_id: row
            for row in self.session.execute(
                select(AnalysisOutput)
                .join(AnnotationWork, AnnotationWork.work_id == AnalysisOutput.work_id)
                .where(
                    AnalysisOutput.run_id == run_id,
                    AnalysisOutput.kind == "chapter_annotation",
                    AnnotationWork.state == "saved",
                    AnnotationWork.invocation_id == AnalysisOutput.invocation_id,
                )
            ).scalars()
        }
        target = (
            next((chapter for chapter in reversed(chapters) if chapter.chapter_id in records), None)
            if chapter_id is None
            else next((chapter for chapter in chapters if chapter.chapter_id == chapter_id), None)
        )
        if target is None or target.chapter_id not in records:
            return None
        return ChapterBoundary(
            run_id=run_id,
            chapter_id=target.chapter_id,
            chapter_order=chapters.index(target) + 1,
            first_chapter_id=target.chapter_id,
            last_chapter_id=target.chapter_id,
            annotation_id=records[target.chapter_id].output_id,
        )

    def resolve_persisted_boundary(self, run_id: str) -> ChapterBoundary | None:
        """2026-08-23 用于构造覆盖全部已提交数据的历史边界（不依赖 annotation record）"""
        chapters = self._chapter_rows(run_id)
        if not chapters:
            return None
        return ChapterBoundary(
            run_id=run_id,
            chapter_id=int(chapters[-1].chapter_id),
            chapter_order=len(chapters),
            first_chapter_id=int(chapters[0].chapter_id),
            last_chapter_id=int(chapters[-1].chapter_id),
            annotation_id="",
        )

    def _latest_state_rows(self, boundary: ChapterBoundary) -> dict[str, EntityState]:
        """2026-08-19 用于读取目标章节及以前每个实体最近的状态"""
        order_map = self._chapter_order_map(boundary.run_id)
        rows = self.session.execute(select(EntityState).where(EntityState.run_id == boundary.run_id)).scalars()
        latest: dict[str, EntityState] = {}
        for row in rows:
            row_order = order_map.get(int(row.chapter_id), 0)
            if row_order > boundary.chapter_order:
                continue
            current = latest.get(row.entity_id)
            if current is None or order_map.get(int(current.chapter_id), 0) < row_order:
                latest[row.entity_id] = row
        return latest

    def fetch_entity_snapshots(self, boundary: ChapterBoundary) -> list[EntitySnapshotRow]:
        """2026-08-19 用于选择目标章节以前最近状态并继承无变化实体"""
        order_map = self._chapter_order_map(boundary.run_id)
        latest_states = self._latest_state_rows(boundary)
        entities = self.session.execute(select(GraphEntity).where(GraphEntity.run_id == boundary.run_id)).scalars()
        result: list[EntitySnapshotRow] = []
        for entity in sorted(entities, key=lambda row: str(row.entity_id)):
            first_order = order_map.get(int(entity.first_seen_chapter), 0)
            if first_order == 0 or first_order > boundary.chapter_order:
                continue
            state = latest_states.get(entity.entity_id)
            result.append(
                EntitySnapshotRow(
                    entity_id=str(entity.entity_id),
                    name=str(entity.canonical_name),
                    entity_type=str(entity.entity_type),
                    tags=list(state.state.get("tags", entity.tags) if state else entity.tags),
                    attributes=dict(state.state.get("attributes", {}) if state else entity.attributes),
                    first_seen_chapter=int(entity.first_seen_chapter),
                    last_seen_chapter=int(entity.last_seen_chapter),
                    state_chapter_id=int(state.chapter_id) if state is not None else None,
                    state=dict(state.state) if state is not None else {},
                )
            )
        return result

    def _latest_relation_states(self, boundary: ChapterBoundary) -> dict[str, RelationState]:
        """2026-08-19 用于读取目标章节及以前每条关系最近状态"""
        order_map = self._chapter_order_map(boundary.run_id)
        rows = self.session.execute(select(RelationState).where(RelationState.run_id == boundary.run_id)).scalars()
        latest: dict[str, RelationState] = {}
        for row in rows:
            row_order = order_map.get(int(row.chapter_id), 0)
            if row_order > boundary.chapter_order:
                continue
            current = latest.get(str(row.relation_id))
            if current is None or order_map.get(int(current.chapter_id), 0) < row_order:
                latest[str(row.relation_id)] = row
        return latest

    def fetch_relation_snapshots(
        self, boundary: ChapterBoundary, *, active_only: bool = True
    ) -> list[RelationSnapshotRow]:
        """2026-08-19 用于选择目标章节以前最近关系状态并过滤活动状态"""
        entity_names = {
            str(row.entity_id): str(row.canonical_name)
            for row in self.session.execute(select(GraphEntity).where(GraphEntity.run_id == boundary.run_id)).scalars()
        }
        relations = {
            str(row.relation_id): row
            for row in self.session.execute(
                select(GraphRelation).where(GraphRelation.run_id == boundary.run_id)
            ).scalars()
        }
        first_seen: dict[str, int] = {}
        for state in self.session.execute(
            select(RelationState).where(RelationState.run_id == boundary.run_id)
        ).scalars():
            relation_id = str(state.relation_id)
            first_seen[relation_id] = min(first_seen.get(relation_id, state.chapter_id), state.chapter_id)
        result: list[RelationSnapshotRow] = []
        for relation_id, state in self._latest_relation_states(boundary).items():
            if active_only and not state.is_active:
                continue
            relation = relations.get(relation_id)
            if relation is None:
                continue
            result.append(
                RelationSnapshotRow(
                    chapter_id=int(state.chapter_id),
                    relation_id=relation_id,
                    from_entity_id=str(relation.from_entity_id),
                    to_entity_id=str(relation.to_entity_id),
                    from_name=entity_names[str(relation.from_entity_id)],
                    to_name=entity_names[str(relation.to_entity_id)],
                    relation_type=str(state.relation_type),
                    directionality=str(relation.directionality),
                    relation_semantics=str(relation.relation_semantics),
                    attributes=dict(state.attributes),
                    is_active=bool(state.is_active),
                    changes=list(state.changes),
                    first_seen_chapter=int(first_seen.get(relation_id, state.chapter_id)),
                    last_seen_chapter=int(state.chapter_id),
                )
            )
        return result

    def fetch_snapshot(self, run_id: str, *, chapter_id: int | None = None) -> GraphSnapshotRow | None:
        """2026-08-19 用于返回目标章节边界的实体状态与有效关系"""
        boundary = self.resolve_chapter_boundary(run_id, chapter_id=chapter_id)
        if boundary is None:
            return None
        return GraphSnapshotRow(
            chapter_boundary=boundary,
            entities=self.fetch_entity_snapshots(boundary),
            relations=self.fetch_relation_snapshots(boundary, active_only=True),
        )

    def fetch_changes(
        self,
        run_id: str,
        *,
        chapter_id: int | None = None,
        offset: int = 0,
        limit: int | None = 200,
    ) -> tuple[list[GraphChangeRow], int]:
        """2026-08-19 用于按章节倒序分页返回状态和关系变化"""
        if offset < 0:
            raise ValueError("graph changes offset 不能小于 0")
        boundary = self.resolve_chapter_boundary(run_id, chapter_id=chapter_id)
        if boundary is None:
            return [], 0
        order_map = self._chapter_order_map(run_id)
        facts = {
            (int(row.chapter_id), str(row.fact_id)): row
            for row in self._filter_current_facts(
                run_id, list(self.session.execute(select(GraphFact).where(GraphFact.run_id == run_id)).scalars())
            )
        }
        entity_map = {
            str(row.entity_id): row
            for row in self.session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars()
        }
        relation_map = {
            str(row.relation_id): row
            for row in self.session.execute(select(GraphRelation).where(GraphRelation.run_id == run_id)).scalars()
        }
        changes: list[GraphChangeRow] = []
        for state in self.session.execute(select(EntityState).where(EntityState.run_id == run_id)).scalars():
            state_order = order_map.get(int(state.chapter_id), 0)
            if state_order == 0 or state_order > boundary.chapter_order:
                continue
            if chapter_id is not None and int(state.chapter_id) != chapter_id:
                continue
            entity = entity_map.get(str(state.entity_id))
            if entity is None:
                continue
            for index, change in enumerate(state.changes):
                fact_id = str(change.get("fact_id", ""))
                fact = facts.get((int(change.get("chapter_id", state.chapter_id)), fact_id))
                if fact is None:
                    continue
                changes.append(
                    GraphChangeRow(
                        change_id=f"state:{run_id}:{state.chapter_id}:{state.entity_id}:{fact_id}:{index}",
                        change_kind="state",
                        chapter_id=int(state.chapter_id),
                        chapter_order=state_order,
                        fact_id=fact_id,
                        effective_chapter_id=int(fact.effective_chapter_id),
                        confidence=str(fact.confidence),
                        changes=[dict(change)],
                        entity_id=str(entity.entity_id),
                        entity_name=str(entity.canonical_name),
                        entity_type=str(entity.entity_type),
                    )
                )
        for relation_state in self.session.execute(
            select(RelationState).where(RelationState.run_id == run_id)
        ).scalars():
            state_order = order_map.get(int(relation_state.chapter_id), 0)
            if state_order == 0 or state_order > boundary.chapter_order:
                continue
            if chapter_id is not None and int(relation_state.chapter_id) != chapter_id:
                continue
            relation = relation_map.get(str(relation_state.relation_id))
            if relation is None:
                continue
            from_entity = entity_map.get(str(relation.from_entity_id))
            to_entity = entity_map.get(str(relation.to_entity_id))
            for index, change in enumerate(relation_state.changes):
                fact_id = str(change.get("fact_id", ""))
                fact = facts.get((int(change.get("chapter_id", relation_state.chapter_id)), fact_id))
                if fact is None:
                    continue
                changes.append(
                    GraphChangeRow(
                        change_id=f"relation:{run_id}:{relation_state.chapter_id}:{relation_state.relation_id}:{fact_id}:{index}",
                        change_kind="relation",
                        chapter_id=int(relation_state.chapter_id),
                        chapter_order=state_order,
                        fact_id=fact_id,
                        effective_chapter_id=int(fact.effective_chapter_id),
                        confidence=str(fact.confidence),
                        changes=[dict(change)],
                        relation_id=str(relation.relation_id),
                        from_entity_id=str(relation.from_entity_id),
                        to_entity_id=str(relation.to_entity_id),
                        from_name=str(from_entity.canonical_name) if from_entity else None,
                        to_name=str(to_entity.canonical_name) if to_entity else None,
                        relation_type=str(relation_state.relation_type),
                        directionality=str(relation.directionality),
                        relation_semantics=str(relation.relation_semantics),
                    )
                )
        changes.sort(key=lambda row: (row.chapter_order, row.change_kind, row.change_id), reverse=True)
        total = len(changes)
        end = None if limit is None else offset + max(1, min(limit, 200))
        return changes[offset:end], total

    def fetch_latest_entity_rows(self, run_id: str, *, entity_type: str | None = None) -> list[EntitySnapshotRow]:
        """2026-08-19 用于读取当前章节边界的实体状态"""
        boundary = self.resolve_persisted_boundary(run_id)
        if boundary is None:
            return []
        return [
            row
            for row in self.fetch_entity_snapshots(boundary)
            if (entity_type is None or row.entity_type == entity_type)
        ]

    def fetch_latest_relations(self, run_id: str, *, active_only: bool = True) -> list[RelationSnapshotRow]:
        """2026-08-19 用于读取当前章节边界的关系状态"""
        boundary = self.resolve_persisted_boundary(run_id)
        return [] if boundary is None else self.fetch_relation_snapshots(boundary, active_only=active_only)

    def fetch_relation_history(self, run_id: str) -> list[RelationSnapshotRow]:
        """按章节顺序读取关系历史，共享实体与关系索引，避免逐状态重建全图"""
        order_map = self._chapter_order_map(run_id)
        entity_names = {
            str(row.entity_id): str(row.canonical_name)
            for row in self.session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars()
        }
        relations = {
            str(row.relation_id): row
            for row in self.session.execute(select(GraphRelation).where(GraphRelation.run_id == run_id)).scalars()
        }
        states = list(self.session.execute(select(RelationState).where(RelationState.run_id == run_id)).scalars())
        first_seen: dict[str, int] = {}
        for state in states:
            key = str(state.relation_id)
            first_seen[key] = min(first_seen.get(key, int(state.chapter_id)), int(state.chapter_id))
        rows: list[RelationSnapshotRow] = []
        for state in sorted(states, key=lambda row: order_map.get(int(row.chapter_id), 0)):
            relation_id = str(state.relation_id)
            relation = relations.get(relation_id)
            if relation is None:
                continue
            rows.append(
                RelationSnapshotRow(
                    chapter_id=int(state.chapter_id),
                    relation_id=relation_id,
                    from_entity_id=str(relation.from_entity_id),
                    to_entity_id=str(relation.to_entity_id),
                    from_name=entity_names[str(relation.from_entity_id)],
                    to_name=entity_names[str(relation.to_entity_id)],
                    relation_type=str(state.relation_type),
                    directionality=str(relation.directionality),
                    relation_semantics=str(relation.relation_semantics),
                    attributes=dict(state.attributes),
                    is_active=bool(state.is_active),
                    changes=list(state.changes),
                    first_seen_chapter=first_seen[relation_id],
                    last_seen_chapter=int(state.chapter_id),
                )
            )
        return rows

    def fetch_relation_changes(self, run_id: str, *, limit: int | None = None) -> list[GraphChangeRow]:
        """2026-08-19 用于读取诊断时间轴所需的关系变化事实"""
        rows, _total = self.fetch_changes(run_id, limit=None)
        relation_rows = [row for row in rows if row.change_kind == "relation"]
        return relation_rows if limit is None else relation_rows[:limit]

    def count_chapters(self, run_id: str) -> int:
        """2026-08-19 用于统计当前运行已提交的章节数量"""
        return len(self._chapter_rows(run_id))
