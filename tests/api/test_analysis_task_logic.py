"""
2026-03-11: Claude创建
测试analyze接口多任务判断逻辑

修改时间: 2026-04-05
修改者: TraeAI
任务: 修复测试使用测试数据库
修改内容: 重构测试使用 pytest 风格，mock get_session_factory 使用测试数据库
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.api.exceptions import AnalysisError
from src.api.services.analysis_service import AnalysisService
from src.api.services.novel_service import NovelService
from src.api.services.task_manager import TaskManager
from src.storage.repositories import RunRepository


class TestNovelServiceTaskLogic:
    """测试NovelService中多任务判断逻辑"""

    @pytest.fixture(autouse=True)
    def setup(self, db_session, tmp_path):
        """设置测试环境"""
        self.db_session = db_session
        self.run_repo = RunRepository(db_session)
        self.temp_dir = tmp_path
        self.test_novel_id = "test_novel"

        def mock_session_factory():
            class SessionContext:
                def __enter__(self):
                    return db_session

                def __exit__(self, *args):
                    pass

            return SessionContext()

        with patch("src.api.services.novel_service.get_session_factory", return_value=mock_session_factory):
            self.service = NovelService(self.temp_dir)
            self.service._novels[self.test_novel_id] = {
                "novel_id": self.test_novel_id,
                "file_path": "test.txt",
            }
            yield

        self.db_session.execute(text("DELETE FROM analysis_runs"))
        self.db_session.commit()

    def _create_run(self, novel_id: str, status: str = "pending", run_id: str | None = None) -> str:
        """创建测试运行记录"""
        created_run_id = self.run_repo.create_run(
            novel_id=novel_id,
            source_path="test.txt",
            title="Test Novel",
            author="Test Author",
            run_id=run_id,
        )
        if status != "pending":
            self.run_repo.update_run_status(created_run_id, status)
        return created_run_id

    def test_get_task_counts_by_status_empty(self):
        """无任务时返回全0"""
        counts = self.service.get_task_counts_by_status("nonexistent")
        assert counts == {"completed": 0, "running": 0, "pending": 0, "failed": 0}

    def test_get_task_counts_by_status_single_task(self):
        """单个任务时正确计数"""
        self._create_run(self.test_novel_id, "completed")

        counts = self.service.get_task_counts_by_status(self.test_novel_id)
        assert counts["completed"] == 1
        assert counts["running"] == 0

    def test_get_task_counts_by_status_multiple_tasks(self):
        """多个任务时正确计数"""
        self._create_run(self.test_novel_id, "completed")
        self._create_run(self.test_novel_id, "running")
        self._create_run(self.test_novel_id, "failed")

        counts = self.service.get_task_counts_by_status(self.test_novel_id)
        assert counts["completed"] == 1
        assert counts["running"] == 1
        assert counts["failed"] == 1

    def test_get_single_valid_task_no_tasks(self):
        """无任务时返回None"""
        task, error = self.service.get_single_valid_task("nonexistent")
        assert task is None
        assert error is None

    def test_get_single_valid_task_single_task(self):
        """单个任务时返回该任务"""
        self._create_run(self.test_novel_id, "completed")

        task, error = self.service.get_single_valid_task(self.test_novel_id)
        assert task is not None
        assert error is None

    def test_get_single_valid_task_one_running_others_failed(self):
        """一个running + 其他failed时返回running"""
        self._create_run(self.test_novel_id, "running")
        self._create_run(self.test_novel_id, "failed")

        task, error = self.service.get_single_valid_task(self.test_novel_id)
        assert task is not None
        assert task["status"] == "running"
        assert error is None

    def test_get_single_valid_task_multiple_completed_error(self):
        """多个completed时报错"""
        self._create_run(self.test_novel_id, "completed")
        self._create_run(self.test_novel_id, "completed")

        task, error = self.service.get_single_valid_task(self.test_novel_id)
        assert task is None
        assert "多个已完成任务" in error

    def test_get_single_valid_task_multiple_running_error(self):
        """多个running时报错"""
        self._create_run(self.test_novel_id, "running")
        self._create_run(self.test_novel_id, "running")

        task, error = self.service.get_single_valid_task(self.test_novel_id)
        assert task is None
        assert "多个运行中任务" in error

    def test_get_single_valid_task_multiple_failed_error(self):
        """多个failed时报错"""
        self._create_run(self.test_novel_id, "failed")
        self._create_run(self.test_novel_id, "failed")

        task, error = self.service.get_single_valid_task(self.test_novel_id)
        assert task is None
        assert "多个失败任务" in error

    def test_get_single_valid_task_multiple_pending_error(self):
        """多个pending时报错"""
        self._create_run(self.test_novel_id, "pending")
        self._create_run(self.test_novel_id, "pending")

        task, error = self.service.get_single_valid_task(self.test_novel_id)
        assert task is None
        assert "多个待处理任务" in error

    def test_get_single_valid_task_running_and_failed_error(self):
        """多个running + 多个failed时报错"""
        self._create_run(self.test_novel_id, "running")
        self._create_run(self.test_novel_id, "running")
        self._create_run(self.test_novel_id, "failed")

        task, error = self.service.get_single_valid_task(self.test_novel_id)
        assert task is None
        assert "请指定task_id" in error


class TestAnalysisServiceTaskId:
    """测试AnalysisService中task_id参数逻辑"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.temp_dir = tmp_path
        self.novel_service = NovelService(self.temp_dir)
        self.task_manager = TaskManager()
        self.analysis_service = AnalysisService(self.novel_service, self.task_manager)

    def test_start_analysis_with_task_id(self):
        """指定task_id时使用该task_id"""
        self.novel_service._novels["test_novel"] = {
            "novel_id": "test_novel",
            "file_path": str(self.temp_dir / "test.txt"),
        }
        self.novel_service._tasks["existing_task"] = {
            "task_id": "existing_task",
            "novel_id": "test_novel",
            "status": "pending",
            "db_path": str(self.temp_dir / "existing_task.db"),
        }

        (self.temp_dir / "test.txt").write_text("test content")

        from src.api.models.requests import AnalyzeRequest

        request = AnalyzeRequest(task_id="existing_task")

        task_id = asyncio.run(self.analysis_service.start_analysis("test_novel", request))
        assert task_id == "existing_task"

    def test_start_analysis_with_wrong_task_id(self):
        """指定不属于该小说的task_id时报错"""
        self.novel_service._novels["test_novel"] = {
            "novel_id": "test_novel",
            "file_path": str(self.temp_dir / "test.txt"),
        }
        self.novel_service._novels["other_novel"] = {
            "novel_id": "other_novel",
            "file_path": str(self.temp_dir / "other.txt"),
        }
        self.novel_service._tasks["other_task"] = {
            "task_id": "other_task",
            "novel_id": "other_novel",
            "status": "pending",
        }

        from src.api.models.requests import AnalyzeRequest

        request = AnalyzeRequest(task_id="other_task")

        with pytest.raises(AnalysisError) as context:
            asyncio.run(self.analysis_service.start_analysis("test_novel", request))
        assert "不属于" in str(context.value)
