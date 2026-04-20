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

_UNSET = object()


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
            "progress": run.progress,
            "stage": run.stage,
            "sub_stage": run.sub_stage,
            "current": run.current,
            "total": run.total,
            "message": run.message,
            "error": run.error,
            "cancel_requested": run.cancel_requested,
            "worker_id": run.worker_id,
            "heartbeat_at": run.heartbeat_at.isoformat() if run.heartbeat_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
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

    def cancel_run(self, run_id: str) -> bool:
        """
        原子性地设置任务的取消请求标记。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-system-db-driven-refactor
        说明: DB 驱动的取消机制，通过 cancel_requested flag 传递取消信号

        Args:
            run_id: 运行ID

        Returns:
            是否成功设置取消标记
        """
        from sqlalchemy import update

        stmt = (
            update(AnalysisRun)
            .where(AnalysisRun.run_id == run_id)
            .where(AnalysisRun.cancel_requested == False)  # noqa: E712
            .values(cancel_requested=True, updated_at=datetime.now())
        )
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    def get_by_status(self, status: str) -> list[dict[str, Any]]:
        """
        按状态查询任务。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-system-db-driven-refactor
        说明: 用于查询指定状态的所有任务

        Args:
            status: 任务状态

        Returns:
            符合状态的任务记录列表
        """
        stmt = select(AnalysisRun).where(AnalysisRun.status == status).order_by(AnalysisRun.created_at.desc())
        runs = self.session.execute(stmt).scalars().all()
        return [self._to_dict(run) for run in runs]

    def get_running_tasks(self) -> list[dict[str, Any]]:
        """
        获取所有运行中的任务。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-system-db-driven-refactor
        说明: 用于启动时清理孤儿任务和运行时状态检查

        Returns:
            所有 status=running 的任务记录列表
        """
        return self.get_by_status("running")

    def get_pending_tasks(self) -> list[dict[str, Any]]:
        """
        获取所有 pending 任务。

        创建时间: 2026-04-20
        创建者: Codex (GPT-5)
        任务: fix-pending-task-pickup
        修改内容: 为启动恢复和 DB worker pickup 提供统一的 pending 查询入口。
        """
        return self.get_by_status("pending")

    def claim_pending_run(self, run_id: str, *, worker_id: str, heartbeat_at: datetime | None = None) -> bool:
        """
        原子性领取一个尚未执行的 pending 任务。

        创建时间: 2026-04-20
        创建者: Codex (GPT-5)
        任务: fix-pending-task-pickup
        修改内容: 通过单条 UPDATE 将 pending->running，避免多个实例同时把同一任务拉起执行。
        """
        from sqlalchemy import update

        now = heartbeat_at or datetime.now()
        stmt = (
            update(AnalysisRun)
            .where(AnalysisRun.run_id == run_id)
            .where(AnalysisRun.status == "pending")
            .where(AnalysisRun.cancel_requested == False)  # noqa: E712
            .values(
                status="running",
                worker_id=worker_id,
                heartbeat_at=now,
                updated_at=now,
            )
        )
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    def cancel_unclaimed_pending_run(self, run_id: str, *, message: str) -> bool:
        """
        原子性终结尚未被任何 worker 领取的 pending 任务。

        创建时间: 2026-04-20
        创建者: Codex (GPT-5)
        任务: fix-pending-task-pickup
        修改内容: 允许进程外取消在任务真正启动前直接落终态，避免进入不可恢复的 cancelling 死状态。
        """
        from sqlalchemy import update

        now = datetime.now()
        stmt = (
            update(AnalysisRun)
            .where(AnalysisRun.run_id == run_id)
            .where(AnalysisRun.status == "pending")
            .values(
                status="cancelled",
                cancel_requested=False,
                completed_at=now,
                message=message,
                worker_id=None,
                heartbeat_at=None,
                updated_at=now,
            )
        )
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    def update_run_task_fields(
        self,
        run_id: str,
        *,
        status: str | None | object = _UNSET,
        progress: float | None | object = _UNSET,
        stage: str | None | object = _UNSET,
        sub_stage: str | None | object = _UNSET,
        current: int | None | object = _UNSET,
        total: int | None | object = _UNSET,
        message: str | None | object = _UNSET,
        error: str | None | object = _UNSET,
        cancel_requested: bool | None | object = _UNSET,
        worker_id: str | None | object = _UNSET,
        heartbeat_at: datetime | None | object = _UNSET,
        completed_at: datetime | None | object = _UNSET,
    ) -> None:
        """
        批量更新任务的运行态字段。

        创建时间: 2026-04-19
        创建者: TraeAI
        任务: task-system-db-driven-refactor
        说明: 统一的运行态字段更新方法，支持选择性更新

        Args:
            run_id: 运行ID
            status: 任务状态
            progress: 进度 (0-100)
            stage: 阶段名称
            sub_stage: 子阶段名称
            current: 当前进度分子
            total: 总量
            message: 提示信息
            error: 错误信息
            cancel_requested: 是否请求取消
            worker_id: 当前执行该任务的 worker 标识
            heartbeat_at: 最近一次心跳时间
            completed_at: 完成时间
        """
        stmt = select(AnalysisRun).where(AnalysisRun.run_id == run_id)
        run = self.session.execute(stmt).scalar_one_or_none()
        if not run:
            return

        now = datetime.now()
        if status is not _UNSET:
            run.status = status
        if progress is not _UNSET:
            run.progress = progress
        if stage is not _UNSET:
            run.stage = stage
        if sub_stage is not _UNSET:
            run.sub_stage = sub_stage
        if current is not _UNSET:
            run.current = current
        if total is not _UNSET:
            run.total = total
        if message is not _UNSET:
            run.message = message
        if error is not _UNSET:
            run.error = error
        if cancel_requested is not _UNSET:
            run.cancel_requested = cancel_requested
        if worker_id is not _UNSET:
            run.worker_id = worker_id
        if heartbeat_at is not _UNSET:
            run.heartbeat_at = heartbeat_at
        if completed_at is not _UNSET:
            run.completed_at = completed_at
        run.updated_at = now
        self.session.commit()

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

    def mark_running_as_failed(self, *, stale_before: datetime) -> int:
        """
        将明确可判定为孤儿的 running 任务标记为 failed。

        修改时间: 2026-04-19
        修改者: Codex (GPT-5)
        任务: fix-task-system-review-findings
        修改内容: 仅回收带有 worker 归属且心跳超时的任务，避免新进程误收口其他活跃实例上的真实运行任务。

        Returns:
            受影响的行数
        """
        from sqlalchemy import update

        now = datetime.now()
        stmt = (
            update(AnalysisRun)
            .where(AnalysisRun.status == "running")
            .where(AnalysisRun.worker_id.is_not(None))
            .where(AnalysisRun.heartbeat_at.is_not(None))
            .where(AnalysisRun.heartbeat_at < stale_before)
            .values(status="failed", updated_at=now)
        )
        result = self.session.execute(stmt)
        self.session.commit()
        count = result.rowcount  # type: ignore[attr-defined]
        if count > 0:
            logger.info(f"Marked {count} orphaned running task(s) as failed on startup")
        return count

    def mark_cancelling_as_cancelled(self, *, stale_before: datetime) -> int:
        """
        将明确可判定为孤儿的 cancelling 任务收口为 cancelled。

        创建时间: 2026-04-19
        创建者: Codex (GPT-5)
        任务: fix-task-system-review-findings
        修改内容: 仅回收带有 worker 归属且心跳超时的任务，避免误终结仍在其他实例中收尾的任务。

        Returns:
            受影响的行数
        """
        from sqlalchemy import update

        now = datetime.now()
        stmt = (
            update(AnalysisRun)
            .where(AnalysisRun.status == "cancelling")
            .where(
                AnalysisRun.worker_id.is_(None)
                | AnalysisRun.heartbeat_at.is_(None)
                | (AnalysisRun.heartbeat_at < stale_before)
            )
            .values(
                status="cancelled",
                cancel_requested=False,
                completed_at=now,
                updated_at=now,
            )
        )
        result = self.session.execute(stmt)
        self.session.commit()
        count = result.rowcount  # type: ignore[attr-defined]
        if count > 0:
            logger.info(f"Marked {count} orphaned cancelling task(s) as cancelled on startup")
        return count

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
