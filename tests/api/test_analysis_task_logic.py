"""
测试 NovelService 任务判断逻辑

创建时间: 2026-03-11
修改时间: 2026-04-08
修改者: TraeAI
任务: 重写测试以匹配当前 NovelService API
修改内容: 基于当前 NovelService 实现重写测试，使用依赖注入的 session
说明: 只有 1 个 task 时返回，多个 task 时报错
"""
import uuid
from pathlib import Path

import pytest

from src.api.services.novel_service import NovelService
from src.storage.models import Novel, AnalysisRun
from src.storage.repositories import RunRepository


class TestNovelServiceTaskLogic:
    """测试 NovelService 中多任务判断逻辑"""

    @pytest.fixture(autouse=True)
    def setup(self, db_session, tmp_path):
        """设置测试环境"""
        self.db_session = db_session
        self.run_repo = RunRepository(db_session)
        self.temp_dir = tmp_path
        self.test_novel_id = str(uuid.uuid4())[:8]

        novel = Novel(
            novel_id=self.test_novel_id,
            filename="test.txt",
            file_path=str(tmp_path / "test.txt"),
            file_size=100,
        )
        db_session.add(novel)
        db_session.commit()

        self.service = NovelService(tmp_path)

        yield

        db_session.query(AnalysisRun).filter(AnalysisRun.novel_id == self.test_novel_id).delete()
        db_session.query(Novel).filter(Novel.novel_id == self.test_novel_id).delete()
        db_session.commit()

    def _create_run(self, status: str = "pending", run_id: str | None = None) -> str:
        """创建测试运行记录"""
        if run_id is None:
            run_id = str(uuid.uuid4())

        run = AnalysisRun(
            run_id=run_id,
            novel_id=self.test_novel_id,
            source_path="test.txt",
            title="Test Novel",
            author="Test Author",
            status=status,
        )
        self.db_session.add(run)
        self.db_session.commit()
        return run_id

    def test_get_task_counts_by_status_empty(self) -> None:
        """无任务时返回全0"""
        counts = self.service.get_task_counts_by_status(self.test_novel_id, self.db_session)
        assert counts["completed"] == 0
        assert counts["running"] == 0
        assert counts["pending"] == 0
        assert counts["failed"] == 0

    def test_get_task_counts_by_status_single_task(self) -> None:
        """单个任务"""
        self._create_run(status="completed")
        counts = self.service.get_task_counts_by_status(self.test_novel_id, self.db_session)
        assert counts["completed"] == 1
        assert counts["running"] == 0
        assert counts["pending"] == 0
        assert counts["failed"] == 0

    def test_get_task_counts_by_status_multiple_tasks(self) -> None:
        """多个任务各状态"""
        self._create_run(status="completed")
        self._create_run(status="running")
        self._create_run(status="pending")
        self._create_run(status="failed")
        counts = self.service.get_task_counts_by_status(self.test_novel_id, self.db_session)
        assert counts["completed"] == 1
        assert counts["running"] == 1
        assert counts["pending"] == 1
        assert counts["failed"] == 1

    def test_get_single_valid_task_no_tasks(self) -> None:
        """无任务返回 None"""
        task, error = self.service.get_single_valid_task(self.test_novel_id, self.db_session)
        assert task is None
        assert error is None

    def test_get_single_valid_task_single_task(self) -> None:
        """单个任务直接返回"""
        self._create_run(status="completed")
        task, error = self.service.get_single_valid_task(self.test_novel_id, self.db_session)
        assert task is not None
        assert error is None
        assert task["status"] == "completed"

    def test_get_single_valid_task_multiple_tasks_error(self) -> None:
        """多个任务返回错误"""
        self._create_run(status="completed")
        self._create_run(status="running")
        task, error = self.service.get_single_valid_task(self.test_novel_id, self.db_session)
        assert task is None
        assert "存在2个任务" in error


class TestAnalysisServiceTaskId:
    """测试 AnalysisService 任务 ID 相关逻辑"""

    @pytest.fixture(autouse=True)
    def setup(self, db_session, tmp_path):
        """设置测试环境"""
        self.db_session = db_session
        self.temp_dir = tmp_path
        self.service = NovelService(tmp_path)

    def test_start_analysis_with_task_id(self) -> None:
        """指定 task_id 启动分析"""
        novel_id = str(uuid.uuid4())[:8]
        novel = Novel(
            novel_id=novel_id,
            filename="test.txt",
            file_path=str(self.temp_dir / "test.txt"),
            file_size=100,
        )
        self.db_session.add(novel)
        self.db_session.commit()

        task_id = self.service.create_task(novel_id, task_id="test-task-001", session=self.db_session)
        assert task_id == "test-task-001"

    def test_start_analysis_with_wrong_task_id(self) -> None:
        """不存在的 task_id"""
        from src.api.exceptions import NovelNotFoundError

        with pytest.raises(NovelNotFoundError):
            self.service.get_task("non-existent-task-id", session=self.db_session)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])