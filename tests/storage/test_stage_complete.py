"""
2026-03-11: Claude创建
测试完整性检查函数

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 使用 SessionFactory 替代 connect_db/create_tables，确保正确关闭连接

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration-cleanup
修改内容: 改用 PostgreSQL db_session fixture，移除 SQLite 依赖
"""
import sys
from pathlib import Path
import uuid

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.storage.repositories import (
    ChunkRepository,
    AnnotationRepository,
    StatsRepository,
    RunRepository,
)
from src.models.local.schema import ChunkAnnotation
from src.models.cloud.schema import CloudAnalysis
from src.chunking.chunker import Chunk


def _create_chunks(count: int = 3) -> list[Chunk]:
    """创建测试用的chunks"""
    return [
        Chunk(index=i, text=f"测试文本{i}" * 100, start=i * 100, end=(i + 1) * 100)
        for i in range(count)
    ]


class TestStageCompleteChecks:
    """测试各阶段完整性检查函数"""

    def test_is_preprocess_complete_empty_db(self, db_session):
        """空数据库时preprocess未完成"""
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=f"test_novel_{uuid.uuid4().hex[:8]}",
            source_path="test",
            title="Test Novel",
        )
        chunk_repo = ChunkRepository(db_session)
        assert not chunk_repo.is_preprocess_complete(run_id)

    def test_is_preprocess_complete_with_chunks(self, db_session):
        """有chunks时preprocess完成"""
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=f"test_novel_{uuid.uuid4().hex[:8]}",
            source_path="test",
            title="Test Novel",
        )
        chunk_repo = ChunkRepository(db_session)
        chunks = _create_chunks(1)
        chunk_repo.insert_chunks(run_id, chunks)
        assert chunk_repo.is_preprocess_complete(run_id)

    def test_is_annotate_complete_no_annotations(self, db_session):
        """有chunks但无annotations时annotate未完成"""
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=f"test_novel_{uuid.uuid4().hex[:8]}",
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
        run_id = run_repo.create_run(
            novel_id=f"test_novel_{uuid.uuid4().hex[:8]}",
            source_path="test",
            title="Test Novel",
        )
        chunk_repo = ChunkRepository(db_session)
        ann_repo = AnnotationRepository(db_session)
        chunks = _create_chunks(3)
        chunk_repo.insert_chunks(run_id, chunks)
        ann_repo.insert_chunk_annotation(
            run_id,
            0,
            ChunkAnnotation(
                emotional_valence="neutral",
                event_type="日常",
                pivot_moment=False,
                cliffhanger=False,
                has_foreshadowing=False,
                foreshadowing_type=None,
                foreshadowing_desc="",
            ),
        )
        assert not ann_repo.is_annotate_complete(run_id)

    def test_is_annotate_complete_all_annotations(self, db_session):
        """annotations数量等于chunks数量时annotate完成"""
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=f"test_novel_{uuid.uuid4().hex[:8]}",
            source_path="test",
            title="Test Novel",
        )
        chunk_repo = ChunkRepository(db_session)
        ann_repo = AnnotationRepository(db_session)
        chunks = _create_chunks(3)
        chunk_repo.insert_chunks(run_id, chunks)
        for i in range(3):
            ann_repo.insert_chunk_annotation(
                run_id,
                i,
                ChunkAnnotation(
                    emotional_valence="neutral",
                    event_type="日常",
                    pivot_moment=False,
                    cliffhanger=False,
                    has_foreshadowing=False,
                    foreshadowing_type=None,
                    foreshadowing_desc="",
                ),
            )
        assert ann_repo.is_annotate_complete(run_id)

    def test_is_aggregate_complete_no_data(self, db_session):
        """无emotion_curve和rhythm_curve时aggregate未完成"""
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=f"test_novel_{uuid.uuid4().hex[:8]}",
            source_path="test",
            title="Test Novel",
        )
        chunk_repo = ChunkRepository(db_session)
        stats_repo = StatsRepository(db_session)
        chunks = _create_chunks(3)
        chunk_repo.insert_chunks(run_id, chunks)
        assert not stats_repo.is_aggregate_complete(run_id)

    def test_is_aggregate_complete_partial_data(self, db_session):
        """只有部分emotion_curve时aggregate未完成"""
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=f"test_novel_{uuid.uuid4().hex[:8]}",
            source_path="test",
            title="Test Novel",
        )
        chunk_repo = ChunkRepository(db_session)
        stats_repo = StatsRepository(db_session)
        chunks = _create_chunks(3)
        chunk_repo.insert_chunks(run_id, chunks)
        stats_repo.insert_emotion_curve(run_id, [(0, 0.1, 0.2, 0.0, 0.1)])
        assert not stats_repo.is_aggregate_complete(run_id)

    def test_is_aggregate_complete_all_data(self, db_session):
        """emotion_curve和rhythm_curve数量都等于chunks数量时aggregate完成"""
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=f"test_novel_{uuid.uuid4().hex[:8]}",
            source_path="test",
            title="Test Novel",
        )
        chunk_repo = ChunkRepository(db_session)
        stats_repo = StatsRepository(db_session)
        chunks = _create_chunks(3)
        chunk_repo.insert_chunks(run_id, chunks)
        emotion_rows = [(i, 0.1, 0.2, 0.0, 0.1) for i in range(3)]
        rhythm_rows = [(i, 0.5, 0.3) for i in range(3)]
        stats_repo.insert_emotion_curve(run_id, emotion_rows)
        stats_repo.insert_rhythm_curve(run_id, rhythm_rows)
        assert stats_repo.is_aggregate_complete(run_id)

    def test_is_topic_model_complete_no_data(self, db_session):
        """无chunk_topics时topic_model未完成"""
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=f"test_novel_{uuid.uuid4().hex[:8]}",
            source_path="test",
            title="Test Novel",
        )
        stats_repo = StatsRepository(db_session)
        assert not stats_repo.has_topic_data(run_id)

    def test_is_topic_model_complete_with_data(self, db_session):
        """有chunk_topics时topic_model完成"""
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=f"test_novel_{uuid.uuid4().hex[:8]}",
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
        run_id = run_repo.create_run(
            novel_id=f"test_novel_{uuid.uuid4().hex[:8]}",
            source_path="test",
            title="Test Novel",
        )
        stats_repo = StatsRepository(db_session)
        assert not stats_repo.has_diagnosis_data(run_id)

    def test_is_diagnose_complete_with_data(self, db_session):
        """有cloud_analysis时diagnose完成"""
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=f"test_novel_{uuid.uuid4().hex[:8]}",
            source_path="test",
            title="Test Novel",
        )
        stats_repo = StatsRepository(db_session)
        analysis = CloudAnalysis(
            novel_id="test",
            foreshadow_rate=0.5,
            arc_scores=[0.2, 0.4],
            narrative_type="三幕",
            topic_labels=["成长"],
            diagnosis="ok",
        )
        stats_repo.insert_cloud_analysis(run_id, analysis)
        assert stats_repo.has_diagnosis_data(run_id)
