"""关系历史查询与恢复完整性检查的数据库回归"""

from __future__ import annotations

from sqlalchemy import select

from src.diagnosis.queries import DiagnosisQueries
from src.linguistic.completion import is_linguistic_complete
from src.storage.models import Paragraph
from src.storage.repositories import GraphRepository, ParagraphRepository, StatsRepository
from src.topic.completion import is_topic_model_complete
from tests.support.chapter_annotation_helpers import (
    character_fact,
    commit_test_annotation,
    create_run_with_chunks,
    persist_chapter_annotation,
    relation_fact,
)
from tests.support.storage_fixtures import storage_for


def _retract_relation(
    session,
    *,
    run_id: str,
    chapter_id: int,
    from_name: str,
    to_name: str,
    relation_type: str,
    reason: str,
) -> None:
    """关系撤回经正式 work 保存入口写图事实（不手拼旧图行）"""
    from src.agents.annotation.output_models import BoundChapterAnnotation
    from src.fact_graph.inputs import ChapterMetricsInput

    commit_test_annotation(
        session,
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=BoundChapterAnnotation(
            metrics=ChapterMetricsInput(summary="关系变化", emotional_valence=0, narrative_function="转折"),
            character_observations=[],
            dialogues=[],
            events=[],
        ),
        relation_assert_ops=[
            {
                "from_entity": from_name,
                "to_entity": to_name,
                "relation_type": relation_type,
                "chapter_id": chapter_id,
                "change_kind": "retract",
                "reason": reason,
            }
        ],
    )


def test_relation_history_reads_states_once_and_preserves_inactive_history(db_session) -> None:
    _, run_id = create_run_with_chunks(db_session, texts=["阿青与阿白联手", "两人分道扬镳"], chapter_ids=[1, 2])
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chapter_id=1, name="阿青", action="迎敌"),
            character_fact(chapter_id=1, name="阿白", action="迎敌"),
        ],
        relations=[relation_fact(chapter_id=1, from_name="阿青", to_name="阿白", relation_type="盟友")],
    )
    db_session.commit()
    _retract_relation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        from_name="阿青",
        to_name="阿白",
        relation_type="盟友",
        reason="分道扬镳",
    )
    db_session.commit()
    history = GraphRepository(db_session).fetch_relation_history(run_id)
    assert [(row.chapter_id, row.is_active) for row in history] == [(1, True), (2, False)]
    assert all({row.from_name, row.to_name} == {"阿青", "阿白"} for row in history)
    repo = DiagnosisQueries(storage_for(db_session))
    all_changes = repo.fetch_relation_changes(run_id)
    assert [chapter_id for chapter_id, _from_name, _to_name, _kind, _change in all_changes] == [1, 2]
    assert repo.fetch_relation_changes(run_id, limit=1) == all_changes[:1]
    assert repo.fetch_relation_changes(run_id, limit=0) == []


def _insert_completion(db_session, run_id: str, paragraph_id: int) -> None:
    """写入单段语言处理完成标记（零词元同样算已完成）

    完成行 FK 到 linguistic_runs 与运行合同，映射种子先落库再写完成行。
    """
    from src.linguistic import ENTITY_TYPE_MAP, POS_GROUP_MAP, ltp_pipeline_contract
    from src.storage.repositories.linguistic_repository import LinguisticRepository

    repo = LinguisticRepository(db_session)
    pipeline_version, model_key = ltp_pipeline_contract()
    repo.ensure_ltp_contract(
        run_id,
        pipeline_version=pipeline_version,
        model_key=model_key,
        pos_mappings=POS_GROUP_MAP,
        entity_type_mappings=ENTITY_TYPE_MAP,
    )
    repo.insert_linguistic_features(
        run_id,
        [
            {
                "paragraph_id": paragraph_id,
                "sentence_count": 0,
                "dependency_depth_sum": 0,
                "dependency_depth_max": 0,
            }
        ],
        clear_first=False,
    )
    db_session.flush()


