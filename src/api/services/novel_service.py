"""
小说服务类

修改历史:

说明: 管理小说文件上传、任务创建和状态查询，使用 PostgreSQL 数据库存储小说元数据和分析任务
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles
from loguru import logger
from sqlalchemy.orm import Session

from src.api.exceptions import FileStorageError, InvalidFileError, NovelNotFoundError
from src.api.services.artifact_gc_service import ArtifactGcService
from src.storage.db import get_session
from src.storage.id_mapping import generate_task_id, run_id_to_task_id
from src.storage.models import Novel
from src.storage.repositories import RunRepository

if TYPE_CHECKING:
    from src.api.services.task_manager import TaskManager


TASK_DELETE_BLOCKING_STATUSES = ("pending", "running", "cancelling")


class NovelService:
    """小说服务类 - 管理小说文件上传、任务创建和状态查询"""

    def __init__(self, upload_dir: Path):
        self.upload_dir = upload_dir
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir = Path("logs")
        self.outputs_dir = Path("outputs")
        self._artifact_gc_service = ArtifactGcService(self.logs_dir, self.outputs_dir)

    @contextmanager
    def _get_session(self, session: Session | None = None) -> Generator[Session, None, None]:
        """获取数据库会话，支持外部传入或内部创建"""
        if session is not None:
            yield session
        else:
            with get_session() as s:
                yield s

    async def save_upload(self, file_content: bytes, filename: str, session: Session | None = None) -> str:
        """
        保存上传的文件并写入 novels 表
        """
        if not filename.endswith(".txt"):
            raise InvalidFileError("只支持 .txt 文件")

        novel_id = str(uuid.uuid4())[:8]

        file_path = self.upload_dir / f"{novel_id}_{filename}"
        try:
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(file_content)
        except Exception as e:
            raise FileStorageError(f"文件保存失败: {e}") from e

        with self._get_session(session) as sess:
            novel = Novel(
                novel_id=novel_id,
                filename=filename,
                file_path=str(file_path),
                file_size=len(file_content),
                upload_time=datetime.now(),
            )
            sess.add(novel)

        logger.info(f"Novel uploaded: {novel_id} - {filename}")
        return novel_id

    def get_novel(self, novel_id: str, session: Session | None = None) -> dict:
        """
        获取小说信息
        """
        with self._get_session(session) as sess:
            novel = sess.get(Novel, novel_id)
            if not novel:
                raise NovelNotFoundError(f"小说不存在: {novel_id}")
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

    def get_run_by_task_id(self, task_id: str, session: Session | None = None) -> dict | None:
        """获取任务对应的运行记录"""
        with self._get_session(session) as sess:
            run_repo = RunRepository(sess)
            run = run_repo.get_run_by_run_id_prefix(task_id)
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
        session: Session | None = None,
        task_kind: str = "analysis",
        request_payload: dict | None = None,
    ) -> str:
        """
        创建分析任务
        """
        self.get_novel(novel_id, session)
        if task_id is None:
            task_id = generate_task_id()

        try:
            with self._get_session(session) as sess:
                run_repo = RunRepository(sess)
                run_repo.create_run(
                    novel_id=novel_id,
                    run_id=task_id,
                    task_kind=task_kind,
                    request_payload=request_payload,
                )
        except Exception as e:
            logger.error(f"Failed to create run in DB for novel {novel_id}, task {task_id}: {e}")
            raise

        logger.info(f"Created task: {task_id} for novel {novel_id}")
        return task_id

    def get_task(self, task_id: str, session: Session | None = None) -> dict:
        """
        获取任务信息
        """
        task = self._load_task_from_db(task_id, session)
        if task:
            return task
        raise NovelNotFoundError(f"任务不存在: {task_id}")

    def _load_task_from_db(self, task_id: str, session: Session | None = None) -> dict | None:
        """
        从数据库加载任务元数据
        """
        with self._get_session(session) as sess:
            run_repo = RunRepository(sess)
            run = run_repo.get_run_by_run_id_prefix(task_id)
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

    def update_task_status(self, task_id: str, status: str) -> None:
        """更新任务状态（仅内存操作，持久化由调用方处理）"""
        pass

    def get_tasks_by_novel(self, novel_id: str, session: Session | None = None) -> list[dict]:
        """
        获取小说的所有任务
        """
        with self._get_session(session) as sess:
            run_repo = RunRepository(sess)
            runs = run_repo.get_runs_by_novel(novel_id)
            return [
                {
                    "task_id": run["run_id"][:8] if len(run["run_id"]) >= 8 else run["run_id"],
                    "novel_id": run["novel_id"],
                    "status": run["status"],
                    "run_id": run["run_id"],
                    "created_at": run["created_at"],
                }
                for run in runs
            ]

    def get_task_counts_by_status(self, novel_id: str, session: Session | None = None) -> dict[str, int]:
        """获取各状态的任务数量"""
        tasks = self.get_tasks_by_novel(novel_id, session)
        counts: dict[str, int] = {"completed": 0, "running": 0, "pending": 0, "failed": 0}
        for task in tasks:
            status = task.get("status", "unknown")
            if status in counts:
                counts[status] += 1
        return counts

    def get_single_valid_task(self, novel_id: str, session: Session | None = None) -> tuple[dict | None, str | None]:
        """获取唯一的合法任务"""
        tasks = self.get_tasks_by_novel(novel_id, session)
        if not tasks:
            return None, None

        if len(tasks) == 1:
            return tasks[0], None

        return None, f"存在{len(tasks)}个任务，请指定task_id"

    def list_novels(self, session: Session | None = None) -> list[dict]:
        """
        列出所有小说及其信息

        2026-08-20 阶段 3.2：使用 LEFT JOIN 和窗口函数消除 N+1 查询
        """
        novels = []
        try:
            with self._get_session(session) as sess:
                from sqlalchemy import func, select
                from sqlalchemy.orm import aliased

                from src.storage.models import AnalysisRun

                # 子查询：为每个小说找到最新任务的 created_at
                latest_run_subq = (
                    select(
                        AnalysisRun.novel_id,
                        func.max(AnalysisRun.created_at).label("latest_created_at")
                    )
                    .group_by(AnalysisRun.novel_id)
                    .subquery()
                )

                # 主查询：JOIN 获取小说和最新任务状态
                LatestRun = aliased(AnalysisRun)
                stmt = (
                    select(Novel, LatestRun.status)
                    .outerjoin(
                        latest_run_subq,
                        Novel.novel_id == latest_run_subq.c.novel_id
                    )
                    .outerjoin(
                        LatestRun,
                        (LatestRun.novel_id == latest_run_subq.c.novel_id)
                        & (LatestRun.created_at == latest_run_subq.c.latest_created_at)
                    )
                    .order_by(Novel.upload_time.desc())
                )

                result = sess.execute(stmt).all()

                for novel, latest_status in result:
                    novels.append(
                        {
                            "novel_id": novel.novel_id,
                            "filename": novel.filename or "unknown.txt",
                            "file_path": novel.file_path or "",
                            "status": latest_status or "uploaded",
                            "title": novel.title or novel.filename or "未知标题",
                            "author": novel.author or "未知作者",
                            "upload_time": novel.upload_time.isoformat() if novel.upload_time else None,
                            "file_size": novel.file_size or 0,
                        }
                    )
        except Exception as e:
            logger.warning(f"Failed to list novels from database: {e}")
        return novels

    def get_analysis_count(self, session: Session | None = None) -> int:
        """
        从 novels 表查询小说数量
        """
        try:
            with self._get_session(session) as sess:
                from sqlalchemy import func, select

                result = sess.execute(select(func.count()).select_from(Novel))
                return result.scalar() or 0
        except Exception as e:
            logger.warning(f"Failed to get novel count from database: {e}")
            return 0

    def _delete_novel_source_file(self, file_path: str | None) -> None:
        """
        删除小说源文件

        说明: 仅在文件真实存在时删除，缺失文件不报错；
              若遇到真实 IO 异常则继续上抛，避免把磁盘问题静默吞掉
        """
        self._artifact_gc_service.delete_novel_source_file(file_path)

    def _delete_task_artifacts(self, task_id: str, run_id: str) -> None:
        """
        删除任务对应的日志与导出文件

        说明: 输出文件按 task_id 命名，日志目录按 run_id 命名；
              为兼容历史短 run_id 目录，run_id != task_id 时会额外检查短目录
        """
        self._artifact_gc_service.delete_task_artifacts(task_id, run_id)

    def _collect_novel_delete_context(
        self,
        novel_id: str,
        session: Session | None = None,
    ) -> tuple[Novel, list[dict]]:
        """
        收集删除小说前需要的上下文

        说明: 先一次性读出小说记录与其全部任务，后续删除阶段不再靠猜测接口状态
        """
        with self._get_session(session) as sess:
            novel = sess.get(Novel, novel_id)
            if not novel:
                raise NovelNotFoundError(f"小说不存在: {novel_id}")

            runs = RunRepository(sess).get_runs_by_novel(novel_id)
            return novel, runs

    def _ensure_novel_tasks_deletable(self, novel_id: str, runs: list[dict]) -> None:
        """
        校验小说下的任务是否都允许删除

        说明: novel 级删除沿用 task 删除状态机，不允许绕过 pending/running/cancelling 护栏
        """
        for run in runs:
            status = str(run.get("status", ""))
            if status in TASK_DELETE_BLOCKING_STATUSES:
                task_id = run_id_to_task_id(str(run["run_id"]))
                raise ValueError(f"小说 {novel_id} 下的任务 {task_id} 正在{status}中，请先取消任务后再删除小说")

    def _delete_run_data(self, run_id: str, session: Session | None = None) -> None:
        """
        删除单个 run 的数据库数据与文件产物

        说明: DB 删除仍复用 RunRepository.delete_run；文件侧统一删除 outputs/task_id.json
              与 logs/run_id 目录，兼容历史 full run_id 日志目录
        """
        task_id = run_id_to_task_id(run_id)

        with self._get_session(session) as sess:
            RunRepository(sess).delete_run(run_id)

        self._delete_task_artifacts(task_id, run_id)
        logger.info(f"Run deleted from database and artifacts cleaned: run_id={run_id}, task_id={task_id}")

    def delete_novel(
        self,
        novel_id: str,
        session: Session | None = None,
        task_manager: TaskManager | None = None,
    ) -> bool:
        """
        级联删除小说及其全部任务数据
        """
        novel, runs = self._collect_novel_delete_context(novel_id, session)
        self._ensure_novel_tasks_deletable(novel_id, runs)

        for run in runs:
            task_id = run_id_to_task_id(str(run["run_id"]))
            self.delete_task(task_id, task_manager=task_manager)

        self._delete_novel_source_file(novel.file_path)

        with self._get_session(session) as sess:
            refreshed_novel = sess.get(Novel, novel_id)
            if not refreshed_novel:
                raise NovelNotFoundError(f"小说不存在: {novel_id}")
            sess.delete(refreshed_novel)
            logger.info(f"Novel deleted with cascaded task cleanup: {novel_id}, deleted_task_count={len(runs)}")
            return True

    def delete_task(
        self,
        task_id: str,
        session: Session | None = None,
        task_manager: TaskManager | None = None,
    ) -> bool:
        """
        删除任务及其数据库/文件产物
        """
        run_id: str | None = None
        with self._get_session(session) as sess:
            run_repo = RunRepository(sess)
            run = run_repo.get_run_by_run_id_prefix(task_id)
            if run:
                run_id = str(run["run_id"])

        if task_manager is not None:
            # TaskManager 只负责当前进程的执行缓存，删除 task 时顺手清掉缓存，
            # 避免 DB 已删除但本进程里还残留已终态任务对象
            task_manager.delete_task(task_id)

        if run_id is not None:
            self._delete_run_data(run_id, session=session)
        else:
            self._delete_task_artifacts(task_id, task_id)
            logger.info(f"Task artifacts cleaned without DB run record: task_id={task_id}")

        return True
