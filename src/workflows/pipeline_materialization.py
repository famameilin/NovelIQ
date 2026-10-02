"""从已 ACK 的分区快照批量物化读模型，释放事务不再逐章扫描全图"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.annotation.identity import stable_uuid, text_digest
from src.storage.models import (
    AnalysisCutoff,
    Chapter,
    ChapterAnnotationRecord,
    CutoffPartition,
    DialogueRecord,
    EntityState,
    EventEdge,
    EventNode,
    FormalArtifact,
    GraphEntity,
    GraphFact,
    GraphRelation,
    Paragraph,
    RelationState,
    TextEvidenceRecord,
)
from src.storage.repositories.event_order import formal_event_ordinals
from src.workflows.pipeline_materialization_domains import (
    event_edge,
    materialize_events,
    materialize_identity,
    materialize_relations,
)


class CutoffMaterializer:
    """索引在一次释放内共享；每个实体和关系的历史只归并一次"""

    def __init__(self, session: Session, cutoff: AnalysisCutoff) -> None:
        self.session = session
        self.cutoff = cutoff
        self.partitions = list(session.execute(select(CutoffPartition).where(
            CutoffPartition.cutoff_hash == cutoff.cutoff_hash,
        ).order_by(CutoffPartition.partition_key)).scalars())
        self.chapters = {row.chapter_id: row for row in session.execute(select(Chapter).where(
            Chapter.run_id == cutoff.run_id,
        )).scalars()}
        ordered = sorted(self.chapters.values(), key=lambda row: (row.sequence, row.chapter_id))
        self.orders = {row.chapter_id: index for index, row in enumerate(ordered, start=1)}
        self.annotations = {row.chapter_id: row for row in session.execute(select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == cutoff.run_id,
        )).scalars()}
        self.event_ordinals = formal_event_ordinals(self.annotations.values())
        self.entities = {row.entity_id: row for row in
                         session.execute(select(GraphEntity).where(GraphEntity.run_id == cutoff.run_id)).scalars()}
        self.paragraphs = {row.paragraph_id: row for row in session.execute(select(Paragraph).where(
            Paragraph.run_id == cutoff.run_id,
        )).scalars()}
        self.evidence = {row.evidence_id: row for row in session.execute(select(TextEvidenceRecord).where(
            TextEvidenceRecord.run_id == cutoff.run_id,
        )).scalars()}
        self.facts = {row.fact_id: row for row in session.execute(select(GraphFact).where(
            GraphFact.run_id == cutoff.run_id,
        )).scalars()}
        self.events = {row.event_id: row for row in session.execute(select(EventNode).where(
            EventNode.run_id == cutoff.run_id,
        )).scalars()}
        self.edges = {(row.source_event_id, row.target_event_id): row for row in
                      session.execute(select(EventEdge).where(EventEdge.run_id == cutoff.run_id)).scalars()}
        self.active_edge_keys: set[tuple[str, str]] = set()
        self.entity_states = {(row.chapter_id, row.entity_id): row for row in session.execute(select(EntityState).where(
            EntityState.run_id == cutoff.run_id,
        )).scalars()}
        self.relations = {row.relation_id: row for row in session.execute(select(GraphRelation).where(
            GraphRelation.run_id == cutoff.run_id,
        )).scalars()}
        self.relation_states = {(row.chapter_id, row.relation_id): row for row in
                                session.execute(select(RelationState).where(
                                    RelationState.run_id == cutoff.run_id,
                                )).scalars()}

    def text_evidence(self, assertion: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for evidence_id in assertion["evidence_ids"]:
            record = self.evidence[evidence_id]
            paragraph = self.paragraphs[record.paragraph_id]
            if not 0 <= record.char_start < record.char_end <= len(paragraph.text) or (
                record.text_hash != text_digest(paragraph.text[record.char_start:record.char_end])
            ):
                raise ValueError("原文证据区间或哈希无效")
            result.append({"evidence_id": evidence_id, "paragraph_ids": [record.paragraph_id],
                           "chapter_id": record.chapter_id,
                           "char_start": paragraph.local_start_char + record.char_start,
                           "char_end": paragraph.local_start_char + record.char_end,
                           "text_hash": record.text_hash, "source_manifest_hash": record.source_manifest_hash})
        return result

    def entity(self, identifier: str | None) -> GraphEntity | None:
        return self.entities.get(identifier) if identifier else None

    def descriptor(self, entity: GraphEntity | None) -> dict[str, Any] | None:
        entity = self.canonical_entity(entity)
        return ({"entity_id": entity.entity_id, "name": entity.canonical_name, "entity_type": entity.entity_type}
                if entity is not None else None)

    def canonical_entity(self, entity: GraphEntity | None) -> GraphEntity | None:
        if entity is None:
            return None
        canonical_id = entity.attributes.get("canonical_entity_id")
        if entity.attributes.get("identity_status") != "contested" and canonical_id:
            entity = self.entities.get(str(canonical_id), entity)
        return entity

    def fact(
        self, assertion: dict[str, Any], *, domain: str, predicate: str,
        subject: GraphEntity | None = None, target: GraphEntity | None = None,
        content: dict[str, Any], value: Any = None, event_id: str | None = None,
    ) -> GraphFact:
        fact_id = stable_uuid("partition-fact", assertion["command_ids"][0])
        existing = self.facts.get(fact_id)
        if existing is not None:
            existing.evidence = self.text_evidence(assertion)
            return existing
        chapter_id = assertion["chapter_id"]
        annotation = self.annotations[chapter_id]
        continuity = assertion["payload"].get("origin") != "chapter_link" and assertion["kind"] in {
            "relation_change", "dialogue_attribution", "event_link", "identity_binding", "entity_type_resolution",
        }
        row = GraphFact(
            run_id=self.cutoff.run_id, chapter_id=chapter_id, fact_id=fact_id, fact_type=domain,
            subject_entity_id=subject.entity_id if subject else None, predicate=predicate,
            object=self.descriptor(target), value=value,
            participants=[{"role": role, "entity": self.descriptor(entity)}
                          for role, entity in (("from", subject), ("to", target)) if entity is not None],
            scope=f"chapter:{chapter_id}", story_time=None, assertion="affirmed", confidence="medium",
            content={"kind": domain, "chapter_id": chapter_id, **content}, effective_chapter_id=chapter_id,
            source_kind="continuity" if continuity else "annotation", annotation_id=annotation.annotation_id,
            payload_path=f"commands/{assertion['command_ids'][0]}", event_id=event_id,
            evidence=self.text_evidence(assertion),
        )
        self.session.add(row)
        self.facts[fact_id] = row
        return row

    def materialize_entities(self) -> None:
        for partition in self.partitions:
            if not partition.partition_key.startswith("entity:"):
                continue
            assertions = partition.projection["assertions"]
            mentions = [item for item in assertions if item["kind"] == "entity_mention"
                        and item["outcome"] == "accepted"]
            if not mentions:
                identifier = next((item["payload"]["entity_id"] for item in assertions
                                   if item["kind"] == "entity_mention"), None)
                entity = self.entity(identifier)
                if entity is not None:
                    entity.attributes = {**entity.attributes, "identity_status": "contested"}
                continue
            first = mentions[0]
            name = first["payload"]["name"]
            key = first["payload"]["entity_id"]
            entity = self.entities.get(key)
            if entity is None:
                entity = GraphEntity(entity_id=key, run_id=self.cutoff.run_id,
                                     canonical_name=name, entity_type=first["payload"]["entity_type"], tags=[],
                                     attributes={}, first_seen_chapter=first["chapter_id"],
                                     last_seen_chapter=mentions[-1]["chapter_id"])
                self.session.add(entity)
                self.session.flush([entity])
                self.entities[key] = entity
            state: dict[str, Any] = {}
            tags: list[str] = []
            states: dict[int, dict[str, Any]] = {}
            changes: dict[int, list[dict[str, Any]]] = defaultdict(list)
            type_resolutions = [item for item in assertions
                                if item["kind"] == "entity_type_resolution" and item["outcome"] == "accepted"]
            selected_type = type_resolutions[0]["payload"]["entity_type"] if type_resolutions else None
            for assertion in assertions:
                if assertion["outcome"] != "accepted":
                    continue
                payload = assertion["payload"]
                chapter_id = assertion["chapter_id"]
                if assertion["kind"] == "entity_mention":
                    updates = {"entity_type": payload["entity_type"], **payload.get("attributes", {})}
                    if payload.get("description") is not None:
                        updates["description"] = payload["description"]
                    tags = sorted(set(tags) | set(payload.get("tags", [])))
                    self.fact(assertion, domain="entity", predicate="entity_mention", subject=entity,
                              content={"entity": self.descriptor(entity), **updates}, value=updates)
                elif assertion["kind"] == "character_observation":
                    updates = {field: payload[field] for field in ("role_function", "action", "emotion")}
                    self.fact(assertion, domain="character_observation", predicate="observation", subject=entity,
                              content={"entity": self.descriptor(entity), **updates}, value=updates)
                elif assertion["kind"] == "entity_type_resolution":
                    updates = {"entity_type": payload["entity_type"]}
                    self.fact(assertion, domain="identity", predicate="type_conflict", subject=entity,
                              content=payload, value=updates)
                else:
                    continue
                for field, after in updates.items():
                    before = state.get(field)
                    if before == after:
                        continue
                    if after is None:
                        state.pop(field, None)
                    else:
                        state[field] = after
                    changes[chapter_id].append({"field": field, "before": before, "after": after,
                                               "chapter_id": chapter_id,
                                               "fact_id": stable_uuid("partition-fact", assertion["command_ids"][0])})
                states[chapter_id] = dict(state)
            identity_status = "contested" if partition.projection["contested"] else "known"
            entity.attributes = {**state, "identity_status": identity_status}
            entity.entity_type = selected_type or first["payload"]["entity_type"]
            if selected_type:
                entity.attributes = {**entity.attributes, "entity_type": selected_type}
                for chapter_state in states.values():
                    chapter_state["entity_type"] = selected_type
            entity.tags = tags
            entity.last_seen_chapter = mentions[-1]["chapter_id"]
            for chapter_id, chapter_changes in changes.items():
                row = self.entity_states.get((chapter_id, entity.entity_id))
                if row is None:
                    self.session.add(EntityState(run_id=self.cutoff.run_id, chapter_id=chapter_id,
                                                 entity_id=entity.entity_id, state=states[chapter_id],
                                                 changes=chapter_changes))
                else:
                    row.state, row.changes = states[chapter_id], chapter_changes
        self.session.flush()

    def materialize_identity(self) -> None:
        """全 cutoff 只选举一次代表；正式名称、UUID 与事实不随绑定变化"""
        materialize_identity(self)

    def materialize_events(self) -> None:
        # 2026-10-02 拆分：事件树领域实现（含 event_edge 与拓扑环检测）迁至
        # pipeline_materialization_domains.materialize_events，此处仅委托
        materialize_events(self)

    def materialize_relations(self) -> None:
        # 2026-10-02 拆分：关系领域实现迁至 pipeline_materialization_domains.materialize_relations，此处仅委托
        materialize_relations(self)

    def event_edge(self, assertion: dict[str, Any], source_id: str, target_id: str, edge_type: str) -> None:
        # 2026-10-02 拆分：事件边登记实现迁至 pipeline_materialization_domains.event_edge，此处仅委托
        event_edge(self, assertion, source_id, target_id, edge_type)

    def materialize_dialogues(self) -> None:
        existing = {row.candidate_key: row for row in self.session.execute(select(DialogueRecord).where(
            DialogueRecord.run_id == self.cutoff.run_id,
        )).scalars()}
        for partition in self.partitions:
            if not partition.partition_key.startswith("dialogue:"):
                continue
            for assertion in partition.projection["assertions"]:
                if assertion["kind"] != "dialogue":
                    continue
                payload = assertion["payload"]
                key = payload["candidate_key"]
                if key in existing:
                    speaker = self.descriptor(self.entity(payload.get("speaker_entity_id")))
                    existing[key].speaker = speaker["entity_id"] if speaker else None
                    continue
                speaker_entity = self.canonical_entity(self.entity(payload.get("speaker_entity_id")))
                anchors = [row for row in self.events.values() if row.chapter_id == assertion["chapter_id"]
                           and row.char_start <= payload["start"] and row.char_end >= payload["end"]]
                row = DialogueRecord(
                    dialogue_id=stable_uuid(self.cutoff.run_id, "dialogue", key), run_id=self.cutoff.run_id,
                    chapter_id=assertion["chapter_id"], candidate_key=key, content=payload["content"],
                    start=payload["start"], end=payload["end"],
                    speaker=speaker_entity.entity_id if speaker_entity else None,
                    tone=payload.get("tone"), is_inner_monologue=payload.get("is_inner_monologue", False),
                    confidence="medium", event_id=anchors[0].event_id if len(anchors) == 1 else None,
                )
                self.session.add(row)
                existing[key] = row


def materialize_cutoff(session: Session, cutoff: AnalysisCutoff) -> None:
    """正式读模型与连续性领域派生在 released 同一事务切换"""
    materializer = CutoffMaterializer(session, cutoff)
    materializer.materialize_entities()
    materializer.materialize_identity()
    materializer.materialize_events()
    materializer.materialize_relations()
    materializer.materialize_dialogues()
    session.flush()
    for artifact in session.execute(select(FormalArtifact).where(
        FormalArtifact.annotation_id.in_([value[0] for value in cutoff.manifest["formal"]]),
    )).scalars():
        artifact.materialized = True
