"""
小说服务类

创建时间: 2025-03-11
创建者: TraeAI
任务: 小说服务

修改历史:
- 2026-03-14: 使用 Repository 模式重构，移除 .db 路径相关逻辑
- 2026-03-15: PostgreSQL 迁移，完全移除 .db 文件扫描逻辑

说明: 管理小说文件上传、任务创建和状态查询，使用 PostgreSQL 数据库存储任务元数据。
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import aiofiles
from loguru import logger

from src.api.exceptions import FileStorageError, InvalidFileError, NovelNotFoundError
from src.storage.db import get_session_factory
from src.storage.id_mapping import generate_task_id
from src.storage.repositories import RunRepository


class NovelService:
    """小说服务类 - 管理小说文件上传、任务创建和状态查询"""

    def __init__(self, upload_dir: Path):
        self.upload_dir = upload_dir
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self._novels: dict[str, dict] = {}
        self._tasks: dict[str, dict] = {}
        self._scan_existing_novels()

    def _scan_existing_novels(self) -> None:
        """扫描已存在的小说文件和任务元数据"""
        for file_path in self.upload_dir.glob("*.txt"):
            filename = file_path.name
            if "_" in filename:
                novel_id = filename.split("_")[0]
                original_filename = "_".join(filename.split("_")[1:])
                self._novels[novel_id] = {
                    "novel_id": novel_id,
                    "filename": original_filename,
                    "file_path": str(file_path),
                    "status": "uploaded",
                }
                logger.debug(f"Restored novel metadata: {novel_id} - {original_filename}")

        self._restore_tasks_from_database()

    def _restore_tasks_from_database(self) -> None:
        """从 PostgreSQL 数据库恢复任务元数据"""
        try:
            session_factory = get_session_factory()
            with session_factory() as session:
                run_repo = RunRepository(session)
                for novel_id in self._novels.keys():
                    runs = run_repo.get_runs_by_novel(novel_id)
                    for run in runs:
                        run_id = run["run_id"]
                        task_id = run_id[:8] if len(run_id) >= 8 else run_id
                        self._tasks[task_id] = {
                            "task_id": task_id,
                            "novel_id": novel_id,
                            "status": run["status"],
                            "run_id": run_id,
                        }
                        logger.debug(f"Restored task metadata: {task_id} for novel {novel_id}")
        except Exception as e:
            logger.warning(f"Failed to restore tasks from database: {e}")

    async def save_upload(self, file_content: bytes, filename: str) -> str:
        """保存上传的文件"""
        if not filename.endswith(".txt"):
            raise InvalidFileError("只支持 .txt 文件")

        novel_id = str(uuid.uuid4())[:8]

        file_path = self.upload_dir / f"{novel_id}_{filename}"
        try:
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(file_content)
        except Exception as e:
            raise FileStorageError(f"文件保存失败: {e}") from e

        self._novels[novel_id] = {
            "novel_id": novel_id,
            "filename": filename,
            "file_path": str(file_path),
            "status": "uploaded",
        }

        logger.info(f"Novel uploaded: {novel_id} - {filename}")
        return novel_id

    def get_novel(self, novel_id: str) -> dict:
        """获取小说信息"""
        if novel_id not in self._novels:
            raise NovelNotFoundError(f"小说不存在: {novel_id}")
        return self._novels[novel_id]

    def get_run_by_task_id(self, task_id: str) -> dict | None:
        """获取任务对应的运行记录"""
        if task_id not in self._tasks:
            return None

        task = self._tasks[task_id]
        return task

    def create_task(self, novel_id: str, task_id: str | None = None) -> str:
        """创建分析任务

        创建时间: 2025-03-11
        创建者: TraeAI
        任务: 小说服务

        修改时间: 2026-03-19
        修改者: TraeAI
        任务: ID系统统一优化
        修改内容: 使用generate_task_id()生成task_id

        修改时间: 2026-03-19
        修改者: TraeAI
        任务: 修复task_id和run_id不关联的问题
        修改内容: 添加task_id参数，支持外部传入task_id
        """
        self.get_novel(novel_id)
        if task_id is None:
            task_id = generate_task_id()

        self._tasks[task_id] = {
            "task_id": task_id,
            "novel_id": novel_id,
            "status": "pending",
        }

        logger.info(f"Created task: {task_id} for novel {novel_id}")
        return task_id

    def get_task(self, task_id: str) -> dict:
        """获取任务信息"""
        if task_id not in self._tasks:
            # 尝试从数据库加载
            task = self._load_task_from_db(task_id)
            if task:
                self._tasks[task_id] = task
                return task
            raise NovelNotFoundError(f"任务不存在: {task_id}")
        return self._tasks[task_id]

    def _load_task_from_db(self, task_id: str) -> dict | None:
        """从数据库加载任务元数据

        修改时间: 2026-03-19
        修改者: TraeAI
        任务: Repository层ID统一优化
        修改内容: 使用get_run_by_run_id_prefix替代get_run_by_task_id
        """
        try:
            session_factory = get_session_factory()
            with session_factory() as session:
                run_repo = RunRepository(session)
                # task_id是run_id的前8位，使用前缀匹配查询
                run = run_repo.get_run_by_run_id_prefix(task_id)
                if run:
                    return {
                        "task_id": task_id,
                        "novel_id": run["novel_id"],
                        "status": run["status"],
                        "run_id": run["run_id"],
                    }
        except Exception as e:
            logger.warning(f"从数据库加载任务失败: {e}")
        return None

    def update_task_status(self, task_id: str, status: str) -> None:
        """更新任务状态"""
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = status

    def get_tasks_by_novel(self, novel_id: str) -> list[dict]:
        """获取小说的所有任务

        从数据库读取，而不是从内存读取
        """
        try:
            session_factory = get_session_factory()
            with session_factory() as session:
                from src.storage.repositories import RunRepository
                run_repo = RunRepository(session)
                runs = run_repo.get_runs_by_novel(novel_id)
                return [
                    {
                        "task_id": run["run_id"][:8] if len(run["run_id"]) >= 8 else run["run_id"],
                        "novel_id": run["novel_id"],
                        "status": run["status"],
                        "run_id": run["run_id"],
                    }
                    for run in runs
                ]
        except Exception as e:
            logger.warning(f"Failed to get tasks from database: {e}")
            return []

    def get_latest_completed_task(self, novel_id: str) -> dict | None:
        """获取小说的最新已完成任务"""
        tasks = self.get_tasks_by_novel(novel_id)
        completed_tasks = [t for t in tasks if t.get("status") == "completed"]
        if not completed_tasks:
            return None
        return completed_tasks[-1]

    def get_latest_task(self, novel_id: str) -> dict | None:
        """
        获取小说的最新任务

        优先级：completed > running > pending > failed
        """
        tasks = self.get_tasks_by_novel(novel_id)
        if not tasks:
            return None

        priority_order = {"completed": 4, "running": 3, "pending": 2, "failed": 1}
        sorted_tasks = sorted(
            tasks, key=lambda t: (priority_order.get(t.get("status", ""), 0), t.get("task_id", "")), reverse=True
        )
        return sorted_tasks[0] if sorted_tasks else None

    def get_task_counts_by_status(self, novel_id: str) -> dict[str, int]:
        """获取各状态的任务数量"""
        tasks = self.get_tasks_by_novel(novel_id)
        counts: dict[str, int] = {"completed": 0, "running": 0, "pending": 0, "failed": 0}
        for task in tasks:
            status = task.get("status", "unknown")
            if status in counts:
                counts[status] += 1
        return counts

    def get_single_valid_task(self, novel_id: str) -> tuple[dict | None, str | None]:
        """
        获取唯一的合法任务

        返回: (task, error_message)
        - 如果只有一个任务，返回它
        - 如果有多个任务，按规则判断：
          - 一个running + 其他failed → 返回running
          - 多个completed/多个running/多个failed/多个pending → 返回错误
        """
        tasks = self.get_tasks_by_novel(novel_id)
        if not tasks:
            return None, None

        if len(tasks) == 1:
            return tasks[0], None

        counts = self.get_task_counts_by_status(novel_id)

        if counts["running"] == 1 and counts["completed"] == 0 and counts["pending"] == 0:
            running_tasks = [t for t in tasks if t.get("status") == "running"]
            return running_tasks[0], None

        if counts["completed"] > 1:
            return None, f"存在多个已完成任务({counts['completed']}个)，请指定task_id"
        if counts["running"] > 1:
            return None, f"存在多个运行中任务({counts['running']}个)，请指定task_id"
        if counts["failed"] > 1:
            return None, f"存在多个失败任务({counts['failed']}个)，请指定task_id"
        if counts["pending"] > 1:
            return None, f"存在多个待处理任务({counts['pending']}个)，请指定task_id"
        if counts["running"] > 0 and counts["failed"] > 0:
            return None, f"存在多个任务(running:{counts['running']}, failed:{counts['failed']})，请指定task_id"

        priority_order = {"completed": 4, "running": 3, "pending": 2, "failed": 1}
        sorted_tasks = sorted(
            tasks, key=lambda t: (priority_order.get(t.get("status", ""), 0), t.get("task_id", "")), reverse=True
        )
        return sorted_tasks[0], None

    def list_novels(self) -> list[dict]:
        """列出所有小说及其信息

        返回小说信息，包含 title、author、upload_time、file_size
        （来自数据库最新运行记录和文件系统）
        """
        novel_ids = [n.get("novel_id") for n in self._novels.values() if n.get("novel_id")]
        latest_runs: dict[str, dict] = {}

        if novel_ids:
            try:
                session_factory = get_session_factory()
                with session_factory() as session:
                    run_repo = RunRepository(session)
                    for nid in novel_ids:
                        if not isinstance(nid, str):
                            continue
                        run = run_repo.get_latest_run(nid)
                        if run:
                            latest_runs[nid] = run
            except Exception as e:
                logger.warning(f"Failed to get latest runs from db: {e}")

        novels = []
        for novel in self._novels.values():
            novel_id = novel.get("novel_id")
            if not novel_id:
                continue
            latest_run = latest_runs.get(novel_id)
            result = {**novel}
            if latest_run:
                result["title"] = latest_run.get("title") or novel.get("filename", "").replace(".txt", "")
                result["author"] = latest_run.get("author") or "未知作者"
                result["upload_time"] = latest_run.get("created_at")
            else:
                result["title"] = novel.get("filename", "").replace(".txt", "")
                result["author"] = "未知作者"
                result["upload_time"] = None
            file_path = novel.get("file_path")
            if file_path and os.path.exists(file_path):
                result["file_size"] = os.path.getsize(file_path)
            else:
                result["file_size"] = 0
            novels.append(result)
        return novels

    def get_analysis_count(self) -> int:
        """
        从数据库查询不同小说的数量

        创建时间: 2026-04-03
        创建者: TraeAI
        任务: 修改端点行为，从数据库查
        说明: 返回 analysis_runs 表中不同 novel_id 的数量
        """
        try:
            session_factory = get_session_factory()
            with session_factory() as session:
                from src.storage.repositories import RunRepository
                run_repo = RunRepository(session)
                return run_repo.count_distinct_novels()
        except Exception as e:
            logger.warning(f"Failed to get novel count from database: {e}")
            return 0

    def delete_novel(self, novel_id: str) -> bool:
        """删除小说及其相关数据"""
        if novel_id not in self._novels:
            raise NovelNotFoundError(f"小说不存在: {novel_id}")

        novel = self._novels[novel_id]
        file_path = Path(novel["file_path"])

        if file_path.exists():
            os.remove(file_path)

        tasks_to_delete = [tid for tid, t in self._tasks.items() if t.get("novel_id") == novel_id]
        for tid in tasks_to_delete:
            del self._tasks[tid]

        del self._novels[novel_id]
        logger.info(f"Novel deleted: {novel_id}")
        return True

    def delete_task(self, task_id: str) -> bool:
        """删除任务

        修改时间: 2026-03-19
        修改者: TraeAI
        任务: 修复删除任务不删除数据库数据的问题
        修改内容: 使用正确的 session 获取方式

        修改时间: 2026-03-19
        修改者: TraeAI
        任务: Repository层ID统一优化
        修改内容: 使用get_run_by_run_id_prefix替代get_run_by_task_id

        修改时间: 2026-04-04
        修改者: AI Assistant
        任务: fix-backend-stability
        修改内容: 使用 get_session 上下文管理器替代手动 session 管理

        修改时间: 2026-04-04
        修改者: AI Assistant
        任务: fix-backend-stability
        修改内容: 修复静默失败问题，数据库删除失败时抛出异常，保持数据一致性

        Raises:
            RuntimeError: 数据库删除失败时抛出
        """
        from src.storage.db import get_session

        with get_session() as session:
            run_repo = RunRepository(session)
            run = run_repo.get_run_by_run_id_prefix(task_id)

            if run:
                run_id = run["run_id"]
                run_repo.delete_run(run_id)
                logger.info(f"Run deleted from database: {run_id}")

        if task_id in self._tasks:
            del self._tasks[task_id]
            logger.info(f"Task deleted from memory: {task_id}")

        return True
