"""
运行诊断测试

创建时间: 2025-03-11
创建者: TraeAI
任务: 测试诊断流程

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

from src.workflows.diagnose import run_local_diagnose
from src.storage.repositories import ChunkRepository, ChunkStyleData, RunRepository
from src.chunking.chunker import Chunk


class TestRunDiagnose:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def _create_aggregated_data(self, chunk_count: int) -> None:
        chunk_repo = ChunkRepository(self.db_session)
        chunks = [Chunk(index=i, start=0, end=100, text=f"测试文本{i}") for i in range(chunk_count)]
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
                cultural_density=0.0,
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

        for i in range(chunk_count):
            self.db_session.execute(
                text("INSERT INTO emotion_curve (chunk_id, pos_density, neg_density, net_density, smoothed_density, run_id) VALUES (:chunk_id, :pos, :neg, :net, :smoothed, :run_id)"),
                {"chunk_id": i, "pos": 0.1, "neg": 0.05, "net": 0.05, "smoothed": 0.05, "run_id": self.run_id},
            )
            self.db_session.execute(
                text("INSERT INTO rhythm_curve (chunk_id, tension_proxy, tension_composite, run_id) VALUES (:chunk_id, :proxy, :composite, :run_id)"),
                {"chunk_id": i, "proxy": 0.5, "composite": 0.5, "run_id": self.run_id},
            )
        self.db_session.execute(
            text("INSERT INTO global_stats (stat_name, stat_value, run_id) VALUES (:name, :value, :run_id)"),
            {"name": "emotion_avg", "value": 0.05, "run_id": self.run_id},
        )
        self.db_session.commit()

    def test_local_diagnose_basic(self) -> None:
        self._create_aggregated_data(3)

        total_chunks, stats_count = run_local_diagnose(run_id=self.run_id, session=self.db_session)
        assert total_chunks == 3
        assert stats_count > 0

    def test_local_diagnose_empty_db(self) -> None:
        total_chunks, stats_count = run_local_diagnose(run_id=self.run_id, session=self.db_session)
        assert total_chunks == 0
        assert stats_count == 0
