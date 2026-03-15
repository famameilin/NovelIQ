"""
云端诊断 CLI 测试

创建时间: 2025-03-11
创建者: TraeAI
任务: 测试云端诊断 CLI

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

from src.workflows.diagnose import run_cloud_diagnose
from src.storage.repositories import RunRepository

from conftest import FakeClient


class TestCli:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, tmp_path):
        self.db_session = db_session
        self.tmp_path = tmp_path
        self.novel_id = f"novel_{uuid.uuid4().hex[:8]}"

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def test_cloud_diagnose_writes_db(self) -> None:
        source_path = self.tmp_path / f"{self.novel_id}.txt"
        source_path.write_text("测试文本", encoding="utf-8")

        analysis = run_cloud_diagnose(
            source_path=source_path,
            run_id=self.run_id,
            session=self.db_session,
            metadata_path=None,
            cache_path=None,
            client=FakeClient(),
        )

        assert analysis.novel_id == self.novel_id

        row = self.db_session.execute(
            text("SELECT novel_id FROM cloud_analysis WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).fetchone()
        assert row[0] == self.novel_id
