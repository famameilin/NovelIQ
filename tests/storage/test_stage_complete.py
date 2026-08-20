"""
测试完整性检查函数

修改时间: 2026-03-15
任务: storage-layer-decoupling
修改内容: 使用 SessionFactory 替代 connect_db/create_tables，确保正确关闭连接

修改时间: 2026-03-15
任务: postgresql-migration-cleanup
修改内容: 改用 PostgreSQL db_session fixture，移除 SQLite 依赖
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import Chunk, split_chunk_paragraphs
from src.models.cloud.schema import CloudAnalysis
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
from tests.support.analysis_factories import insert_test_novel
from tests.support.chapter_annotation_helpers import persist_chapter_annotation


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
    """2026-08-15 M2：补齐 preprocess 完成的指标/曲线前置（最小合法行）"""
    from src.storage.repositories.paragraph_repository import (
        ParagraphCurveRow,
        ParagraphMetricRow,
    )

    repo = ParagraphRepository(db_session)
    repo.insert_paragraph_metrics(
        run_id,
        [
            ParagraphMetricRow(
                paragraph_id=paragraph_id,
                token_count=1,
                char_count=2,
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
                function_word_counts={},
                semantic_category_counts={},
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
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chapter_repo = ChapterRepository(db_session)
        assert not chapter_repo.is_preprocess_complete(run_id)

    def test_is_preprocess_complete_with_chunks_when_semantic_search_disabled(self, db_session):
        """2026-08-07 用于验证关闭语义原文定位时 chunks 足以完成预处理"""
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chapter_repo = ChapterRepository(db_session)
        chunks = _create_chunks(1)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        # 段落事实源是 preprocess 完成的前置条件（与语义检索开关无关）
        _insert_paragraphs(db_session, run_id, chunks)
        # 2026-08-15 M2：指标/曲线同为完成前置（段落行落库后分段提交的崩溃窗口）
        _insert_paragraph_derived_rows(db_session, run_id, [0])
        with patch(
            "src.storage.repositories.chapter_repository.settings.models.paragraph_embedding.semantic_enabled",
            False,
        ):
            assert chapter_repo.is_preprocess_complete(run_id)

    def test_is_preprocess_complete_false_when_semantic_paragraph_embeddings_missing(self, db_session):
        """
        创建时间: 2026-04-24
        任务: fix-preprocess-completion-level3-contract
        说明: 当前配置要求 Level3 时，只有 chunks 或只有 chunk embeddings 都不能视为 preprocess 完成。
              RAG 粒度固定为自然段：只有 paragraph embeddings 才算数。
        """
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chapter_repo = ChapterRepository(db_session)
        chunks = _create_chunks(2)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        ensure_paragraph_embeddings_schema(db_session, 1024)

        with (
            patch(
                "src.storage.repositories.chapter_repository.settings.models.paragraph_embedding.semantic_enabled",
                True,
            ),
            patch(
                "src.storage.repositories.chapter_repository.settings.models.paragraph_embedding.embedding_dim",
                1024,
            ),
        ):
            assert not chapter_repo.is_preprocess_complete(run_id)

    def test_is_preprocess_complete_true_when_semantic_embeddings_complete(self, db_session):
        """
        创建时间: 2026-04-24
        任务: fix-preprocess-completion-level3-contract
        说明: 当前配置要求 Level3 时，只有 paragraph embeddings 完整就绪，preprocess 才算完成。
        """
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chapter_repo = ChapterRepository(db_session)
        chunks = _create_chunks(2)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        _insert_paragraphs(db_session, run_id, chunks)
        # 2026-08-15 M2：指标/曲线同为完成前置
        _insert_paragraph_derived_rows(db_session, run_id, [0, 1])
        ensure_paragraph_embeddings_schema(db_session, 1024)
        # 二期段落化：embedding 行按 paragraph_id 对齐段落事实源
        # （chunk 0 的段 paragraph_id=0，chunk 1 的段 paragraph_id=1）
        insert_paragraph_embeddings(
            db_session,
            run_id,
            [
                ParagraphEmbeddingRow(paragraph_id=0, embedding_vector=[0.3] * 1024),
                ParagraphEmbeddingRow(paragraph_id=1, embedding_vector=[0.4] * 1024),
            ],
        )

        with (
            patch(
                "src.storage.repositories.chapter_repository.settings.models.paragraph_embedding.semantic_enabled",
                True,
            ),
            patch(
                "src.storage.repositories.chapter_repository.settings.models.paragraph_embedding.embedding_dim",
                1024,
            ),
        ):
            assert chapter_repo.is_preprocess_complete(run_id)

    def test_is_preprocess_complete_false_when_paragraph_metrics_missing(self, db_session):
        """2026-08-15 M2 回归：段落行存在但指标缺失（分段提交崩溃窗口）→ 判定未完成"""
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chapter_repo = ChapterRepository(db_session)
        chunks = _create_chunks(1)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        _insert_paragraphs(db_session, run_id, chunks)

        with patch(
            "src.storage.repositories.chapter_repository.settings.models.paragraph_embedding.semantic_enabled",
            False,
        ):
            assert not chapter_repo.is_preprocess_complete(run_id)

    def test_is_preprocess_complete_false_when_partial_paragraph_embeddings(self, db_session):
        """
        2026-08-14 二期段落化：readiness 缺口以段落为粒度——
        部分段落缺 embedding 行时 preprocess 不得判定完成。
        """
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
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
        )

        with (
            patch(
                "src.storage.repositories.chapter_repository.settings.models.paragraph_embedding.semantic_enabled",
                True,
            ),
            patch(
                "src.storage.repositories.chapter_repository.settings.models.paragraph_embedding.embedding_dim",
                1024,
            ),
        ):
            assert not chapter_repo.is_preprocess_complete(run_id)

    def test_is_annotate_complete_no_annotations(self, db_session):
        """有chunks但无annotations时annotate未完成"""
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chapter_repo = ChapterRepository(db_session)
        ann_repo = AnnotationRepository(db_session)
        chunks = _create_chunks(3)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        assert not ann_repo.is_annotate_complete(run_id)

    def test_is_annotate_complete_partial_annotations(self, db_session):
        """annotations数量小于chunks数量时annotate未完成"""
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chapter_repo = ChapterRepository(db_session)
        ann_repo = AnnotationRepository(db_session)
        chunks = _create_chunks(3)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        # 2026-08-18 段落事实源：证据派生要求章节存在段落行
        _insert_paragraphs(db_session, run_id, chunks)
        persist_chapter_annotation(db_session, run_id=run_id, chapter_id=1)
        assert not ann_repo.is_annotate_complete(run_id)

    def test_is_annotate_complete_all_annotations(self, db_session):
        """2026-08-05 用于验证每个真实章节都有正式标注时 annotate 完成"""
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chapter_repo = ChapterRepository(db_session)
        ann_repo = AnnotationRepository(db_session)
        chunks = _create_chunks(3)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        # 2026-08-18 段落事实源：证据派生要求章节存在段落行
        _insert_paragraphs(db_session, run_id, chunks)
        for chapter_id in range(1, 4):
            persist_chapter_annotation(db_session, run_id=run_id, chapter_id=chapter_id)
        assert ann_repo.is_annotate_complete(run_id)

    def test_is_aggregate_complete_no_data(self, db_session):
        """无emotion_curve和rhythm_curve时aggregate未完成"""
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chapter_repo = ChapterRepository(db_session)
        stats_repo = StatsRepository(db_session)
        chunks = _create_chunks(3)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        assert not stats_repo.is_aggregate_complete(run_id)

    def test_is_aggregate_complete_partial_data(self, db_session):
        """只有chunks、无global_stats时aggregate未完成（M8b 后以 global_stats 为准）"""
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chapter_repo = ChapterRepository(db_session)
        stats_repo = StatsRepository(db_session)
        chunks = _create_chunks(3)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        assert not stats_repo.is_aggregate_complete(run_id)

    def test_is_topic_model_complete_no_data(self, db_session):
        """无paragraph_topics时topic_model未完成"""
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        stats_repo = StatsRepository(db_session)
        assert not stats_repo.has_topic_data(run_id)

    def test_is_topic_model_complete_with_data(self, db_session):
        """有paragraph_topics时topic_model完成（§11.1 主题判定改查段落主题）"""
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chapter_repo = ChapterRepository(db_session)
        stats_repo = StatsRepository(db_session)
        chunks = _create_chunks(1)
        chapter_repo.insert_chapter_texts(run_id, chunks)
        _insert_paragraphs(db_session, run_id, chunks)
        ParagraphRepository(db_session).insert_paragraph_topics(run_id, [(0, 1, 0.5, 10)])
        assert stats_repo.has_topic_data(run_id)

    def test_is_diagnose_complete_no_data(self, db_session):
        """无cloud_analysis时diagnose未完成"""
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        stats_repo = StatsRepository(db_session)
        assert not stats_repo.has_diagnosis_data(run_id)

    def test_is_diagnose_complete_with_data(self, db_session):
        """有cloud_analysis时diagnose完成"""
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        stats_repo = StatsRepository(db_session)
        analysis = CloudAnalysis(
            novel_id=novel_id,
            foreshadow_expectation=0.5,
            arc_scores={"角色0": 8.2, "角色1": 7.4},
            genre_labels=["通用"],
            style_labels=["严肃"],
            topic_labels=["成长"],
            diagnosis="ok",
            focus_structure="dual",
            focus_characters=["角色0", "角色1"],
            main_characters=["角色0", "角色1"],
            core_cast=["角色0", "角色1"],
        )
        stats_repo.insert_cloud_analysis(run_id, analysis)
        assert stats_repo.has_diagnosis_data(run_id)

    def test_is_diagnose_complete_rejects_incomplete_focus_contract_row(self, db_session):
        """旧/半成品 cloud_analysis 行不应再把 diagnose 阶段标成完成"""
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )

        db_session.execute(
            text(
                "INSERT INTO cloud_analysis "
                "(novel_id, foreshadow_expectation, arc_scores, diagnosis, run_id) "
                "VALUES (:novel_id, :foreshadow_expectation, :arc_scores, :diagnosis, :run_id)"
            ),
            {
                "novel_id": novel_id,
                "foreshadow_expectation": 0.5,
                "arc_scores": '{"角色0": 8.2, "角色1": 7.4}',
                "diagnosis": "旧 row 缺少 focus contract",
                "run_id": run_id,
            },
        )
        db_session.commit()

        stats_repo = StatsRepository(db_session)
        assert not stats_repo.has_diagnosis_data(run_id)
