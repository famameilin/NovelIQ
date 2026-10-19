"""测试任务读写服务的多任务判断逻辑"""

import pytest

from src.storage import new_id
from src.storage.models import Novel, Run
from src.storage.repositories import RunRepository
from src.workflows.tasks import TaskService
from tests.support.run_records import set_run_status
from tests.support.storage_fixtures import storage_for


class TestTaskServiceTaskLogic:
    """测试任务读写服务中多任务判断逻辑"""

    @pytest.fixture(autouse=True)
    def setup(self, db_session, tmp_path):
        """设置测试环境"""
        self.db_session = db_session
        self.run_repo = RunRepository(db_session)
        self.temp_dir = tmp_path
        self.test_novel_id = new_id()

        novel = Novel(
            novel_id=self.test_novel_id,
            filename="test.txt",
            file_path=str(tmp_path / "test.txt"),
            file_size=100,
        )
        db_session.add(novel)
        db_session.commit()

        self.service = TaskService()

        yield

        db_session.query(Run).filter(Run.novelid == self.test_novel_id).delete()
        db_session.query(Novel).filter(Novel.novel_id == self.test_novel_id).delete()
        db_session.commit()

    def _create_run(self, status: str = "pending", run_id: str | None = None) -> str:
        """创建测试运行记录"""
        if run_id is None:
            run_id = new_id()

        run_id = self.run_repo.create_run(novel_id=self.test_novel_id, run_id=run_id)
        set_run_status(self.db_session, run_id, status)
        return run_id

    def test_get_task_counts_by_status_empty(self) -> None:
        """无任务时返回全0"""
        counts = self.service.get_task_counts_by_status(self.test_novel_id, storage_for(self.db_session))
        assert counts["completed"] == 0
        assert counts["running"] == 0
        assert counts["pending"] == 0
        assert counts["failed"] == 0

    def test_get_task_counts_by_status_single_task(self) -> None:
        """单个任务"""
        self._create_run(status="completed")
        counts = self.service.get_task_counts_by_status(self.test_novel_id, storage_for(self.db_session))
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
        counts = self.service.get_task_counts_by_status(self.test_novel_id, storage_for(self.db_session))
        assert counts["completed"] == 1
        assert counts["running"] == 1
        assert counts["pending"] == 1
        assert counts["failed"] == 1

    def test_get_single_valid_task_no_tasks(self) -> None:
        """无任务返回 None"""
        task, error = self.service.get_single_valid_task(self.test_novel_id, storage_for(self.db_session))
        assert task is None
        assert error is None

    def test_get_single_valid_task_single_task(self) -> None:
        """单个任务直接返回"""
        self._create_run(status="completed")
        task, error = self.service.get_single_valid_task(self.test_novel_id, storage_for(self.db_session))
        assert task is not None
        assert error is None
        assert task["status"] == "completed"

    def test_get_single_valid_task_multiple_tasks_error(self) -> None:
        """多个任务返回错误"""
        self._create_run(status="completed")
        self._create_run(status="running")
        task, error = self.service.get_single_valid_task(self.test_novel_id, storage_for(self.db_session))
        assert task is None


class TestAnalysisServiceTaskId:
    """测试 AnalysisService 任务 ID 相关逻辑"""

    @pytest.fixture(autouse=True)
    def setup(self, db_session, tmp_path):
        """设置测试环境"""
        self.db_session = db_session
        self.temp_dir = tmp_path
        self.service = TaskService()

    def test_start_analysis_with_task_id(self) -> None:
        """指定 task_id 启动分析"""
        novel_id = new_id()
        novel = Novel(
            novel_id=novel_id,
            filename="test.txt",
            file_path=str(self.temp_dir / "test.txt"),
            file_size=100,
        )
        self.db_session.add(novel)
        self.db_session.commit()

        task_id = self.service.create_task(novel_id, task_id="1234abcd", session=storage_for(self.db_session))
        assert task_id == "1234abcd"

    def test_start_analysis_with_wrong_task_id(self) -> None:
        """不存在的 task_id"""
        from src.api.exceptions import NovelNotFoundError

        with pytest.raises(NovelNotFoundError):
            self.service.get_task("non-existent-task-id", session=storage_for(self.db_session))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
