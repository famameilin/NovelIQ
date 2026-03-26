"""
云端诊断路由测试

创建时间: 2025-03-11
创建者: TraeAI
任务: 测试云端诊断

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
from sqlalchemy.orm import Session

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.workflows.diagnose import run_diagnose
from src.models.cloud import build_diagnosis_payload
from src.storage.repositories import (
    ChunkRepository,
    ChunkStyleData,
    RunRepository,
    AnnotationRepository,
    DiagnosisRepository,
)
from src.chunking.chunker import Chunk
from src.models.local.schema import (
    ChunkAnnotation,
    CharacterSnapshot,
    RelationChangeSnapshot,
)

from conftest import FakeClient


class TestCloudDiagnose:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def _create_full_data(self, chunk_count: int = 5) -> None:
        chunk_repo = ChunkRepository(self.db_session)
        chunks = [Chunk(index=i, start=0, end=100, text=f"这是第{i}个测试文本，包含一些内容。") for i in range(chunk_count)]
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

        for i in range(chunk_count):
            self.db_session.execute(
                text("INSERT INTO emotion_curve (chunk_id, pos_density, neg_density, net_density, smoothed_density, run_id) VALUES (:chunk_id, :pos, :neg, :net, :smoothed, :run_id)"),
                {"chunk_id": i, "pos": 0.1, "neg": 0.05, "net": 0.05 + i * 0.01, "smoothed": 0.05, "run_id": self.run_id},
            )
            self.db_session.execute(
                text("INSERT INTO rhythm_curve (chunk_id, tension_proxy, tension_composite, run_id) VALUES (:chunk_id, :proxy, :composite, :run_id)"),
                {"chunk_id": i, "proxy": 0.5, "composite": 0.5, "run_id": self.run_id},
            )

        ann_repo = AnnotationRepository(self.db_session)
        for i in range(chunk_count):
            annotation = ChunkAnnotation(
                emotional_valence="mild_positive" if i % 2 == 0 else "mild_negative",
                event_type="高潮" if i in [1, 2] else ("转折" if i == 3 else "铺垫"),
                pivot_moment=(i in [1, 2]),
                cliffhanger=(i == chunk_count - 1),
                has_foreshadowing=(i == 0),
                foreshadowing_type="causal" if i == 0 else None,
                foreshadowing_desc="测试伏笔" if i == 0 else "",
                characters=[
                    CharacterSnapshot(
                        name=f"角色{i}",
                        role_function="主体" if i == 0 else "其他",
                        action="测试行为",
                        action_type="其他",
                        emotion_score="neutral",
                    )
                ],
                relations=[
                    RelationChangeSnapshot(
                        from_name="角色A",
                        to_name="角色B",
                        type="盟友",
                        change="新建",
                    )
                ],
                dialogues=[],
            )
            ann_repo.insert_chunk_annotation(self.run_id, i, annotation)
            if annotation.relations:
                ann_repo.insert_chunk_relations(self.run_id, i, annotation.relations)

        self.db_session.commit()

    def test_build_diagnosis_payload(self) -> None:
        """
        修改时间: 2026-03-19
        修改者: TraeAI
        任务: 修复run_id过滤BUG
        修改内容: 添加run_id参数
        """
        self._create_full_data(5)

        payload = build_diagnosis_payload(self.db_session, self.novel_id, self.run_id)

        assert payload["novel_id"] == self.novel_id
        assert "pivot_blocks" in payload
        assert "pivot_moments" in payload
        assert "high_tension_paragraphs" in payload
        assert "character_relations" in payload
        assert "foreshadowing_list" in payload
        assert "first_chapter_summary" in payload
        assert "last_chapter_summary" in payload

        assert len(payload["pivot_blocks"]) > 0
        assert len(payload["pivot_moments"]) > 0
        assert len(payload["foreshadowing_list"]) > 0

    def test_fetch_pivot_blocks(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        blocks = diag_repo.fetch_pivot_blocks(self.run_id)
        assert len(blocks) > 0
        for block in blocks:
            assert len(block) == 3

    def test_fetch_high_tension_chunks(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        chunks = diag_repo.fetch_high_tension_chunks(self.run_id, limit=3)
        assert len(chunks) > 0
        for chunk in chunks:
            assert len(chunk) == 3

    def test_fetch_relation_changes(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        relations = diag_repo.fetch_relation_changes(self.run_id)
        assert len(relations) > 0
        for rel in relations:
            assert len(rel) == 5

    def test_fetch_foreshadowing_chunks(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        chunks = diag_repo.fetch_foreshadowing_chunks(self.run_id)
        assert len(chunks) > 0

    def test_fetch_first_last_chunk_summary(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        first, last = diag_repo.fetch_first_last_chunk_summary(self.run_id)
        assert len(first) > 0
        assert len(last) > 0

    def test_fetch_pivot_moments(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        moments = diag_repo.fetch_pivot_moments(self.run_id)
        assert len(moments) > 0

    def test_run_diagnose_with_cloud(self) -> None:
        self._create_full_data(5)

        analysis = run_diagnose(
            run_id=self.run_id,
            session=self.db_session,
            client=FakeClient(),
        )
        assert analysis is not None
        assert analysis.narrative_type == "三幕"
        assert analysis.foreshadow_rate == 0.1

        rows = self.db_session.execute(
            text("SELECT COUNT(*) FROM cloud_analysis WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        assert rows > 0

    def test_run_diagnose_persists_result(self) -> None:
        self._create_full_data(3)

        run_diagnose(
            run_id=self.run_id,
            session=self.db_session,
            client=FakeClient(),
        )
        rows = self.db_session.execute(
            text(
                "SELECT novel_id, narrative_type, foreshadow_rate, narrative_arc_type "
                "FROM cloud_analysis WHERE run_id = :run_id"
            ),
            {"run_id": self.run_id},
        ).fetchall()
        assert len(rows) > 0
        assert rows[0][3] == "白手起家"
