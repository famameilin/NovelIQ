"""
创建时间: 2026-03-14
创建者: TraeAI
任务: 实现 RunRepository 类
说明: 分析运行记录的数据库操作实现

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from src.storage.models import AnalysisRun
from .base import BaseRepository


class RunRepository(BaseRepository[Dict[str, Any]]):
    """
    分析运行记录 Repository

    管理分析运行的创建、查询和状态更新。
    使用 AnalysisRun ORM 模型。

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session
    """

    def _to_dict(self, run: AnalysisRun) -> Dict[str, Any]:
        """将 ORM 对象转换为字典"""
        return {
            "run_id": run.run_id,
            "novel_id": run.novel_id,
            "source_path": run.source_path,
            "title": run.title,
            "status": run.status,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        }

    def create_run(
        self,
        novel_id: str,
        source_path: str | None = None,
        title: str | None = None,
    ) -> str:
        """
        创建新的分析运行记录

        Args:
            novel_id: 小说ID
            source_path: 源文件路径
            title: 小说标题

        Returns:
            运行ID
        """
        run_id = str(uuid.uuid4())
        now = datetime.now()

        run = AnalysisRun(
            run_id=run_id,
            novel_id=novel_id,
            source_path=source_path,
            title=title,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        self.session.add(run)
        self.session.commit()
        return run_id

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        获取运行记录

        Args:
            run_id: 运行ID

        Returns:
            运行记录字典，不存在则返回 None
        """
        stmt = select(AnalysisRun).where(AnalysisRun.run_id == run_id)
        run = self.session.execute(stmt).scalar_one_or_none()
        if run is None:
            return None
        return self._to_dict(run)

    def update_run_status(self, run_id: str, status: str) -> None:
        """
        更新运行状态

        Args:
            run_id: 运行ID
            status: 新状态
        """
        now = datetime.now()
        stmt = select(AnalysisRun).where(AnalysisRun.run_id == run_id)
        run = self.session.execute(stmt).scalar_one_or_none()
        if run:
            run.status = status
            run.updated_at = now
            self.session.commit()

    def get_runs_by_novel(self, novel_id: str) -> List[Dict[str, Any]]:
        """
        获取指定小说的所有运行记录

        Args:
            novel_id: 小说ID

        Returns:
            运行记录列表，按创建时间倒序排列
        """
        stmt = select(AnalysisRun).where(AnalysisRun.novel_id == novel_id).order_by(AnalysisRun.created_at.desc())
        runs = self.session.execute(stmt).scalars().all()
        return [self._to_dict(run) for run in runs]

    def get_run_by_task_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        通过task_id获取运行记录

        创建时间: 2026-03-17
        创建者: TraeAI
        任务: 修复服务重启后任务丢失问题
        说明: task_id是run_id的前8位，用于API查询

        Args:
            task_id: 任务ID（run_id的前8位）

        Returns:
            运行记录字典，不存在则返回 None
        """
        # 使用LIKE匹配run_id的前8位
        stmt = select(AnalysisRun).where(AnalysisRun.run_id.like(f"{task_id}%"))
        run = self.session.execute(stmt).scalar_one_or_none()
        if run is None:
            return None
        return self._to_dict(run)

    def get_latest_run(self, novel_id: str) -> Optional[Dict[str, Any]]:
        """
        获取指定小说的最新运行记录

        Args:
            novel_id: 小说ID

        Returns:
            最新运行记录字典，不存在则返回 None
        """
        stmt = (
            select(AnalysisRun).where(AnalysisRun.novel_id == novel_id).order_by(AnalysisRun.created_at.desc()).limit(1)
        )
        run = self.session.execute(stmt).scalar_one_or_none()
        if run is None:
            return None
        return self._to_dict(run)
