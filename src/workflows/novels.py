"""小说文本导入、登记与删除用例（workflows）

说明: api 只负责「文本导入」——把上传内容落成文件与 novels 行、列出/删除小说。
任务与运行的读写、产物清理、取消/删除状态机在 src/workflows（编排层按需向下驱动
work 队列），本模块按需调用，不做转发层。
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import aiofiles
from loguru import logger
from sqlalchemy.orm import Session

from src.storage.db import get_session
from src.storage.models import Novel
from src.workflows import dependencies as workflows_deps
from src.workflows.application import TaskApplicationService
from src.workflows.exceptions import FileStorageError, InvalidFileError, NovelNotFoundError
from src.workflows.tasks import TaskService


class NovelService:
    """小说导入与登记：上传落盘 + novels 行读写 + 小说级删除"""

    def __init__(
        self,
        upload_dir: Path,
        task_service: TaskService | None = None,
        task_application_service: TaskApplicationService | None = None,
    ) -> None:
        self.upload_dir = upload_dir
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.task_service = task_service or workflows_deps.get_task_service()
        self.task_application_service = task_application_service or workflows_deps.get_task_application_service()

    @contextmanager
    def _get_session(self, session: Session | None = None) -> Generator[Session, None, None]:
        if session is not None:
            yield session
        else:
            with get_session() as s:
                yield s

    async def save_upload(self, file_content: bytes, filename: str, session: Session | None = None) -> str:
        """保存上传的文件并写入 novels 表"""
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
            sess.add(
                Novel(
                    novel_id=novel_id,
                    filename=filename,
                    title=filename.removesuffix(".txt"),
                    file_path=str(file_path),
                    file_size=len(file_content),
                    upload_time=datetime.now(),
                )
            )

        logger.info(f"Novel uploaded: {novel_id} - {filename}")
        return novel_id

    def get_novel(self, novel_id: str, session: Session | None = None) -> dict:
        return self.task_service.get_novel(novel_id, session)

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
                    select(AnalysisRun.novel_id, func.max(AnalysisRun.created_at).label("latest_created_at"))
                    .group_by(AnalysisRun.novel_id)
                    .subquery()
                )

                LatestRun = aliased(AnalysisRun)
                stmt = (
                    select(Novel, LatestRun.status)
                    .outerjoin(latest_run_subq, Novel.novel_id == latest_run_subq.c.novel_id)
                    .outerjoin(
                        LatestRun,
                        (LatestRun.novel_id == latest_run_subq.c.novel_id)
                        & (LatestRun.created_at == latest_run_subq.c.latest_created_at),
                    )
                    .order_by(Novel.upload_time.desc())
                )

                for novel, latest_status in sess.execute(stmt).all():
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

    def delete_novel(self, novel_id: str, session: Session | None = None) -> bool:
        """级联删除小说及其全部任务数据（任务侧交给编排层的应用服务）"""
        novel = self.task_service.get_novel(novel_id, session)
        deleted_task_count = self.task_application_service.delete_tasks_for_novel(novel_id)
        self.task_service.delete_novel_source_file(novel["file_path"])

        with self._get_session(session) as sess:
            refreshed_novel = sess.get(Novel, novel_id)
            if not refreshed_novel:
                raise NovelNotFoundError(f"小说不存在: {novel_id}")
            sess.delete(refreshed_novel)
            logger.info(
                f"Novel deleted with cascaded task cleanup: {novel_id}, deleted_task_count={deleted_task_count}"
            )
            return True