def test_partial_linguistic_rows_are_not_a_completed_stage(db_session) -> None:
    _, run_id = create_run_with_chunks(db_session, texts=["。", "！"], chapter_ids=[1, 2])
    identifiers = list(
        db_session.execute(
            select(Paragraph.paragraph_id).where(Paragraph.run_id == run_id).order_by(Paragraph.paragraph_id),
        ).scalars()
    )
    repo = StatsRepository(db_session)
    assert not is_linguistic_complete(storage_for(repo.session), run_id)
    _insert_completion(db_session, run_id, identifiers[0])
    assert repo.has_linguistic_data(run_id)
    assert not is_linguistic_complete(storage_for(repo.session), run_id)
    _insert_completion(db_session, run_id, identifiers[1])
    assert is_linguistic_complete(storage_for(repo.session), run_id)


def test_topic_contract_and_partial_inference_or_distribution_cannot_be_reused(db_session) -> None:
    _, run_id = create_run_with_chunks(db_session, texts=["阿青迎敌", "。"], chapter_ids=[1, 2])
    identifiers = list(
        db_session.execute(
            select(Paragraph.paragraph_id).where(Paragraph.run_id == run_id).order_by(Paragraph.paragraph_id),
        ).scalars()
    )
    repo = ParagraphRepository(db_session)
    stats = StatsRepository(db_session)
    repo.insert_topic_model_run(
        run_id,
        model_key="gensim-lda",
        library_version="4.4.0",
        pipeline_version="current",
        num_topics=2,
        parameters={"num_topics": 2},
        dictionary_size=4,
        training_document_count=1,
        inference_paragraph_count=1,
        artifact_key=f"models/topic/{run_id}",
    )
    assert stats.has_topic_data(run_id)
    assert not is_topic_model_complete(storage_for(stats.session), run_id)
    complete = (identifiers[0], 2, 2, "complete", None, 1.0)
    empty = (identifiers[1], 0, 0, "empty_after_preprocess", "无词元", None)
    repo.insert_paragraph_topic_inferences(run_id, [complete])
    assert not is_topic_model_complete(storage_for(stats.session), run_id)
    repo.insert_paragraph_topic_inferences(run_id, [complete, empty])
    assert not is_topic_model_complete(storage_for(stats.session), run_id)
    repo.insert_paragraph_topics(run_id, [(identifiers[0], 0, 0.7)])
    assert not is_topic_model_complete(storage_for(stats.session), run_id)
    repo.insert_paragraph_topics(run_id, [(identifiers[0], 0, 0.7), (identifiers[0], 1, 0.3)])
    assert is_topic_model_complete(storage_for(stats.session), run_id)


def test_topic_rerun_writes_commit_against_deferred_constraints(db_session) -> None:
    """同 run 主题重跑写入必须可提交：重跑不得踩延迟约束触发器

    延迟行为触发器在提交时按每条修改行的当时版本校验，校验里的主题行计数读
    提交时的最终状态：重跑若先做全量"清空推断列"UPDATE，旧 complete 行以
    status=<NULL> 的修改事件被校验，与随后写入的最终主题行假冲突、提交必被拒。
    换全量 upsert 覆盖旧值后，重跑提交必须通过。
    """
    _, run_id = create_run_with_chunks(db_session, texts=["阿青迎敌", "。"], chapter_ids=[1, 2])
    identifiers = list(
        db_session.execute(
            select(Paragraph.paragraph_id).where(Paragraph.run_id == run_id).order_by(Paragraph.paragraph_id),
        ).scalars()
    )
    repo = ParagraphRepository(db_session)
    repo.insert_topic_model_run(
        run_id,
        model_key="gensim-lda",
        library_version="4.4.0",
        pipeline_version="current",
        num_topics=2,
        parameters={"num_topics": 2},
        dictionary_size=4,
        training_document_count=1,
        inference_paragraph_count=1,
        artifact_key=f"models/topic/{run_id}",
    )
    complete = (identifiers[0], 2, 2, "complete", None, 1.0)
    empty = (identifiers[1], 0, 0, "empty_after_preprocess", "无词元", None)
    distribution = [(identifiers[0], 0, 0.7), (identifiers[0], 1, 0.3)]
    # 首跑提交：延迟约束触发器在提交时点校验
    repo.insert_paragraph_topic_inferences(run_id, [complete, empty])
    repo.insert_paragraph_topics(run_id, distribution)
    db_session.commit()
    # 同 run 重跑：整体覆盖写入并再次提交，提交必须通过
    repo.insert_paragraph_topic_inferences(run_id, [complete, empty])
    repo.insert_paragraph_topics(run_id, distribution)
    db_session.commit()
    assert is_topic_model_complete(storage_for(db_session), run_id)
