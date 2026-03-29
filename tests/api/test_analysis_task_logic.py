"""
2026-03-11: Claude创建
测试analyze接口多任务判断逻辑
"""
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.api.exceptions import AnalysisError
from src.api.services.analysis_service import AnalysisService
from src.api.services.novel_service import NovelService
from src.api.services.task_manager import TaskManager


class TestNovelServiceTaskLogic(unittest.TestCase):
    """测试NovelService中多任务判断逻辑"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.service = NovelService(Path(self.temp_dir))

    def test_get_task_counts_by_status_empty(self):
        """无任务时返回全0"""
        counts = self.service.get_task_counts_by_status("nonexistent")
        self.assertEqual(counts, {"completed": 0, "running": 0, "pending": 0, "failed": 0})

    def test_get_task_counts_by_status_single_task(self):
        """单个任务时正确计数"""
        self.service._novels["test_novel"] = {"novel_id": "test_novel", "file_path": "test.txt"}
        self.service._tasks["task1"] = {"task_id": "task1", "novel_id": "test_novel", "status": "completed"}
        
        counts = self.service.get_task_counts_by_status("test_novel")
        self.assertEqual(counts["completed"], 1)
        self.assertEqual(counts["running"], 0)

    def test_get_task_counts_by_status_multiple_tasks(self):
        """多个任务时正确计数"""
        self.service._novels["test_novel"] = {"novel_id": "test_novel", "file_path": "test.txt"}
        self.service._tasks["task1"] = {"task_id": "task1", "novel_id": "test_novel", "status": "completed"}
        self.service._tasks["task2"] = {"task_id": "task2", "novel_id": "test_novel", "status": "running"}
        self.service._tasks["task3"] = {"task_id": "task3", "novel_id": "test_novel", "status": "failed"}
        
        counts = self.service.get_task_counts_by_status("test_novel")
        self.assertEqual(counts["completed"], 1)
        self.assertEqual(counts["running"], 1)
        self.assertEqual(counts["failed"], 1)

    def test_get_single_valid_task_no_tasks(self):
        """无任务时返回None"""
        task, error = self.service.get_single_valid_task("nonexistent")
        self.assertIsNone(task)
        self.assertIsNone(error)

    def test_get_single_valid_task_single_task(self):
        """单个任务时返回该任务"""
        self.service._novels["test_novel"] = {"novel_id": "test_novel", "file_path": "test.txt"}
        self.service._tasks["task1"] = {"task_id": "task1", "novel_id": "test_novel", "status": "completed"}
        
        task, error = self.service.get_single_valid_task("test_novel")
        self.assertIsNotNone(task)
        self.assertEqual(task["task_id"], "task1")
        self.assertIsNone(error)

    def test_get_single_valid_task_one_running_others_failed(self):
        """一个running + 其他failed时返回running"""
        self.service._novels["test_novel"] = {"novel_id": "test_novel", "file_path": "test.txt"}
        self.service._tasks["task1"] = {"task_id": "task1", "novel_id": "test_novel", "status": "running"}
        self.service._tasks["task2"] = {"task_id": "task2", "novel_id": "test_novel", "status": "failed"}
        
        task, error = self.service.get_single_valid_task("test_novel")
        self.assertIsNotNone(task)
        self.assertEqual(task["task_id"], "task1")
        self.assertEqual(task["status"], "running")
        self.assertIsNone(error)

    def test_get_single_valid_task_multiple_completed_error(self):
        """多个completed时报错"""
        self.service._novels["test_novel"] = {"novel_id": "test_novel", "file_path": "test.txt"}
        self.service._tasks["task1"] = {"task_id": "task1", "novel_id": "test_novel", "status": "completed"}
        self.service._tasks["task2"] = {"task_id": "task2", "novel_id": "test_novel", "status": "completed"}
        
        task, error = self.service.get_single_valid_task("test_novel")
        self.assertIsNone(task)
        self.assertIn("多个已完成任务", error)

    def test_get_single_valid_task_multiple_running_error(self):
        """多个running时报错"""
        self.service._novels["test_novel"] = {"novel_id": "test_novel", "file_path": "test.txt"}
        self.service._tasks["task1"] = {"task_id": "task1", "novel_id": "test_novel", "status": "running"}
        self.service._tasks["task2"] = {"task_id": "task2", "novel_id": "test_novel", "status": "running"}
        
        task, error = self.service.get_single_valid_task("test_novel")
        self.assertIsNone(task)
        self.assertIn("多个运行中任务", error)

    def test_get_single_valid_task_multiple_failed_error(self):
        """多个failed时报错"""
        self.service._novels["test_novel"] = {"novel_id": "test_novel", "file_path": "test.txt"}
        self.service._tasks["task1"] = {"task_id": "task1", "novel_id": "test_novel", "status": "failed"}
        self.service._tasks["task2"] = {"task_id": "task2", "novel_id": "test_novel", "status": "failed"}
        
        task, error = self.service.get_single_valid_task("test_novel")
        self.assertIsNone(task)
        self.assertIn("多个失败任务", error)

    def test_get_single_valid_task_multiple_pending_error(self):
        """多个pending时报错"""
        self.service._novels["test_novel"] = {"novel_id": "test_novel", "file_path": "test.txt"}
        self.service._tasks["task1"] = {"task_id": "task1", "novel_id": "test_novel", "status": "pending"}
        self.service._tasks["task2"] = {"task_id": "task2", "novel_id": "test_novel", "status": "pending"}
        
        task, error = self.service.get_single_valid_task("test_novel")
        self.assertIsNone(task)
        self.assertIn("多个待处理任务", error)

    def test_get_single_valid_task_running_and_failed_error(self):
        """多个running + 多个failed时报错"""
        self.service._novels["test_novel"] = {"novel_id": "test_novel", "file_path": "test.txt"}
        self.service._tasks["task1"] = {"task_id": "task1", "novel_id": "test_novel", "status": "running"}
        self.service._tasks["task2"] = {"task_id": "task2", "novel_id": "test_novel", "status": "running"}
        self.service._tasks["task3"] = {"task_id": "task3", "novel_id": "test_novel", "status": "failed"}
        
        task, error = self.service.get_single_valid_task("test_novel")
        self.assertIsNone(task)
        self.assertIn("请指定task_id", error)


@pytest.mark.asyncio
class TestAnalysisServiceTaskId(unittest.IsolatedAsyncioTestCase):
    """测试AnalysisService中task_id参数逻辑"""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.novel_service = NovelService(Path(self.temp_dir))
        self.task_manager = TaskManager()
        self.analysis_service = AnalysisService(self.novel_service, self.task_manager)

    async def asyncTearDown(self):
        pass

    async def test_start_analysis_with_task_id(self):
        """指定task_id时使用该task_id"""
        self.novel_service._novels["test_novel"] = {
            "novel_id": "test_novel",
            "file_path": str(Path(self.temp_dir) / "test.txt"),
        }
        self.novel_service._tasks["existing_task"] = {
            "task_id": "existing_task",
            "novel_id": "test_novel",
            "status": "pending",
            "db_path": str(Path(self.temp_dir) / "existing_task.db"),
        }
        
        Path(self.temp_dir, "test.txt").write_text("test content")
        
        from src.api.models.requests import AnalyzeRequest
        request = AnalyzeRequest(task_id="existing_task")
        
        task_id = await self.analysis_service.start_analysis("test_novel", request)
        self.assertEqual(task_id, "existing_task")

    async def test_start_analysis_with_wrong_task_id(self):
        """指定不属于该小说的task_id时报错"""
        self.novel_service._novels["test_novel"] = {
            "novel_id": "test_novel",
            "file_path": str(Path(self.temp_dir) / "test.txt"),
        }
        self.novel_service._novels["other_novel"] = {
            "novel_id": "other_novel",
            "file_path": str(Path(self.temp_dir) / "other.txt"),
        }
        self.novel_service._tasks["other_task"] = {
            "task_id": "other_task",
            "novel_id": "other_novel",
            "status": "pending",
        }
        
        from src.api.models.requests import AnalyzeRequest
        request = AnalyzeRequest(task_id="other_task")
        
        with self.assertRaises(AnalysisError) as context:
            await self.analysis_service.start_analysis("test_novel", request)
        self.assertIn("不属于", str(context.exception))


if __name__ == "__main__":
    unittest.main()
