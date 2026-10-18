"从 src/fact_graph/graph.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import or_, select, text

from src.storage.models import (
    AnalysisAssessment,
    Chapter,
    ChapterAnnotation,
    DeclarationParticipant,
    DiagnosisReport,
    DialogueRecord,
    EventDeclaration,
    Execution,
    FactEntityTag,
    GraphEntity,
    GraphFact,
    GraphRelation,
    SourceEvidence,
)


def fact_graph_graph_execution_entities_1(_session, run_id):
    run_executions = select(Execution.execution_id).where(
        or_(Execution.run_id == run_id, Execution.session_run_id == run_id)
    )
    return _session.scalars(
        select(DeclarationParticipant.entity_id)
        .join(EventDeclaration, EventDeclaration.declaration_id == DeclarationParticipant.declaration_id)
        .join(ChapterAnnotation, ChapterAnnotation.record_id == EventDeclaration.record_id)
        .where(ChapterAnnotation.execution_id.in_(run_executions))
    )


def fact_graph_graph_ensure_entity_rows_1(_session, value_1):
    return _session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"fact_graph:{value_1}"}
    )


def fact_graph_graph_ensure_entity_rows_2(_session, identifier):
    return _session.get(GraphEntity, identifier)


def fact_graph_graph_save_work_1(_session, value_1):
    return _session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"fact_graph:{value_1}"}
    )


def fact_graph_graph_save_work_2(_session, frozen_execution_id):
    return _session.get(Execution, frozen_execution_id)


def fact_graph_graph_save_work_3(_session, execution_id):
    return _session.execute(
        select(GraphFact.graph_fact_id).where(GraphFact.direct_producer_execution_id == execution_id).limit(1)
    ).scalar_one_or_none()


def fact_graph_graph_save_work_4(_session, entity_id):
    return _session.get(GraphEntity, entity_id)


def fact_graph_graph_save_work_5(_session, identifier):
    return _session.get(GraphRelation, identifier)


def fact_graph_graph_rebuild_storage_1(_session, live_relations):
    return _session.execute(
        select(GraphRelation.from_entity_id, GraphRelation.to_entity_id).where(
            GraphRelation.relation_id.in_(live_relations)
        )
    )


def fact_graph_graph_rebuild_storage_2(_session, value_1):
    run_executions = select(Execution.execution_id).where(
        or_(Execution.run_id == value_1, Execution.session_run_id == value_1)
    )
    return _session.scalars(
        select(GraphFact.entity_id).where(
            GraphFact.direct_producer_execution_id.in_(run_executions), GraphFact.entity_id.is_not(None)
        )
    )


def fact_graph_graph_rebuild_storage_3(_session, value_1):
    run_executions = select(Execution.execution_id).where(
        or_(Execution.run_id == value_1, Execution.session_run_id == value_1)
    )
    return _session.scalars(
        select(GraphFact.relation_id).where(
            GraphFact.direct_producer_execution_id.in_(run_executions), GraphFact.relation_id.is_not(None)
        )
    )


def fact_graph_graph_rebuild_storage_4(_session, value_1):
    run_executions = select(Execution.execution_id).where(
        or_(Execution.run_id == value_1, Execution.session_run_id == value_1)
    )
    return _session.scalars(
        select(DeclarationParticipant.entity_id)
        .join(EventDeclaration, EventDeclaration.declaration_id == DeclarationParticipant.declaration_id)
        .join(ChapterAnnotation, ChapterAnnotation.record_id == EventDeclaration.record_id)
        .where(ChapterAnnotation.execution_id.in_(run_executions))
    )


def fact_graph_graph_rebuild_storage_5(_session, value_1):
    run_executions = select(Execution.execution_id).where(
        or_(Execution.run_id == value_1, Execution.session_run_id == value_1)
    )
    return _session.scalars(
        select(DialogueRecord.speaker_entity_id).where(
            DialogueRecord.creation_execution_id.in_(run_executions), DialogueRecord.speaker_entity_id.is_not(None)
        )
    )


