"""
云端诊断 CLI 测试

"""

import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from conftest import FakeClient

from src.storage.models import Novel
from src.storage.repositories import RunRepository
from src.workflows.diagnose import run_diagnose


def _insert_test_novel(db_session, novel_id: str) -> None:
    """
    创建测试用 Novel 记录，避免 create_run 时 ForeignKeyViolation。

    创建时间: 2026-04-23
    任务: 修复 pytest ForeignKeyViolation
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
    async def test_cloud_diagnose_writes_db(self) -> None:
        analysis = await run_diagnose(
            run_id=self.run_id,
            session=self.db_session,
            cache_path=None,
            client=FakeClient(),
            analysis_logger=None,
        )

        assert analysis.narrative_type == "三幕"

        row = self.db_session.execute(
            text("SELECT narrative_type FROM cloud_analysis WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).fetchone()
        assert row[0] == "三幕"
