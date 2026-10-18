"""分析任务读写与产物清理（work 队列侧）

2026-10-06 自 `src/ingest/novel_service.py` 收归：任务的创建、查询、删除，小说记录的
读取，以及 logs/outputs 产物清理都属于运行生命周期，归 work 队列；小说源文件的上传与
登记属于 api 的文本导入（`src/api/services/novel_service.py`）。

本模块只读写存储与文件系统，不碰 HTTP、不碰 SSE。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from src.storage import Storage, get_storage
from src.storage.id_mapping import generate_task_id, run_id_to_task_id
from src.storage.records.models import NovelRecord
from src.work.artifacts import ArtifactGcService
from src.workflows.exceptions import NovelNotFoundError

if TYPE_CHECKING:
    from src.work.task_manager import TaskManager


TASK_DELETE_BLOCKING_STATUSES = ("pending", "running", "cancelling")


class TaskService:
    """任务/运行记录的读写与删除（含产物清理）"""

    def __init__(self, logs_dir: Path | None = None, outputs_dir: Path | None = None) -> None:
        self.logs_dir = logs_dir or Path("logs")
        self.outputs_dir = outputs_dir or Path("outputs")
        self._artifact_gc_service = ArtifactGcService(self.logs_dir, self.outputs_dir)

    def _require_novel(self, sess: Storage, novel_id: str) -> NovelRecord:
        novel = sess.novels.get(novel_id)
        if not novel:
            raise NovelNotFoundError(f"小说不存在: {novel_id}")
        return novel

    def get_novel(self, novel_id: str, session: Storage | None = None) -> dict:
        """读取小说记录（run 侧需要标题与源文件路径，经此读取以免反向依赖 api）"""
        sess = session or get_storage()
        novel = self._require_novel(sess, novel_id)
        return {
            "novel_id": novel.novel_id,
            "filename": novel.filename,
            "file_path": novel.file_path,
            "title": novel.title,
            "author": novel.author,
            "file_size": novel.file_size,
            "upload_time": novel.upload_time.isoformat() if novel.upload_time else None,
            "status": "uploaded",
        }

    def get_run_by_task_id(self, task_id: str, session: Storage | None = None) -> dict | None:
        """获取任务对应的运行记录"""
        sess = session or get_storage()
        run = sess.runs.get_run_by_task_id(task_id)
        if run:
            return {
                "task_id": task_id,
                "novel_id": run["novel_id"],
                "status": run["status"],
                "run_id": run["run_id"],
                "task_kind": run["task_kind"],
                "request_payload": run["request_payload"],
            }
        return None

    def create_task(
        self,
        novel_id: str,
        task_id: str | None = None,
        session: Storage | None = None,
        task_kind: str = "analysis",
        request_payload: dict | None = None,
    ) -> str:
        """创建分析任务（小说必须先存在）"""
        if task_id is None:
            task_id = generate_task_id()

        try:
            sess = session or get_storage()
            self._require_novel(sess, novel_id)
            sess.runs.create_run(
                novel_id=novel_id,
                task_id=task_id,
                task_kind=task_kind,
                request_payload=request_payload,
            )
        except Exception as e:
            logger.error(f"Failed to create run in DB for novel {novel_id}, task {task_id}: {e}")
            raise

        logger.info(f"Created task: {task_id} for novel {novel_id}")
        return task_id

    def load_task(self, task_id: str, session: Storage | None = None) -> dict | None:
        """从数据库加载任务完整信息（含运行时状态字段）"""
        sess = session or get_storage()
        run = sess.runs.get_run_by_task_id(task_id)
        if run:
            return {
                "task_id": task_id,
                "novel_id": run["novel_id"],
                "status": run["status"],
                "run_id": run["run_id"],
                "task_kind": run["task_kind"],
                "request_payload": run["request_payload"],
                "progress": run.get("progress", 0.0),
                "stage": run.get("stage"),
                "sub_stage": run.get("sub_stage"),
                "current": run.get("current"),
                "total": run.get("total"),
                "message": run.get("message"),
                "error": run.get("error"),
                "started_at": run.get("started_at"),
                "completed_at": run.get("completed_at"),
            }
        return None

    def get_task(self, task_id: str, session: Storage | None = None) -> dict:
        """获取任务信息"""
        task = self.load_task(task_id, session)
        if task:
            return task
        raise NovelNotFoundError(f"任务不存在: {task_id}")

    def get_tasks_by_novel(self, novel_id: str, session: Storage | None = None) -> list[dict]:
        """获取小说的所有任务"""
        sess = session or get_storage()
        runs = sess.runs.get_runs_by_novel(novel_id)
        return [
            {
                "task_id": run["task_id"],
                "novel_id": run["novel_id"],
                "status": run["status"],
                "run_id": run["run_id"],
                "created_at": run["created_at"],
            }
            for run in runs
        ]

    def get_task_counts_by_status(self, novel_id: str, session: Storage | None = None) -> dict[str, int]:
        """获取各状态的任务数量"""
        tasks = self.get_tasks_by_novel(novel_id, session)
        counts: dict[str, int] = {"completed": 0, "running": 0, "pending": 0, "failed": 0}
        for task in tasks:
            status = task.get("status", "unknown")
            if status in counts:
                counts[status] += 1
        return counts

    def get_single_valid_task(self, novel_id: str, session: Storage | None = None) -> tuple[dict | None, str | None]:
        """获取唯一的合法任务"""
        tasks = self.get_tasks_by_novel(novel_id, session)
        if not tasks:
            return None, None
        if len(tasks) == 1:
            return tasks[0], None
        return None, f"存在{len(tasks)}个任务，请指定task_id"

    def collect_runs(self, novel_id: str, session: Storage | None = None) -> list[dict]:
        """收集小说下的全部任务（小说删除前的前置读取）"""
        sess = session or get_storage()
        self._require_novel(sess, novel_id)
        return sess.runs.get_runs_by_novel(novel_id)

    def ensure_tasks_deletable(self, novel_id: str, runs: list[dict]) -> None:
        """校验小说下的任务是否都允许删除

        说明: novel 级删除沿用 task 删除状态机，不允许绕过 pending/running/cancelling 护栏
        """
        for run in runs:
            status = str(run.get("status", ""))
            if status in TASK_DELETE_BLOCKING_STATUSES:
                task_id = str(run["task_id"])
                raise ValueError(f"小说 {novel_id} 下的任务 {task_id} 正在{status}中，请先取消任务后再删除小说")

    def delete_run_data(self, run_id: str, session: Storage | None = None) -> None:
        """删除单个 run 的数据库数据与文件产物"""
        sess = session or get_storage()
        task_id = run_id_to_task_id(run_id, sess)
        sess.runs.delete_run(run_id)
        self._artifact_gc_service.delete_task_artifacts(task_id, run_id)
        logger.info(f"Run deleted from database and artifacts cleaned: run_id={run_id}, task_id={task_id}")

    def delete_task(
        self,
        task_id: str,
        session: Storage | None = None,
        task_manager: TaskManager | None = None,
    ) -> bool:
        """删除任务及其数据库/文件产物"""
        run_id: str | None = None
        sess = session or get_storage()
        run = sess.runs.get_run_by_task_id(task_id)
        if run:
            run_id = str(run["run_id"])

        if task_manager is not None:
            # TaskManager 只负责当前进程的执行缓存，删除 task 时顺手清掉缓存，
            # 避免 DB 已删除但本进程里还残留已终态任务对象
            task_manager.delete_task(task_id)

        if run_id is not None:
            self.delete_run_data(run_id, session=session)
        else:
            self._artifact_gc_service.delete_task_artifacts(task_id, task_id)
            logger.info(f"Task artifacts cleaned without DB run record: task_id={task_id}")

        return True

    def delete_novel_source_file(self, file_path: str | None) -> None:
        """删除小说源文件（小说级删除的文件侧步骤）"""
        self._artifact_gc_service.delete_novel_source_file(file_path)
