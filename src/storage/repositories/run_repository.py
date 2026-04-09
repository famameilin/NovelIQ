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
from typing import Any

from loguru import logger
from sqlalchemy import select

from src.storage.models import AnalysisRun

from .base import BaseRepository


class RunRepository(BaseRepository[dict[str, Any]]):
    """
    分析运行记录 Repository

    管理分析运行的创建、查询和状态更新。
    使用 AnalysisRun ORM 模型。

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session
    """

    def _to_dict(self, run: AnalysisRun) -> dict[str, Any]:
        """将 ORM 对象转换为字典"""
        return {
            "run_id": run.run_id,
            "novel_id": run.novel_id,
            "source_path": run.source_path,
            "title": run.title,
            "author": run.author,
            "status": run.status,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        }

    def create_run(
        self,
        novel_id: str,
        source_path: str | None = None,
        title: str | None = None,
        author: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """
        创建新的分析运行记录

        Args:
            novel_id: 小说ID
            source_path: 源文件路径
            title: 小说标题
            author: 小说作者
            run_id: 可选的运行ID，如果不提供则自动生成

        Returns:
            运行ID
        """
        if run_id is None:
            run_id = str(uuid.uuid4())
        now = datetime.now()

        run = AnalysisRun(
            run_id=run_id,
            novel_id=novel_id,
            source_path=source_path,
            title=title,
            author=author,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        self.session.add(run)
        self.session.commit()
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
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

    def update_run_progress(self, run_id: str, progress: float) -> None:
        """
        更新运行进度

        创建时间: 2026-04-08
        创建者: TraeAI
        任务: 修复数据库更新方法缺少关键字段同步问题
        说明: 同步 progress 字段到数据库

        Args:
            run_id: 运行ID
            progress: 进度值 (0-100)
        """
        now = datetime.now()
        stmt = select(AnalysisRun).where(AnalysisRun.run_id == run_id)
        run = self.session.execute(stmt).scalar_one_or_none()
        if run:
            run.progress = progress
            run.updated_at = now
            self.session.commit()

    def update_run_stage(self, run_id: str, stage: str) -> None:
        """
        更新运行阶段

        创建时间: 2026-04-08
        创建者: TraeAI
        任务: 修复数据库更新方法缺少关键字段同步问题
        说明: 同步 stage 字段到数据库

        Args:
            run_id: 运行ID
            stage: 阶段名称
        """
        now = datetime.now()
        stmt = select(AnalysisRun).where(AnalysisRun.run_id == run_id)
        run = self.session.execute(stmt).scalar_one_or_none()
        if run:
            run.stage = stage
            run.updated_at = now
            self.session.commit()

    def get_runs_by_novel(self, novel_id: str) -> list[dict[str, Any]]:
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

    def get_run_by_run_id_prefix(self, run_id_prefix: str) -> dict[str, Any] | None:
        """
        通过run_id前缀获取运行记录

        创建时间: 2026-03-19
        创建者: TraeAI
        任务: Repository层ID统一优化
        说明: 使用run_id前缀匹配查询运行记录

        Args:
            run_id_prefix: run_id前缀（如前8位）

        Returns:
            运行记录字典，不存在则返回 None

        修改时间: 2026-03-25
        修改者: TraeAI
        任务: fix-resume-feature - 断点续传功能修复
        修改内容: 使用 limit(1) 避免多记录时抛出异常
        """
        stmt = (
            select(AnalysisRun)
            .where(AnalysisRun.run_id.like(f"{run_id_prefix}%"))
            .order_by(AnalysisRun.created_at.asc())
            .limit(1)
        )
        run = self.session.execute(stmt).scalar_one_or_none()
        if run is None:
            return None
        return self._to_dict(run)

    def get_latest_run(self, novel_id: str) -> dict[str, Any] | None:
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

    def delete_run(self, run_id: str) -> bool:
        """
        删除运行记录及相关数据

        创建时间: 2026-03-18
        创建者: TraeAI
        任务: 修复删除任务不删除数据库数据的问题

        修改时间: 2026-04-08
        修改者: TraeAI
        任务: fix-delete-task-failure
        修改内容: 修正表名列表以匹配实际数据库架构
        """
        from sqlalchemy import text

        tables = [
            "stage_summaries",
            "token_usage",
            "model_interactions",
            "chunk_summaries",
            "chunk_curves",
            "global_stats",
            "global_context",
            "chunk_annotation",
            "chunk_characters",
            "chunk_dialogues",
            "chunk_foreshadowing",
            "chunk_locations",
            "chunk_relations",
            "chunk_style",
            "chunk_topics",
            "chunks",
            "character_appearances",
            "graph_entity_aliases",
            "graph_relation_events",
            "graph_relations_current",
            "graph_entities",
            "disambig_checkpoint",
            "cloud_analysis",
            "analysis_runs",
        ]

        for table in tables:
            try:
                self.session.execute(text(f"DELETE FROM {table} WHERE run_id = :run_id"), {"run_id": run_id})
            except Exception as e:
                if "relation" in str(e).lower() or "column" in str(e).lower():
                    pass
                else:
                    logger.warning(f"Failed to delete from {table}: {e}")

        self.session.commit()
        return True

    def count_distinct_novels(self) -> int:
        """
        统计不同小说的数量

        创建时间: 2026-04-03
        创建者: TraeAI
        任务: 修改端点行为，从数据库查
        说明: 返回 analysis_runs 表中 distinct novel_id 的数量
        """
        from sqlalchemy import func, select

        stmt = select(func.count(func.distinct(AnalysisRun.novel_id))).select_from(AnalysisRun)
        result = self.session.execute(stmt)
        return result.scalar() or 0

    def list_novels_with_latest_run(self) -> list[dict[str, Any]]:
        """
        获取所有有分析记录的小说列表

        创建时间: 2026-04-05
        创建者: AI Assistant
        任务: fix-test-data-pollution
        说明: 返回每个 novel_id 的最新运行记录，用于小说列表展示

        Returns:
            小说列表，每个元素包含 novel_id、title、author、status、created_at 等
        """
        from sqlalchemy import func, select

        subquery = (
            select(
                AnalysisRun.novel_id,
                func.max(AnalysisRun.created_at).label("latest_created_at"),
            )
            .group_by(AnalysisRun.novel_id)
            .subquery()
        )

        stmt = (
            select(AnalysisRun)
            .join(subquery, AnalysisRun.novel_id == subquery.c.novel_id)
            .where(AnalysisRun.created_at == subquery.c.latest_created_at)
            .order_by(AnalysisRun.created_at.desc())
        )

        runs = self.session.execute(stmt).scalars().all()
        return [self._to_dict(run) for run in runs]
