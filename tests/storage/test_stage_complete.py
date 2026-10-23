"""测试完整性检查函数"""

import sys
from pathlib import Path
from unittest.mock import patch

from src.diagnosis.completion import has_diagnosis_data
from src.metrics.queries.completion import is_aggregate_complete
from src.storage import new_id
from src.work.queries import is_annotate_complete
from src.workflows.preprocess_readiness import is_preprocess_complete
from tests.support.storage_fixtures import storage_for

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.diagnosis.schema import AgentAnalysis
from src.storage.repositories import (
    AnnotationRepository,
    ChapterRepository,
    ParagraphRepository,
    RunRepository,
    StatsRepository,
)
from src.storage.repositories.paragraph import (
    ParagraphEmbeddingRow,
    insert_paragraph_embeddings,
)
from src.storage.vector_schema import ensure_paragraph_embeddings_schema
from src.text_processing.models import Chunk
from src.text_processing.paragraphs import split_chunk_paragraphs
from tests.support.analysis_factories import insert_test_novel
from tests.support.chapter_annotation_helpers import (
    create_run_with_chunks,
    persist_chapter_annotation,
)


def _create_chunks(count: int = 3) -> list[Chunk]:
    """创建测试用的chunks"""
    # 文本长度固定 500 字符（f"测试文本{i}" 恒为 5 字符 × 100），
    # 坐标区间必须与文本长度一致，否则 insert_paragraphs 的坐标单调校验失败
    text_len = 500
    return [
        Chunk(
            index=i,
            text=f"测试文本{i}" * 100,
            start=i * text_len,
            end=(i + 1) * text_len,
            chapter_id=i + 1,
        )
        for i in range(count)
    ]


def _insert_paragraphs(db_session, run_id: str, chunks: list[Chunk]) -> None:
    """生成并插入段落事实源（token_count 由调用方填充，reposiotry 校验非 None）"""
    from dataclasses import replace

    spans = [replace(span, token_count=1) for span in split_chunk_paragraphs(chunks)]
    ParagraphRepository(db_session).insert_paragraphs(run_id, spans)


def _insert_paragraph_derived_rows(db_session, run_id: str, paragraph_ids: list[int]) -> None:
    """补齐 preprocess 完成的指标/曲线前置（最小合法行）"""
    from src.storage.repositories.paragraph_repository import (
        ParagraphCurveRow,
        ParagraphMetricRow,
    )

    repo = ParagraphRepository(db_session)
    repo.insert_paragraph_metrics(
        run_id,
        [
            ParagraphMetricRow(
                # char_count/词类计数是读取投影，不是 paragraph_metrics 可写列
                paragraph_id=paragraph_id,
                token_count=1,
                sentence_count=1,
                sentence_char_sum=2.0,
                sentence_char_sum_sq=4.0,
                positive_weight_sum=0.0,
                negative_weight_sum=0.0,
                fight_weight_sum=0.0,
                exclaim_count=0,
                question_count=0,
                pause_count=0,
                dialogue_char_count=0,
                sensory_hit_count=0,
                imagery_hit_count=0,
                metaphor_sentence_count=0,
                body_reaction_hit_count=0,
            )
            for paragraph_id in paragraph_ids
        ],
    )
    repo.insert_paragraph_curves(
        run_id,
        [
            ParagraphCurveRow(
                paragraph_id=paragraph_id,
                pos_density=0.0,
                neg_density=0.0,
                net_density=0.0,
                smoothed_net_density=0.0,
                surface_tension=0.5,
                smoothed_surface_tension=0.5,
            )
            for paragraph_id in paragraph_ids
        ],
    )


