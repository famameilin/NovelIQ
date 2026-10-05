"""关系历史查询与恢复完整性检查的数据库回归"""

from __future__ import annotations

from sqlalchemy import event, select

from src.storage.models import Paragraph, ParagraphLinguisticFeature
from src.storage.repositories import GraphRepository, ParagraphRepository, StatsRepository
from src.storage.repositories.diagnosis_repository import DiagnosisRepository
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    persist_chapter_annotation,
    relation_fact,
)


def test_relation_history_reads_states_once_and_preserves_inactive_history(db_session) -> None:
    _, run_id = create_run_with_chunks(db_session, texts=["阿青与阿白联手", "两人分道扬镳"], chapter_ids=[1, 2])
    persist_chapter_annotation(
        db_session, run_id=run_id, chapter_id=1,
        characters=[character_fact(chapter_id=1, name="阿青", action="迎敌"),
                    character_fact(chapter_id=1, name="阿白", action="迎敌")],
        relations=[relation_fact(chapter_id=1, from_name="阿青", to_name="阿白", relation_type="盟友")],
    )
    persist_chapter_annotation(
        db_session, run_id=run_id, chapter_id=2,
        continuity_resolutions=[{"reason": "分道扬镳", "from_entity": "阿青", "to_entity": "阿白",
                                 "relation_type": "盟友", "change_kind": "break"}],
    )
    db_session.commit()
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement.lower())

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture)
    try:
        history = GraphRepository(db_session).fetch_relation_history(run_id)
    finally:
        event.remove(bind, "before_cursor_execute", capture)
    assert [(row.chapter_id, row.is_active) for row in history] == [(1, True), (2, False)]
    assert history[0].from_name == "阿青" and history[1].to_name == "阿白"
    assert sum("from relation_states" in query for query in statements) == 1
    repo = DiagnosisRepository(db_session)
    all_changes = repo.fetch_relation_changes(run_id)
    assert [chapter_id for chapter_id, _from_name, _to_name, _kind, _change in all_changes] == [1, 2]
    assert repo.fetch_relation_changes(run_id, limit=1) == all_changes[:1]
    assert repo.fetch_relation_changes(run_id, limit=0) == []


def _feature(run_id: str, paragraph_id: int) -> ParagraphLinguisticFeature:
    return ParagraphLinguisticFeature(
        run_id=run_id, paragraph_id=paragraph_id, ltp_token_count=0, tokens=[], word_length_counts={},
        pos_counts={}, sentence_count=0, sentence_pattern_counts={}, dependency_arcs=[], dependency_node_count=0,
        dependency_root_count=0, dependency_depth_sum=0, dependency_depth_max=0, dependency_relation_counts={},
        sdp_arcs=[], emotion_events=[], emotion_event_count=0, emotion_pos_event_count=0, emotion_neg_event_count=0,
        lexicon_pos_count=0.0, lexicon_neg_count=0.0, mneg_pos_count=0.0, mneg_neg_count=0.0,
    )


def test_partial_linguistic_rows_are_not_a_completed_stage(db_session) -> None:
    _, run_id = create_run_with_chunks(db_session, texts=["。", "！"], chapter_ids=[1, 2])
    identifiers = list(db_session.execute(
        select(Paragraph.paragraph_id).where(Paragraph.run_id == run_id).order_by(Paragraph.paragraph_id),
    ).scalars())
    repo = StatsRepository(db_session)
    assert not repo.is_linguistic_complete(run_id)
    db_session.add(_feature(run_id, identifiers[0]))
    db_session.flush()
    assert repo.has_linguistic_data(run_id)
    assert not repo.is_linguistic_complete(run_id)
    db_session.add(_feature(run_id, identifiers[1]))
    db_session.flush()
    assert repo.is_linguistic_complete(run_id)


def test_topic_contract_and_partial_inference_or_distribution_cannot_be_reused(db_session) -> None:
    _, run_id = create_run_with_chunks(db_session, texts=["阿青迎敌", "。"], chapter_ids=[1, 2])
    identifiers = list(db_session.execute(
        select(Paragraph.paragraph_id).where(Paragraph.run_id == run_id).order_by(Paragraph.paragraph_id),
    ).scalars())
    repo = ParagraphRepository(db_session)
    stats = StatsRepository(db_session)
    repo.insert_topic_model_run(
        run_id, model_key="gensim-lda", library_version="4.4.0", pipeline_version="current",
        num_topics=2, parameters={"num_topics": 2}, dictionary_size=4, training_document_count=1,
        inference_paragraph_count=1, artifact_key=f"models/topic/{run_id}",
    )
    assert stats.has_topic_data(run_id)
    assert not stats.is_topic_model_complete(run_id)
    complete = (identifiers[0], 2, 2, "complete", None, 1.0)
    empty = (identifiers[1], 0, 0, "empty_after_preprocess", "无词元", None)
    repo.insert_paragraph_topic_inferences(run_id, [complete])
    assert not stats.is_topic_model_complete(run_id)
    repo.insert_paragraph_topic_inferences(run_id, [complete, empty])
    assert not stats.is_topic_model_complete(run_id)
    repo.insert_paragraph_topics(run_id, [(identifiers[0], 0, 0.7)])
    assert not stats.is_topic_model_complete(run_id)
    repo.insert_paragraph_topics(run_id, [(identifiers[0], 0, 0.7), (identifiers[0], 1, 0.3)])
    assert stats.is_topic_model_complete(run_id)
