"""
诊断 Agent 工作流测试（CLI 入口）

说明: run_diagnose 已 agent 化，测试通过 patch run_diagnosis_agent 注入假诊断结果
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.cloud.schema import CloudAnalysis
from src.storage.models import Novel
from src.storage.repositories import RunRepository
from src.workflows.diagnose import run_diagnose


def _insert_test_novel(db_session, novel_id: str) -> None:
    """
    创建测试用 Novel 记录，避免 create_run 时 ForeignKeyViolation
    """
    db_session.add(
        Novel(
            novel_id=novel_id,
            filename=f"{novel_id}.txt",
            file_path=f"data/uploads/{novel_id}.txt",
            file_size=128,
        )
    )
    db_session.commit()


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


class TestCli:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, tmp_path):
        self.db_session = db_session
        self.tmp_path = tmp_path
        self.novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, self.novel_id)

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    @pytest.mark.asyncio()
    async def test_agent_diagnose_writes_db(self) -> None:
        fake = AsyncMock(return_value=_fake_analysis(self.novel_id))
        with patch("src.agents.run_diagnosis_agent", new=fake):
            analysis = await run_diagnose(
                run_id=self.run_id,
                session=self.db_session,
                analysis_logger=None,
            )

        assert analysis.genre_labels == ["通用"]
        assert analysis.style_labels == ["严肃"]
        fake.assert_awaited_once()

        row = self.db_session.execute(
            text("SELECT genre_labels, style_labels FROM cloud_analysis WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).fetchone()
        assert row[0] == '["通用"]'
        assert row[1] == '["严肃"]'
