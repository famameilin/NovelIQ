"""
诊断 Agent 路由测试

说明: 诊断已 agent 化（工具化自主取证），payload 构建与 DiagnosisClient 已移除；
     本文件保留数据层取证测试，并通过 patch run_diagnosis_agent 验证工作流落库

2026-08-14 M8a：取证事实源段落化——测试数据改为写入 paragraphs/paragraph_topics/
paragraph_curves（chunk_topics 已删除），高张力素材来自段落曲线 surface_tension。
"""

import sys
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.agents.annotation.schema import BoundForeshadowing
from src.chunking.chunker import Chunk, split_chunk_paragraphs
from src.models.cloud.schema import CloudAnalysis
from src.storage.repositories import (
    ChapterRepository,
    DiagnosisRepository,
    ForeshadowingRepository,
    ParagraphRepository,
    RunRepository,
    StatsRepository,
)
from src.storage.repositories.paragraph_repository import ParagraphCurveRow
from src.workflows.diagnose import run_diagnose
from tests.support.analysis_factories import insert_test_novel
from tests.support.chapter_annotation_helpers import character_fact, persist_chapter_annotation


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
        insert_test_novel(self.novel_id, session=db_session)

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def _create_full_data(self, chunk_count: int = 5) -> None:
        chapter_repo = ChapterRepository(self.db_session)
        # M9a-2：每章一个运行时 chunk（chunk_id == chapter_id），
        # 段落坐标校验要求 global 坐标严格单调不重叠：偏移随章节序号递增
        chunks = [
            Chunk(
                index=i,
                start=i * 100,
                end=(i + 1) * 100,
                text=f"这是第{i}个测试文本，包含一些内容。",
                chapter_id=i + 1,
            )
            for i in range(chunk_count)
        ]
        chapter_repo.insert_chapter_texts(self.run_id, chunks)

        paragraph_repo = ParagraphRepository(self.db_session)
        spans = [replace(span, token_count=1) for span in split_chunk_paragraphs(chunks)]
        paragraph_repo.insert_paragraphs(self.run_id, spans)
        paragraph_repo.insert_paragraph_topics(
            self.run_id,
            [(span.paragraph_id, 0, 1.0, 1) for span in spans],
        )
        paragraph_repo.insert_paragraph_curves(
            self.run_id,
            [
                ParagraphCurveRow(
                    paragraph_id=span.paragraph_id,
                    pos_density=0.1,
                    neg_density=0.05,
                    net_density=0.05 + span.paragraph_id * 0.01,
                    smoothed_net_density=0.05,
                    surface_tension=0.5,
                    smoothed_surface_tension=0.5,
                )
                for span in spans
            ],
        )

        for i in range(chunk_count):
            persist_chapter_annotation(
                self.db_session,
                run_id=self.run_id,
                chapter_id=i + 1,
                emotional_valences={
                    i + 1: "mild_positive" if i % 2 == 0 else "mild_negative"
                },
                event_types={
                    i + 1: "冲突" if i in {1, 2} else "转折" if i == 3 else "铺垫"
                },
                pivot_chunks={i + 1} if i in {1, 2} else None,
                cliffhanger_chunks={chunk_count} if i == chunk_count - 1 else None,
                characters=[
                    character_fact(
                        chunk_id=i + 1,
                        name=f"角色{i}",
                        action="测试行为",
                        role_function="主体" if i == 0 else "客体",
                    )
                ],
            )
        ForeshadowingRepository(self.db_session).sync(
            run_id=self.run_id,
            chapter_id=1,
            foreshadowing=BoundForeshadowing(
                description="测试伏笔",
                confidence="medium",
                setup_event_index=1,
            ),
            setup_event_id="event-test-setup",
        )

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
        assert set(fetched) == {
            "novel_id",
            "foreshadow_expectation",
            "arc_scores",
            "genre_labels",
            "style_labels",
            "topic_labels",
            "diagnosis",
            "value_logic_type",
            "value_logic_reason",
            "power_stance_score",
            "power_stance_reason",
            "common_people_dignity",
            "dignity_reason",
            "cultural_depth_score",
            "cultural_depth_reason",
            "narrative_arc_type",
            "focus_structure",
            "focus_characters",
            "main_characters",
            "core_cast",
            "theme_color",
            "run_id",
        }