class TestStageCompleteChecks:
    """测试各阶段完整性检查函数"""

    def test_is_preprocess_complete_empty_db(self, db_session):
        """空数据库时preprocess未完成"""
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(novel_id=novel_id)
        chapter_repo = ChapterRepository(db_session)
        assert not is_preprocess_complete(storage_for(chapter_repo.session), run_id)

    def test_is_preprocess_complete_with_chunks_when_semantic_search_disabled(self, db_session):
        """验证关闭语义原文定位时 chunks 足以完成预处理"""
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(novel_id=novel_id)
        chapter_repo = ChapterRepository(db_session)
        chunks = _create_chunks(1)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        # 段落事实源是 preprocess 完成的前置条件（与语义检索开关无关）
        _insert_paragraphs(db_session, run_id, chunks)
        # 指标/曲线同为完成前置（段落行落库后分段提交的崩溃窗口）
        _insert_paragraph_derived_rows(db_session, run_id, [0])
        with patch(
            "src.workflows.preprocess_readiness.settings.models.paragraph_embedding.semantic_enabled",
            False,
        ):
            assert is_preprocess_complete(storage_for(chapter_repo.session), run_id)

    def test_is_preprocess_complete_false_when_semantic_paragraph_embeddings_missing(self, db_session):
        """RAG 粒度固定为自然段：只有 paragraph embeddings 才算数。"""
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(novel_id=novel_id)
        chapter_repo = ChapterRepository(db_session)
        chunks = _create_chunks(2)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        ensure_paragraph_embeddings_schema(db_session, 1024)

        with patch(
            "src.workflows.preprocess_readiness.settings.models.paragraph_embedding.semantic_enabled",
            True,
        ):
            assert not is_preprocess_complete(storage_for(chapter_repo.session), run_id)

    def test_is_preprocess_complete_true_when_semantic_embeddings_complete(self, db_session):
        """当前配置要求 Level3 时，只有 paragraph embeddings 完整就绪，preprocess 才算完成。"""
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(novel_id=novel_id)
        chapter_repo = ChapterRepository(db_session)
        chunks = _create_chunks(2)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        _insert_paragraphs(db_session, run_id, chunks)
        # 指标/曲线同为完成前置
        _insert_paragraph_derived_rows(db_session, run_id, [0, 1])
        ensure_paragraph_embeddings_schema(db_session, 1024)
        # embedding 行按 paragraph_id 对齐段落事实源
        # （chunk 0 的段 paragraph_id=0，chunk 1 的段 paragraph_id=1）
        insert_paragraph_embeddings(
            db_session,
            run_id,
            [
                ParagraphEmbeddingRow(paragraph_id=0, embedding_vector=[0.3] * 1024),
                ParagraphEmbeddingRow(paragraph_id=1, embedding_vector=[0.4] * 1024),
            ],
            embedding_dimension=1024,
        )

        with patch(
            "src.workflows.preprocess_readiness.settings.models.paragraph_embedding.semantic_enabled",
            True,
        ):
            assert is_preprocess_complete(storage_for(chapter_repo.session), run_id)

    def test_is_preprocess_complete_false_when_paragraph_metrics_missing(self, db_session):
        """段落行存在但指标缺失（分段提交崩溃窗口）→ 判定未完成"""
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(novel_id=novel_id)
        chapter_repo = ChapterRepository(db_session)
        chunks = _create_chunks(1)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        _insert_paragraphs(db_session, run_id, chunks)

        with patch(
            "src.workflows.preprocess_readiness.settings.models.paragraph_embedding.semantic_enabled",
            False,
        ):
            assert not is_preprocess_complete(storage_for(chapter_repo.session), run_id)

    def test_is_preprocess_complete_false_when_partial_paragraph_embeddings(self, db_session):
        """readiness 缺口以段落为粒度——
        部分段落缺 embedding 行时 preprocess 不得判定完成。
        """
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(novel_id=novel_id)
        chapter_repo = ChapterRepository(db_session)
        chunks = _create_chunks(2)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        _insert_paragraphs(db_session, run_id, chunks)
        ensure_paragraph_embeddings_schema(db_session, 1024)
        # 只给 paragraph_id=0 写入向量，paragraph_id=1 缺口仍在
        insert_paragraph_embeddings(
            db_session,
            run_id,
            [ParagraphEmbeddingRow(paragraph_id=0, embedding_vector=[0.3] * 1024)],
            embedding_dimension=1024,
        )

        with patch(
            "src.workflows.preprocess_readiness.settings.models.paragraph_embedding.semantic_enabled",
            True,
        ):
            assert not is_preprocess_complete(storage_for(chapter_repo.session), run_id)

    def test_is_annotate_complete_no_annotations(self, db_session):
        """有chunks但无annotations时annotate未完成"""
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(novel_id=novel_id)
        chapter_repo = ChapterRepository(db_session)
        ann_repo = AnnotationRepository(db_session)
        chunks = _create_chunks(3)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        assert not is_annotate_complete(storage_for(ann_repo.session), run_id)

    def test_is_annotate_complete_partial_annotations(self, db_session):
        """annotations数量小于chunks数量时annotate未完成"""
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(novel_id=novel_id)
        chapter_repo = ChapterRepository(db_session)
        ann_repo = AnnotationRepository(db_session)
        chunks = _create_chunks(3)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        # 段落事实源：证据派生要求章节存在段落行
        _insert_paragraphs(db_session, run_id, chunks)
        persist_chapter_annotation(db_session, run_id=run_id, chapter_id=1)
        assert not is_annotate_complete(storage_for(ann_repo.session), run_id)

    def test_is_annotate_complete_all_annotations(self, db_session):
        """验证每个真实章节都有正式标注时 annotate 完成"""
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(novel_id=novel_id)
        chapter_repo = ChapterRepository(db_session)
        ann_repo = AnnotationRepository(db_session)
        chunks = _create_chunks(3)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        # 段落事实源：证据派生要求章节存在段落行
        _insert_paragraphs(db_session, run_id, chunks)
        for chapter_id in range(1, 4):
            persist_chapter_annotation(db_session, run_id=run_id, chapter_id=chapter_id)
        assert is_annotate_complete(storage_for(ann_repo.session), run_id)

    def test_is_aggregate_complete_no_data(self, db_session):
        """无emotion_curve和rhythm_curve时aggregate未完成"""
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(novel_id=novel_id)
        chapter_repo = ChapterRepository(db_session)
        stats_repo = StatsRepository(db_session)
        chunks = _create_chunks(3)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        assert not is_aggregate_complete(storage_for(stats_repo.session), run_id)

    def test_is_aggregate_complete_partial_data(self, db_session):
        """只有chunks、无global_stats时aggregate未完成（以 global_stats 为准）"""
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(novel_id=novel_id)
        chapter_repo = ChapterRepository(db_session)
        stats_repo = StatsRepository(db_session)
        chunks = _create_chunks(3)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        assert not is_aggregate_complete(storage_for(stats_repo.session), run_id)

    def test_insert_global_stats_registers_aggregate_completion(self, db_session):
        """写入全书统计即登记聚合阶段完成事实

        缺写者时序：每次续跑 is_aggregate_complete 恒假，聚合重跑且跳过条件
        连带压住主题与诊断阶段；补齐后一次写入即可判定完成。
        """
        _novel_id, run_id = create_run_with_chunks(db_session, texts=["测试文本" * 100])
        assert not is_aggregate_complete(storage_for(db_session), run_id)

        StatsRepository(db_session).insert_global_stats(run_id, [("avg_mtld", 58.4)])

        assert is_aggregate_complete(storage_for(db_session), run_id)

    def test_is_topic_model_complete_no_data(self, db_session):
        """无paragraph_topics时topic_model未完成"""
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(novel_id=novel_id)
        stats_repo = StatsRepository(db_session)
        assert not stats_repo.has_topic_data(run_id)

    def test_is_topic_model_complete_with_data(self, db_session):
        """有契约表与段落主题时topic_model完成（主题判定改查契约行）"""
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(novel_id=novel_id)
        chapter_repo = ChapterRepository(db_session)
        stats_repo = StatsRepository(db_session)
        chunks = _create_chunks(1)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        _insert_paragraphs(db_session, run_id, chunks)
        paragraph_repo = ParagraphRepository(db_session)
        from tests.support.storage_fixtures import save_topic_artifact
        save_topic_artifact(run_id, 1)
        paragraph_repo.insert_topic_model_run(
            run_id,
            model_key="gensim-lda",
            library_version="4.4.0",
            num_topics=1,
            parameters={"num_topics": 1},
            dictionary_size=10,
            training_document_count=1,
            inference_paragraph_count=1,
            artifact_key=f"models/topic/{run_id}",
        )
        paragraph_repo.insert_paragraph_topic_inferences(run_id, [(0, 10, 10, "complete", None, 1.0)])
        paragraph_repo.insert_paragraph_topics(run_id, [(0, 0, 1.0)])
        assert stats_repo.has_topic_data(run_id)

    def test_is_diagnose_complete_no_data(self, db_session):
        """无诊断产物时diagnose未完成"""
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(novel_id=novel_id)
        stats_repo = StatsRepository(db_session)
        assert not has_diagnosis_data(storage_for(stats_repo.session), run_id)

    def test_is_diagnose_complete_with_data(self, db_session):
        """正式报告 + 已保存完整事件 + 焦点结构与名单条目才判定 diagnose 完成"""
        from src.storage.repositories.diagnosis_event_writes import save_diagnosis_events
        from src.storage.repositories.organization_writes import save_organization
        from tests.support.event_tree_fixtures import (
            add_annotation_source,
            add_declaration,
            first_paragraph,
            identity_every_declaration,
        )
        from tests.support.storage_fixtures import insert_report_fixture

        novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜寻找山门并点灯。"])
        paragraph = first_paragraph(db_session, run_id)
        record_id, _agent_id = add_annotation_source(db_session, run_id, 1, role="event")
        add_declaration(
            db_session,
            record_id=record_id,
            paragraph=paragraph,
            phrase="顾霜寻找山门",
            title="寻找山门",
            summary="顾霜寻找山门",
            participants=(("顾霜", "主体"),),
        )
        db_session.flush()
        draft, _meta = identity_every_declaration(db_session, run_id)
        organization = draft.finish()
        report_id = insert_report_fixture(
            db_session,
            run_id,
            str(draft.agent_id),
            AgentAnalysis(
                novel_id=novel_id,
                narrative_organization=organization,
                diagnosis="顾霜寻路并点灯",
                focus_structure="single",
                focus_characters=["顾霜"],
                main_characters=["顾霜"],
                core_cast=["顾霜"],
            ),
        )
        save_diagnosis_events(db_session, run_id, organization, report_id)
        save_organization(db_session, run_id, organization, report_id)
        db_session.commit()

        stats_repo = StatsRepository(db_session)
        assert has_diagnosis_data(storage_for(stats_repo.session), run_id)

    def test_is_diagnose_complete_rejects_incomplete_focus_contract_row(self, db_session):
        """只有正文、缺焦点结构与名单条目的半成品报告行不算 diagnose 完成"""
        from tests.support.event_tree_fixtures import add_diagnosis_context
        from tests.support.storage_fixtures import insert_report_fixture

        novel_id, run_id = create_run_with_chunks(db_session, texts=["旧 row 缺少焦点合同。"])
        session_id, _agent_id = add_diagnosis_context(db_session, run_id)
        insert_report_fixture(
            db_session,
            run_id,
            session_id,
            AgentAnalysis(novel_id=novel_id, diagnosis="旧 row 缺少 focus contract"),
        )
        db_session.commit()

        stats_repo = StatsRepository(db_session)
        assert not has_diagnosis_data(storage_for(stats_repo.session), run_id)
