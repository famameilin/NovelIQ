"""
诊断 Agent 工作流测试（CLI 入口）

说明: run_diagnose 已 agent 化，测试通过 patch run_diagnosis_agent 注入假诊断结果
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.agents.diagnosis.schema import AgentAnalysis
from src.storage.repositories import RunRepository
from src.workflows.diagnose import run_diagnose
from tests.support.analysis_factories import insert_test_novel


def _fake_analysis(novel_id: str) -> AgentAnalysis:
    return AgentAnalysis(
        novel_id=novel_id,
        foreshadow_expectation=0.1,
        arc_scores={"角色0": 8.5, "角色1": 7.0},
        genre_labels=["通用"],
        style_labels=["严肃"],
        topic_labels={'0': '成长'},
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
        insert_test_novel(self.novel_id, session=db_session)

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    @pytest.mark.asyncio()
    async def test_agent_diagnose_writes_db(self) -> None:
        from tests.support.chapter_annotation_helpers import create_run_with_chunks, persist_chapter_annotation
        self.novel_id, self.run_id = create_run_with_chunks(self.db_session, texts=["测试小说正文。"])
        persist_chapter_annotation(self.db_session, run_id=self.run_id, chapter_id=1)
        fake = AsyncMock(return_value=_fake_analysis(self.novel_id))
        with patch("src.agents.run_diagnosis_agent", new=fake):
            analysis = await run_diagnose(
                run_id=self.run_id,
                session=self.db_session,
                analysis_logger=None,
            )

        assert analysis.genre_labels == ["通用"]
        assert analysis.style_labels == ["严肃"]
        # 诊断 agent 完整通过注解完成度闸门并被派发；落库断言见
        # tests/workflows/test_agent_diagnose_routes.py 的真 agent 路径
        fake.assert_awaited_once()
