"""
CLI aggregate 模块测试

创建时间: 2025-03-11
创建者: TraeAI
任务: 测试聚合流程

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 使用 SessionFactory 替代 connect_db/create_tables，消除 DeprecationWarning

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 使用 SQLAlchemy text() 替换 ? 占位符，移除 sqlite3 导入

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration-cleanup
修改内容: 改用 PostgreSQL db_session fixture，移除 SessionFactory 依赖
"""
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import Chunk
from src.models.local.schema import ChunkAnnotation
from src.storage.repositories import AnnotationRepository, ChunkRepository, ChunkStyleData, RunRepository
from src.workflows.aggregate import run_aggregate


class TestAggregate:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def _create_chunks_with_style(self, chunk_count: int) -> None:
        chunk_repo = ChunkRepository(self.db_session)
        chunks = [Chunk(index=i, start=0, end=100, text=f"这是第{i}个测试文本。包含快乐和悲伤的词语。") for i in range(chunk_count)]
        chunk_repo.insert_chunks(self.run_id, chunks)

        style_rows = [
            ChunkStyleData(
                chunk_id=i,
                mtld=50.0 + i,
                ttr=0.5,
                avg_sent_len=20.0 + i,
                sent_len_std=5.0,
                d_value=5.0,
                pause_density=0.1,
                fight_density=0.0,
                exclaim_density=0.0,
                dialogue_ratio=0.2,
                question_density=0.0,
                sensory_density=0.0,
                metaphor_density=0.0,
                function_word_vector="{}",
                category_density_combat=0.0,
                category_density_body=0.0,
                category_density_relation=0.0,
                category_density_faction=0.0,
                category_density_command=0.0,
                category_density_action=0.0,
                category_density_psychology=0.0,
                category_density_measure=0.0,
                category_density_emotion=0.0,
                category_density_color=0.0,
            )
            for i in range(chunk_count)
        ]
        chunk_repo.insert_chunk_style(self.run_id, style_rows)

    @pytest.mark.asyncio()
    async def test_aggregate_basic(self) -> None:
        self._create_chunks_with_style(5)

        chunks, chunk_curves_count, _ = await run_aggregate(run_id=self.run_id, session=self.db_session)
        assert chunks == 5
        assert chunk_curves_count == 5

        chunk_curves_count = self.db_session.execute(
            text("SELECT COUNT(*) FROM chunk_curves WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        stats_count = self.db_session.execute(
            text("SELECT COUNT(*) FROM global_stats WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()

        assert chunk_curves_count == 5
        assert stats_count > 0

    @pytest.mark.asyncio()
    async def test_aggregate_chunk_curves(self) -> None:
        self._create_chunks_with_style(3)

        await run_aggregate(run_id=self.run_id, session=self.db_session)

        rows = self.db_session.execute(
            text("SELECT chunk_id, pos_density, neg_density, net_density, smoothed_density, tension_proxy, tension_composite FROM chunk_curves WHERE run_id = :run_id ORDER BY chunk_id"),
            {"run_id": self.run_id},
        ).fetchall()
        assert len(rows) == 3
        for row in rows:
            assert row[0] is not None
            assert isinstance(row[1], float)
            assert isinstance(row[2], float)
            assert isinstance(row[3], float)
            assert isinstance(row[4], float)
            assert isinstance(row[5], float)
            assert isinstance(row[6], float)

    @pytest.mark.asyncio()
    async def test_aggregate_global_stats(self) -> None:
        self._create_chunks_with_style(5)

        await run_aggregate(run_id=self.run_id, session=self.db_session)

        stats = self.db_session.execute(
            text("SELECT stat_name, stat_value FROM global_stats WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).fetchall()
        stat_names = [s[0] for s in stats]
        assert "global_avg_mtld" in stat_names
        assert "global_avg_ttr" in stat_names
        assert "global_avg_sent_len" in stat_names
        assert "emotion_avg" in stat_names
        assert "emotion_std" in stat_names
        assert "emotion_max" in stat_names
        assert "emotion_min" in stat_names
        assert "rhythm_avg" in stat_names
        assert "rhythm_std" in stat_names

    @pytest.mark.asyncio()
    async def test_aggregate_with_annotations(self) -> None:
        chunk_repo = ChunkRepository(self.db_session)
        test_chunks = [Chunk(index=i, start=0, end=100, text=f"测试文本{i}") for i in range(3)]
        chunk_repo.insert_chunks(self.run_id, test_chunks)

        style_rows = [
            ChunkStyleData(
                chunk_id=i,
                mtld=50.0,
                ttr=0.5,
                avg_sent_len=20.0,
                sent_len_std=5.0,
                d_value=5.0,
                pause_density=0.1,
                fight_density=0.0,
                exclaim_density=0.0,
                dialogue_ratio=0.2,
                question_density=0.0,
                sensory_density=0.0,
                metaphor_density=0.0,
                function_word_vector="{}",
                category_density_combat=0.0,
                category_density_body=0.0,
                category_density_relation=0.0,
                category_density_faction=0.0,
                category_density_command=0.0,
                category_density_action=0.0,
                category_density_psychology=0.0,
                category_density_measure=0.0,
                category_density_emotion=0.0,
                category_density_color=0.0,
            )
            for i in range(3)
        ]
        chunk_repo.insert_chunk_style(self.run_id, style_rows)

        ann_repo = AnnotationRepository(self.db_session)
        for i in range(3):
            annotation = ChunkAnnotation(
                emotional_valence="positive",
                event_type="高潮" if i == 0 else "日常",
                pivot_moment=(i == 0),
                cliffhanger=(i == 2),
                has_foreshadowing=False,
                foreshadowing_type=None,
                foreshadowing_desc="",
                characters=[],
                relations=[],
                dialogues=[],
            )
            ann_repo.insert_chunk_annotation(self.run_id, i, annotation)

        chunks, chunk_curves_count, _ = await run_aggregate(run_id=self.run_id, session=self.db_session)
        assert chunks == 3

        curve_data = self.db_session.execute(
            text("SELECT tension_composite FROM chunk_curves WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).fetchall()
        assert len(curve_data) == 3

    @pytest.mark.asyncio()
    async def test_aggregate_empty_db(self) -> None:
        chunks, chunk_curves_count, _ = await run_aggregate(run_id=self.run_id, session=self.db_session)
        assert chunks == 0
        assert chunk_curves_count == 0
