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

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import Chunk, split_chunk_paragraphs
from src.models.cloud.schema import CloudAnalysis
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    ParagraphRepository,
    RunRepository,
    StatsRepository,
)
from src.storage.repositories.chunk import (
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
        chunk_repo = ChunkRepository(db_session)
        assert not chunk_repo.is_preprocess_complete(run_id)

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
        chunk_repo = ChunkRepository(db_session)
        chunks = _create_chunks(1)
        chunk_repo.insert_chunks(run_id, chunks)
        # 段落事实源是 preprocess 完成的前置条件（与语义检索开关无关）
        _insert_paragraphs(db_session, run_id, chunks)
        with patch(
            "src.storage.repositories.chunk_repository.settings.models.paragraph_embedding.semantic_enabled",
            False,
        ):
            assert chunk_repo.is_preprocess_complete(run_id)

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
        chunk_repo = ChunkRepository(db_session)
        chunks = _create_chunks(2)
        chunk_repo.insert_chunks(run_id, chunks)
        ensure_paragraph_embeddings_schema(db_session, 1024)

        with (
            patch(
                "src.storage.repositories.chunk_repository.settings.models.paragraph_embedding.semantic_enabled",
                True,
            ),
            patch("src.storage.repositories.chunk_repository.settings.models.paragraph_embedding.embedding_dim", 1024),
        ):
            assert not chunk_repo.is_preprocess_complete(run_id)

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
        chunk_repo = ChunkRepository(db_session)
        chunks = _create_chunks(2)
        chunk_repo.insert_chunks(run_id, chunks)
        _insert_paragraphs(db_session, run_id, chunks)
        ensure_paragraph_embeddings_schema(db_session, 1024)
        insert_paragraph_embeddings(
            db_session,
            run_id,
            [
                ParagraphEmbeddingRow(
                    chunk_id=0,
                    paragraph_index=0,
                    paragraph_text="测试文本0",
                    local_start_char=0,
                    local_end_char=5,
                    global_start_char=0,
                    global_end_char=5,
                    embedding_vector=[0.3] * 1024,
                ),
                ParagraphEmbeddingRow(
                    chunk_id=1,
                    paragraph_index=0,
                    paragraph_text="测试文本1",
                    local_start_char=0,
                    local_end_char=5,
                    global_start_char=100,
                    global_end_char=105,
                    embedding_vector=[0.4] * 1024,
                ),
            ],
        )

        with (
            patch(
                "src.storage.repositories.chunk_repository.settings.models.paragraph_embedding.semantic_enabled",
                True,
            ),
            patch("src.storage.repositories.chunk_repository.settings.models.paragraph_embedding.embedding_dim", 1024),
        ):
            assert chunk_repo.is_preprocess_complete(run_id)

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
        chunk_repo = ChunkRepository(db_session)
        ann_repo = AnnotationRepository(db_session)
        chunks = _create_chunks(3)
        chunk_repo.insert_chunks(run_id, chunks)
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
        chunk_repo = ChunkRepository(db_session)
        ann_repo = AnnotationRepository(db_session)
        chunks = _create_chunks(3)
        chunk_repo.insert_chunks(run_id, chunks)
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
        chunk_repo = ChunkRepository(db_session)
        ann_repo = AnnotationRepository(db_session)
        chunks = _create_chunks(3)
        chunk_repo.insert_chunks(run_id, chunks)
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
        chunk_repo = ChunkRepository(db_session)
        stats_repo = StatsRepository(db_session)
        chunks = _create_chunks(3)
        chunk_repo.insert_chunks(run_id, chunks)
        assert not stats_repo.is_aggregate_complete(run_id)

    def test_is_aggregate_complete_partial_data(self, db_session):
        """只有部分chunk_curves时aggregate未完成"""
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chunk_repo = ChunkRepository(db_session)
        stats_repo = StatsRepository(db_session)
        chunks = _create_chunks(3)
        chunk_repo.insert_chunks(run_id, chunks)
        stats_repo.insert_chunk_curve(run_id, [(0, 0.1, 0.2, 0.0, 0.1, 0.5, 0.3)])
        assert not stats_repo.is_aggregate_complete(run_id)

    def test_is_topic_model_complete_no_data(self, db_session):
        """无chunk_topics时topic_model未完成"""
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
        """有chunk_topics时topic_model完成"""
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chunk_repo = ChunkRepository(db_session)
        stats_repo = StatsRepository(db_session)
        chunks = _create_chunks(1)
        chunk_repo.insert_chunks(run_id, chunks)
        chunk_repo.insert_chunk_topics(run_id, [(0, 1, 0.5)])
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


class TestChunkTopicsIdempotency:
    """2026-08-13 修复 P1：chunk_topics 此前无唯一约束且重跑不清理旧行，
    重分析后数据翻倍、SUM 双倍计数；修复后写入幂等且唯一约束兜底。"""

    def _setup_run(self, db_session):
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chunk_repo = ChunkRepository(db_session)
        chunk_repo.insert_chunks(run_id, _create_chunks(1))
        return run_id, chunk_repo

    def test_reinsert_same_run_does_not_duplicate_rows(self, db_session):
        run_id, chunk_repo = self._setup_run(db_session)
        chunk_repo.insert_chunk_topics(run_id, [(0, 1, 0.5), (0, 2, 0.3)])
        # 重跑主题建模（非 force 路径）：同 run 再次插入不应翻倍
        chunk_repo.insert_chunk_topics(run_id, [(0, 1, 0.5), (0, 2, 0.3)])

        rows = db_session.execute(
            text("SELECT chunk_id, topic_id, topic_weight FROM chunk_topics WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).fetchall()
        assert len(rows) == 2

    def test_unique_constraint_rejects_duplicate_triple(self, db_session):
        from sqlalchemy.exc import IntegrityError

        from src.storage.models import ChunkTopic

        run_id, chunk_repo = self._setup_run(db_session)
        chunk_repo.insert_chunk_topics(run_id, [(0, 1, 0.5)])
        # 绕过幂等写入路径直接 ORM 插入同 (run_id, chunk_id, topic_id)：唯一约束必须拒绝
        db_session.add(ChunkTopic(chunk_id=0, topic_id=1, topic_weight=0.9, run_id=run_id))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_aggregate_sum_not_doubled_after_rerun(self, db_session):
        run_id, chunk_repo = self._setup_run(db_session)
        chunk_repo.insert_chunk_topics(run_id, [(0, 1, 0.5)])
        chunk_repo.insert_chunk_topics(run_id, [(0, 1, 0.5)])

        total = chunk_repo.fetch_chunk_topics_agg(run_id)
        assert len(total) == 1
        assert total[0].total_weight == pytest.approx(0.5)
