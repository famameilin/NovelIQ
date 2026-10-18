"event trees trees 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select, text

from src.storage.models import (
    ChapterAnnotation,
    DeclarationParticipant,
    EventDeclaration,
    EventForeshadowingAction,
    GraphEntity,
    NarrativeLink,
)


def event_trees_trees_save_work_1(_session, value_1):
    return _session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"event_trees:{value_1}"}
    )


def event_trees_trees_save_work_2(_session, annotation_id):
    return _session.get(ChapterAnnotation, annotation_id)


def event_trees_trees_save_work_3(_session, action):
    return _session.get(EventDeclaration, action["root_event_id"])


def event_trees_trees_save_work_4(_session, endpoint_id):
    return _session.get(EventDeclaration, endpoint_id)


def event_trees_trees_discard_storage_1(_session, execution_ids):
    return _session.execute(
        select(EventDeclaration.declaration_id).where(
            EventDeclaration.record_id.in_(
                select(ChapterAnnotation.record_id).where(ChapterAnnotation.execution_id.in_(sorted(execution_ids)))
            )
        )
    ).scalars()


def event_trees_trees_load_saved_work_1(_session, annotation_id):
    return _session.get(ChapterAnnotation, annotation_id)


def event_trees_trees_load_saved_work_2(_session, annotation_id):
    return _session.scalars(select(EventDeclaration).where(EventDeclaration.record_id == annotation_id))


def event_trees_trees_load_saved_work_3(_session, declaration_ids):
    return _session.scalars(
        select(DeclarationParticipant)
        .where(DeclarationParticipant.declaration_id.in_(declaration_ids))
        .order_by(DeclarationParticipant.declaration_id, DeclarationParticipant.participant_ordinal)
    )


def event_trees_trees_load_saved_work_4(_session, execution_id):
    return _session.scalars(
        select(EventForeshadowingAction).where(EventForeshadowingAction.producer_execution_id == execution_id)
    )


def event_trees_trees_load_saved_work_5(_session, execution_id):
    return _session.scalars(
        select(NarrativeLink).where(
            NarrativeLink.producer_execution_id == execution_id,
            NarrativeLink.semantic_source_declaration_id.is_not(None),
        )
    )


def event_trees_trees_load_saved_work_6(_session, participant_rows):
    return _session.scalars(
        select(GraphEntity).where(GraphEntity.entity_id.in_({row.entity_id for row in participant_rows}))
    )