def fact_graph_graph_rebuild_storage_6(_session, value_1):
    run_executions = select(Execution.execution_id).where(
        or_(Execution.run_id == value_1, Execution.session_run_id == value_1)
    )
    return _session.scalars(
        select(AnalysisAssessment.cast_entity_id)
        .join(ChapterAnnotation, ChapterAnnotation.record_id == AnalysisAssessment.record_id, isouter=True)
        .where(
            ChapterAnnotation.execution_id.in_(run_executions)
            | AnalysisAssessment.report_id.in_(
                select(DiagnosisReport.report_id)
                .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
                .where(Execution.session_run_id == value_1)
            ),
            AnalysisAssessment.cast_entity_id.is_not(None),
        )
    )


def fact_graph_graph_rebuild_storage_7(_session, value_1):
    run_executions = select(Execution.execution_id).where(
        or_(Execution.run_id == value_1, Execution.session_run_id == value_1)
    )
    return _session.scalars(
        select(AnalysisAssessment.scored_entity_id)
        .join(ChapterAnnotation, ChapterAnnotation.record_id == AnalysisAssessment.record_id, isouter=True)
        .where(
            ChapterAnnotation.execution_id.in_(run_executions)
            | AnalysisAssessment.report_id.in_(
                select(DiagnosisReport.report_id)
                .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
                .where(Execution.session_run_id == value_1)
            ),
            AnalysisAssessment.scored_entity_id.is_not(None),
        )
    )


def fact_graph_graph_load_saved_work_1(_session, annotation_id):
    return _session.get(ChapterAnnotation, annotation_id)


def fact_graph_graph_load_saved_work_2(_session, execution_id):
    return _session.get(Execution, execution_id)


def fact_graph_graph_load_saved_work_3(_session, execution_chapter_id, value_1):
    return _session.scalar(select(Chapter).where(Chapter.run_id == value_1, Chapter.chapter_id == execution_chapter_id))


def fact_graph_graph_read_execution_facts_1(_session, rows):
    return _session.execute(
        select(FactEntityTag).where(FactEntityTag.graph_fact_id.in_([row.graph_fact_id for row in rows]))
    ).scalars()


def fact_graph_graph_read_execution_facts_2(_session, rows):
    return _session.execute(
        select(SourceEvidence).where(SourceEvidence.graph_fact_id.in_([row.graph_fact_id for row in rows]))
    ).scalars()


def fact_graph_graph_read_execution_facts_3(_session, execution_id):
    return _session.execute(
        select(GraphFact)
        .where(GraphFact.direct_producer_execution_id == execution_id)
        .order_by(GraphFact.operation_order, GraphFact.graph_fact_id)
    ).scalars()


def fact_graph_graph_read_execution_facts_4(_session, value_1):
    return _session.execute(select(GraphEntity).where(GraphEntity.run_id == value_1)).scalars()


def fact_graph_graph_read_execution_facts_5(_session):
    return _session.execute(select(GraphRelation)).scalars()


def fact_graph_graph_load_registry_1(_session, facts):
    return _session.execute(
        select(FactEntityTag).where(FactEntityTag.graph_fact_id.in_([row.graph_fact_id for row in facts]))
    ).scalars()


def fact_graph_graph_load_registry_2(_session, fact):
    return _session.get(GraphRelation, fact.relation_id)


def fact_graph_graph_load_registry_3(_session, value_1):
    return _session.execute(select(GraphEntity).where(GraphEntity.run_id == value_1)).scalars()


def fact_graph_graph_load_registry_4(_session, value_1):
    run_executions = select(Execution.execution_id).where(
        or_(Execution.run_id == value_1, Execution.session_run_id == value_1)
    )
    return _session.execute(
        select(GraphFact)
        .where(GraphFact.direct_producer_execution_id.in_(run_executions))
        .order_by(GraphFact.graph_fact_id)
    ).scalars()
