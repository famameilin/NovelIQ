"""
诊断 Agent 路由测试

说明: 诊断已 agent 化（工具化自主取证），payload 构建与 DiagnosisClient 已移除；
     本文件保留数据层取证测试，并通过 patch run_diagnosis_agent 验证工作流落库
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import Chunk
from src.models.cloud.schema import CloudAnalysis
from src.models.local.schema import (
    CharacterSnapshot,
    ChunkAnnotation,
)
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    ChunkStyleData,
    DiagnosisRepository,
    RunRepository,
    StatsRepository,
)
from src.workflows.diagnose import run_diagnose


def _insert_test_novel(session, novel_id: str) -> None:
    """
    为诊断测试补小说主表记录
    """
    from src.storage.models import Novel

    session.add(
        Novel(
            novel_id=novel_id,
            filename=f"{novel_id}.txt",
            file_path=f"data/uploads/{novel_id}.txt",
            file_size=128,
        )
    )
    session.commit()


def _fake_analysis(novel_id: str) -> CloudAnalysis:
    return CloudAnalysis(
        novel_id=novel_id,
        foreshadow_expectation=0.1,
        arc_scores={"角色0": 8.5, "角色1": 7.0},
        genre_labels=["通用"],
        style_labels=["严肃"],
        topic_labels=["成长"],
        diagnosis="ok",
        narrative_arc_type="白手起家",
        focus_structure="dual",
        focus_characters=["角色0", "角色1"],
        main_characters=["角色0", "角色1"],
        core_cast=["角色0", "角色1"],
    )


class TestDiagnosisRoutes:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, self.novel_id)

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def _create_full_data(self, chunk_count: int = 5) -> None:
        chunk_repo = ChunkRepository(self.db_session)
        chunks = [
            Chunk(index=i, start=0, end=100, text=f"这是第{i}个测试文本，包含一些内容。") for i in range(chunk_count)
        ]
        chunk_repo.insert_chunks(self.run_id, chunks)
        chunk_repo.insert_chunk_topics(self.run_id, [(i, 0, 1.0) for i in range(chunk_count)])

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
                text(
                    "INSERT INTO chunk_curves ("
                    "chunk_id, pos_density, neg_density, net_density, smoothed_density, "
                    "tension_proxy, tension_composite, run_id"
                    ") VALUES (:chunk_id, :pos, :neg, :net, :smoothed, :proxy, :composite, :run_id)"
                ),
                {
                    "chunk_id": i,
                    "pos": 0.1,
                    "neg": 0.05,
                    "net": 0.05 + i * 0.01,
                    "smoothed": 0.05,
                    "proxy": 0.5,
                    "composite": 0.5,
                    "run_id": self.run_id,
                },
            )

        ann_repo = AnnotationRepository(self.db_session)
        for i in range(chunk_count):
            annotation = ChunkAnnotation(
                emotional_valence="mild_positive" if i % 2 == 0 else "mild_negative",
                event_type="高潮" if i in [1, 2] else ("转折" if i == 3 else "铺垫"),
                pivot_moment=(i in [1, 2]),
                cliffhanger=(i == chunk_count - 1),
                has_foreshadowing=(i == 0),
                foreshadowing_type="场景" if i == 0 else None,
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
                dialogues=[],
            )
            ann_repo.insert_chunk_annotation(self.run_id, i, annotation)
            ann_repo.insert_chunk_characters(self.run_id, i, annotation.characters)

        self.db_session.commit()

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
        assert len(relations) == 0

    def test_fetch_foreshadowing_chunks(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        chunks = diag_repo.fetch_foreshadowing_chunks(self.run_id)
        assert len(chunks) > 0

    def test_fetch_pivot_moments(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        moments = diag_repo.fetch_pivot_moments(self.run_id)
        assert len(moments) > 0

    @pytest.mark.asyncio()
    async def test_run_diagnose_agent_writes_db(self) -> None:
        self._create_full_data(5)

        fake = AsyncMock(return_value=_fake_analysis(self.novel_id))
        with patch("src.agents.run_diagnosis_agent", new=fake):
            analysis = await run_diagnose(
                run_id=self.run_id,
                session=self.db_session,
            )
        assert analysis is not None
        assert analysis.genre_labels == ["通用"]
        assert analysis.style_labels == ["严肃"]
        assert analysis.foreshadow_expectation == 0.1
        fake.assert_awaited_once()

        rows = self.db_session.execute(
            text("SELECT COUNT(*) FROM cloud_analysis WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        assert rows > 0

    @pytest.mark.asyncio()
    async def test_run_diagnose_persists_result(self) -> None:
        self._create_full_data(3)

        fake = AsyncMock(return_value=_fake_analysis(self.novel_id))
        with patch("src.agents.run_diagnosis_agent", new=fake):
            await run_diagnose(
                run_id=self.run_id,
                session=self.db_session,
            )
        rows = self.db_session.execute(
            text(
                "SELECT novel_id, genre_labels, style_labels, foreshadow_expectation, narrative_arc_type, "
                "focus_structure, focus_characters, main_characters, core_cast "
                "FROM cloud_analysis WHERE run_id = :run_id"
            ),
            {"run_id": self.run_id},
        ).fetchall()
        assert len(rows) > 0
        assert rows[0][0] == self.novel_id
        assert rows[0][1] == '["通用"]'
        assert rows[0][2] == '["严肃"]'
        assert rows[0][4] == "白手起家"
        assert rows[0][5] == "dual"
        assert "角色0" in rows[0][6]
        assert "角色0" in rows[0][7]
        assert "角色1" in rows[0][8]

        stats_repo = StatsRepository(self.db_session)
        fetched = stats_repo.fetch_cloud_analysis(self.novel_id, self.run_id)
        assert fetched is not None
        assert fetched["focus_structure"] == "dual"
        assert fetched["focus_characters"] is not None
        assert fetched["main_characters"] is not None
        assert fetched["core_cast"] is not None
        assert "reference_contract_version" not in fetched
