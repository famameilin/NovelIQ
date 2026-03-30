"""
CLI workflow 测试

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 使用 SessionFactory 替代 connect_db，消除 DeprecationWarning

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration-cleanup
修改内容: 改用 PostgreSQL db_session fixture，移除 SQLite 依赖
"""
import uuid
from unittest.mock import MagicMock

from src.models.annotation import AnnotationClient
from src.models.disambiguation import DisambiguationClient
from src.models.local.schema import CharacterSnapshot, ChunkAnnotation
from src.storage.repositories import AnnotationRepository, ChunkRepository, RunRepository, StatsRepository


def _create_mock_clients() -> tuple:
    mock_annotation = ChunkAnnotation(
        emotional_valence="neutral",
        event_type="铺垫",
        pivot_moment=False,
        cliffhanger=False,
        has_foreshadowing=False,
        foreshadowing_type=None,
        foreshadowing_desc="",
        characters=[
            CharacterSnapshot(
                name="张三",
                role_function="主体",
                action="测试行为",
                action_type="其他",
                emotion_score="neutral",
            )
        ],
    )
    mock_annotate_client = MagicMock(spec=AnnotationClient)
    mock_annotate_client.annotate_chunk.return_value = mock_annotation
    mock_annotate_client.disambiguate_characters.return_value = {}

    mock_incremental_client = MagicMock(spec=DisambiguationClient)
    mock_incremental_client.disambiguate_characters.return_value = {}

    mock_full_client = MagicMock(spec=DisambiguationClient)
    mock_full_client.disambiguate_characters.return_value = {}

    return mock_annotate_client, mock_incremental_client, mock_full_client


class TestStageCompletion:
    """测试阶段完成检查"""

    def test_preprocess_complete_with_chunks(self, db_session):
        """有 chunks 时 preprocess 完成"""
        novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(novel_id=novel_id, source_path="test", title="Test Novel")

        chunk_repo = ChunkRepository(db_session)
        from src.chunking.chunker import Chunk
        chunks = [Chunk(index=0, text="测试文本" * 100, start=0, end=100)]
        chunk_repo.insert_chunks(run_id, chunks)

        assert chunk_repo.has_chunks(run_id)

    def test_annotate_complete_with_annotations(self, db_session):
        """有 annotations 时 annotate 完成"""
        novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(novel_id=novel_id, source_path="test", title="Test Novel")

        chunk_repo = ChunkRepository(db_session)
        ann_repo = AnnotationRepository(db_session)
        from src.chunking.chunker import Chunk
        chunks = [Chunk(index=0, text="测试文本" * 100, start=0, end=100)]
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

        assert ann_repo.has_annotations(run_id)

    def test_aggregate_complete_with_data(self, db_session):
        """有聚合数据时 aggregate 完成"""
        novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(novel_id=novel_id, source_path="test", title="Test Novel")

        chunk_repo = ChunkRepository(db_session)
        stats_repo = StatsRepository(db_session)
        from src.chunking.chunker import Chunk
        chunks = [Chunk(index=0, text="测试文本" * 100, start=0, end=100)]
        chunk_repo.insert_chunks(run_id, chunks)
        stats_repo.insert_chunk_curve(run_id, [(0, 0.1, 0.2, 0.0, 0.1, 0.5, 0.3)])

        assert stats_repo.has_aggregated_data(run_id)





