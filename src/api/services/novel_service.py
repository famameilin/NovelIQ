"""
小说服务类

创建时间: 2025-03-11
创建者: TraeAI
任务: 小说服务

修改历史:
- 2026-03-14: 使用 Repository 模式重构，移除 .db 路径相关逻辑
- 2026-03-15: PostgreSQL 迁移，完全移除 .db 文件扫描逻辑
- 2026-04-08: 新增 novels 表，上传后立即可查
- 2026-04-08: 添加可选 session 参数支持依赖注入

说明: 管理小说文件上传、任务创建和状态查询，使用 PostgreSQL 数据库存储小说元数据和分析任务。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import aiofiles
from loguru import logger
from sqlalchemy.orm import Session

from src.api.exceptions import FileStorageError, InvalidFileError, NovelNotFoundError
from src.storage.db import get_session
from src.storage.id_mapping import generate_task_id
from src.storage.models import Novel
from src.storage.repositories import RunRepository


class NovelService:
    """小说服务类 - 管理小说文件上传、任务创建和状态查询"""

    def __init__(self, upload_dir: Path):
        self.upload_dir = upload_dir
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def _scan_existing_novels(self) -> None:
        """从数据库加载小说列表（保留用于初始化）"""
        pass

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

        修改时间: 2026-04-19
        修改者: Codex (GPT-5)
        任务: fix-task-system-review-findings
        修改内容: DB 创建失败时不再吞异常，避免接口返回成功但无持久化真相
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

        修改时间: 2026-04-19
        修改者: Codex (GPT-5)
        任务: fix-task-system-review-findings
        修改内容: 移除 DB 异常吞掉逻辑，基础设施故障应由上层按 5xx 处理，而不是伪装成任务不存在。
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

        修改时间: 2026-04-19
        修改者: Codex (GPT-5)
        任务: fix-task-system-review-findings
        修改内容: 不再将 DB 查询失败伪装成空列表，并补齐 created_at 供任务面板显示真实时间。
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

    def get_latest_completed_task(self, novel_id: str, session: Session | None = None) -> dict | None:
        """获取小说的最新已完成任务"""
        tasks = self.get_tasks_by_novel(novel_id, session)
        completed_tasks = [t for t in tasks if t.get("status") == "completed"]
        if not completed_tasks:
            return None
        return completed_tasks[-1]

    def get_latest_task(self, novel_id: str, session: Session | None = None) -> dict | None:
        """获取小说的最新任务"""
        tasks = self.get_tasks_by_novel(novel_id, session)
        if not tasks:
            return None

        priority_order = {"completed": 4, "running": 3, "pending": 2, "failed": 1}
        sorted_tasks = sorted(
            tasks, key=lambda t: (priority_order.get(t.get("status", ""), 0), t.get("task_id", "")), reverse=True
        )
        return sorted_tasks[0] if sorted_tasks else None

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
        """
        novels = []
        try:
            with self._get_session(session) as sess:
                from sqlalchemy import select

                from src.storage.models import AnalysisRun

                result = sess.execute(select(Novel).order_by(Novel.upload_time.desc()))
                all_novels = result.scalars().all()

                for novel in all_novels:
                    runs = (
                        sess.execute(
                            select(AnalysisRun)
                            .where(AnalysisRun.novel_id == novel.novel_id)
                            .order_by(AnalysisRun.created_at.desc())
                        )
                        .scalars()
                        .all()
                    )

                    latest_status = runs[0].status if runs else "uploaded"

                    novels.append(
                        {
                            "novel_id": novel.novel_id,
                            "filename": novel.filename or "unknown.txt",
                            "file_path": novel.file_path or "",
                            "status": latest_status,
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

    def delete_novel(self, novel_id: str, session: Session | None = None) -> bool:
        """
        删除小说及其相关数据
        """
        with self._get_session(session) as sess:
            novel = sess.get(Novel, novel_id)
            if not novel:
                raise NovelNotFoundError(f"小说不存在: {novel_id}")

            file_path = novel.file_path
            if file_path and os.path.exists(file_path):
                os.remove(file_path)

            sess.delete(novel)
            logger.info(f"Novel deleted: {novel_id}")
            return True

    def delete_task(self, task_id: str, session: Session | None = None) -> bool:
        """删除任务"""
        with self._get_session(session) as sess:
            run_repo = RunRepository(sess)
            run = run_repo.get_run_by_run_id_prefix(task_id)

            if run:
                run_id = run["run_id"]
                run_repo.delete_run(run_id)
                logger.info(f"Run deleted from database: {run_id}")

        return True
