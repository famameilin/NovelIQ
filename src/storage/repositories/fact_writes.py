from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as Storage

from src.storage.records.facts import FactSave as FactContribution
from src.storage.repositories.queries import fact_graph_graph as _queries


class FactWriter:
    def __init__(self, run_id):
        self.run_scope = run_id

    def ensure_entity_rows(self, session: Storage, frozen: FactContribution) -> None:
        "在跨域写入前先落实体身份行（事件参与者等外键依赖同一批身份）"
        from src.storage.models import GraphEntity

        _queries.fact_graph_graph_ensure_entity_rows_1(session, self.run_scope)
        for identifier, value in frozen.snapshot()["entities"].items():
            if _queries.fact_graph_graph_ensure_entity_rows_2(session, identifier) is None:
                session.add(
                    GraphEntity(
                        entity_id=identifier,
                        run_id=self.run_scope,
                        canonical_name=value["name"],
                        entity_type=value["entity_type"],
                    )
                )
        session.flush()

    def save_work(self, session: Storage, frozen: FactContribution, annotation_id: str) -> None:
        "保存自己的不可变操作；实体与关系状态不落缓存，由正式贡献按读侧折叠重建"
        from src.storage.models import FactEntityTag, GraphFact, GraphRelation, SourceEvidence
        from src.storage.records.evidence import evidence_for

        _queries.fact_graph_graph_save_work_1(session, self.run_scope)
        del annotation_id
        execution = _queries.fact_graph_graph_save_work_2(session, frozen.agent_id)
        if execution is None or execution.run_id != self.run_scope:
            raise ValueError(f"事实贡献缺少真实执行身份: agent_id={frozen.agent_id}")
        effective_chapter_id = int(frozen.chapter_id) if frozen.chapter_id is not None else None
        contribution = frozen.snapshot()
        agent_id = frozen.agent_id
        entities = contribution["entities"]
        self.ensure_entity_rows(session, frozen)
        if _queries.fact_graph_graph_save_work_3(session, agent_id) is not None:
            return
        operations: list[tuple[str, dict[str, Any]]] = []
        operations += [("entity", op) for op in contribution["entity_ops"]]
        operations += [("relation", op) for op in contribution["relation_assert_ops"]]
        operations += [("entity_reference", value) for _, value in sorted(entities.items())]
        for index, (kind, op) in enumerate(operations):
            fact: GraphFact | None = None
            if kind == "entity_reference":
                fact = GraphFact(
                    direct_producer_agent_id=agent_id,
                    operation_order=index,
                    effective_chapter_id=effective_chapter_id,
                    entity_id=str(op["entity_id"]),
                    tags_submitted=False,
                )
            elif kind == "entity":
                entity_id = str(op["entity_id"])
                entity = _queries.fact_graph_graph_save_work_4(session, entity_id)
                if entity is not None and op["name"] != entity.canonical_name:
                    entity.canonical_name = op["name"]
                fields = op["submitted_fields"]
                description = op.get("description") if "description" in fields else None
                representative: bool | None = op.get("representative") if "representative" in fields else None
                fact = GraphFact(
                    direct_producer_agent_id=agent_id,
                    operation_order=index,
                    effective_chapter_id=effective_chapter_id,
                    entity_id=entity_id,
                    description_action="set"
                    if description is not None
                    else "omit"
                    if "description" in fields
                    else None,
                    description_value=description,
                    representative_action="set" if representative else "clear" if representative is False else None,
                    representative_value=True if representative else None,
                    tags_submitted=True if "tags" in fields else None,
                )
            elif kind == "relation":
                from_id = str(op["from_entity_id"])
                to_id = str(op["to_entity_id"])
                identifier = str(op["relation_id"])
                if _queries.fact_graph_graph_save_work_5(session, identifier) is None:
                    session.add(
                        GraphRelation(
                            relation_id=identifier,
                            from_entity_id=from_id,
                            to_entity_id=to_id,
                            relation_type=str(op["relation_type"]),
                        )
                    )
                    session.flush()
                change_kind = op.get("change_kind", "assert")
                fact = GraphFact(
                    direct_producer_agent_id=agent_id,
                    operation_order=index,
                    effective_chapter_id=effective_chapter_id,
                    relation_id=identifier,
                    relation_change_kind=change_kind,
                    identity_kind=op.get("identity_kind"),
                    reason=op.get("reason"),
                )
            if fact is None:
                continue
            session.add(fact)
            session.flush()
            if kind == "entity" and "tags" in op["submitted_fields"]:
                for ordinal, tag in enumerate(op.get("tags") or []):
                    session.add(FactEntityTag(graph_fact_id=fact.graph_fact_id, tag_ordinal=ordinal, tag=str(tag)))
            self._write_evidence(session, fact.graph_fact_id, SourceEvidence, evidence_for(frozen.paragraphs))
        for index, item in enumerate(contribution.get("plotline_ops", [])):
            operation = item["operation"]
            fact = GraphFact(
                direct_producer_agent_id=agent_id,
                operation_order=index,
                effective_chapter_id=effective_chapter_id,
                business_call_id=str(item["source_operation_id"]),
                declaration_id=item.get("event_id"),
                plotline_subject_id=str(operation["subject_id"]),
                plotline_subject_title=str(operation["subject_title"]),
                plotline_description=str(operation["description"]),
                plotline_before=operation.get("before"),
                plotline_after=str(operation["after"]),
            )
            session.add(fact)
            session.flush()
            self._write_evidence(session, fact.graph_fact_id, SourceEvidence, list(item.get("evidence") or []))
        session.flush()
        self.rebuild_storage(session, preserve=set(entities))

    @staticmethod
    def _write_evidence(
        session: Storage, graph_fact_id: str, evidence_model: Any, entries: list[dict[str, Any]]
    ) -> None:
        "按所有者序号写入有序原文证据；引用与操作共用同一事实证据序列"
        from src.storage.ids import new_id

        for ordinal, entry in enumerate(entries):
            session.add(
                evidence_model(
                    evidence_id=new_id(),
                    graph_fact_id=graph_fact_id,
                    ordinal=ordinal,
                    paragraph_id=int(entry["paragraph_id"]),
                    start_char=int(entry["char_start"]),
                    end_char=int(entry["char_end"]),
                )
            )

    def rebuild_storage(self, session: Any, *, preserve: set[str] | None = None) -> None:
        "清退不再被正式贡献或正式记录引用的身份行；状态由读侧折叠，不写第二份可写缓存"
        from sqlalchemy import delete, select

        from src.storage.models import GraphEntity, GraphRelation

        run_entities = select(GraphEntity.entity_id).where(GraphEntity.run_id == self.run_scope)
        live_entities: set[str] = set(preserve or ())
        live_entities.update(_queries.fact_graph_graph_rebuild_storage_2(session, self.run_scope))
        live_relations = set(_queries.fact_graph_graph_rebuild_storage_3(session, self.run_scope))
        for relation in _queries.fact_graph_graph_rebuild_storage_1(session, live_relations):
            live_entities.update((relation.from_entity_id, relation.to_entity_id))
        live_entities.update(_queries.fact_graph_graph_rebuild_storage_4(session, self.run_scope))
        live_entities.update(_queries.fact_graph_graph_rebuild_storage_5(session, self.run_scope))
        live_entities.update(_queries.fact_graph_graph_rebuild_storage_6(session, self.run_scope))
        live_entities.update(_queries.fact_graph_graph_rebuild_storage_7(session, self.run_scope))
        session.execute(
            delete(GraphRelation).where(
                GraphRelation.from_entity_id.in_(run_entities), GraphRelation.relation_id.not_in(live_relations)
            )
        )
        session.execute(
            delete(GraphEntity).where(GraphEntity.run_id == self.run_scope, GraphEntity.entity_id.not_in(live_entities))
        )
        session.flush()

    def discard_storage(self, session: Any, execution_ids: set[str]) -> None:
        from sqlalchemy import delete, select

        from src.storage.models import ChapterAnnotation, DeclarationParticipant, EventDeclaration, GraphFact

        ordered = sorted(execution_ids)
        session.execute(delete(GraphFact).where(GraphFact.direct_producer_agent_id.in_(ordered)))
        session.execute(
            delete(GraphFact).where(
                GraphFact.participant_id.in_(
                    select(DeclarationParticipant.participant_id)
                    .join(EventDeclaration, EventDeclaration.declaration_id == DeclarationParticipant.declaration_id)
                    .join(ChapterAnnotation, ChapterAnnotation.record_id == EventDeclaration.record_id)
                    .where(ChapterAnnotation.agent_id.in_(ordered))
                )
            )
        )
