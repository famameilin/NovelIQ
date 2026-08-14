"""
分析运行记录的数据库操作实现

从 sqlite3.Connection 迁移到 SQLAlchemy Session
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, TypeGuard, TypeVar

from loguru import logger
from sqlalchemy import delete, inspect, select

from src.storage.models import AnalysisRun, Base

from .base import BaseRepository

_UNSET = object()
T = TypeVar("T")


def _is_set[T](value: T | object) -> TypeGuard[T]:
    """
    判断参数是否不是 `_UNSET` 哨兵值

    统一收窄 `T | object` 到真实字段类型，避免 mypy 把 `_UNSET` 联合类型传进 ORM 字段赋值
    """
    return value is not _UNSET


class RunRepository(BaseRepository[dict[str, Any]]):
    """运行记录数据访问层

    管理分析运行的创建、查询和状态更新
    使用 AnalysisRun ORM 模型
    从 sqlite3.Connection 迁移到 SQLAlchemy Session
    """

    def _serialize_request_payload(self, request_payload: dict[str, Any] | None) -> str | None:
        """
        序列化任务请求载荷

        将重分析请求参数持久化到 analysis_runs.request_payload，供 resume/recovery 恢复原始语义
        """
        if request_payload is None:
            return None
        return json.dumps(request_payload, ensure_ascii=False, sort_keys=True)

    def _deserialize_request_payload(self, request_payload: str | None) -> dict[str, Any] | None:
        """
        反序列化任务请求载荷

        读取 analysis_runs.request_payload 时恢复为语义化字典，避免上层直接处理 JSON 字符串

        增加 JSON 解析异常保护，脏数据时返回 None 并记录警告日志
        """
        if not request_payload:
            return None
        try:
            return json.loads(request_payload)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to deserialize request_payload: {e}")
            return None

    def _to_dict(self, run: AnalysisRun) -> dict[str, Any]:
        """将 ORM 对象转换为字典"""
        return {
            "run_id": run.run_id,
            "novel_id": run.novel_id,
            "analysis_contract_version": run.analysis_contract_version,
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
            "task_kind": run.task_kind,
            "request_payload": self._deserialize_request_payload(run.request_payload),
            "cancel_requested": run.cancel_requested,
            "worker_id": run.worker_id,
            "heartbeat_at": run.heartbeat_at.isoformat() if run.heartbeat_at else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
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
        task_kind: str = "analysis",
        request_payload: dict[str, Any] | None = None,
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
        now = datetime.now(UTC)

        run = AnalysisRun(
            run_id=run_id,
            novel_id=novel_id,
            source_path=source_path,
            title=title,
            author=author,
            status="pending",
            task_kind=task_kind,
            # §16 分析合同版本：新 run 默认 paragraph-v1，旧 run 为 NULL（段落级接口 409）
            analysis_contract_version="paragraph-v1",
            request_payload=self._serialize_request_payload(request_payload),
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
        now = datetime.now(UTC)
        stmt = select(AnalysisRun).where(AnalysisRun.run_id == run_id)
        run = self.session.execute(stmt).scalar_one_or_none()
        if run:
            run.status = status
            if status in ("completed", "failed", "cancelled"):
                run.completed_at = now
            run.updated_at = now
            self.session.commit()

    def update_run_progress(self, run_id: str, progress: float) -> None:
        """
        更新运行进度

        同步 progress 字段到数据库

        Args:
            run_id: 运行ID
            progress: 进度值 (0-100)
        """
        now = datetime.now(UTC)
        stmt = select(AnalysisRun).where(AnalysisRun.run_id == run_id)
        run = self.session.execute(stmt).scalar_one_or_none()
        if run:
            run.progress = progress
            run.updated_at = now
            self.session.commit()

    def update_run_stage(self, run_id: str, stage: str) -> None:
        """
        更新运行阶段

        同步 stage 字段到数据库

        Args:
            run_id: 运行ID
            stage: 阶段名称
        """
        now = datetime.now(UTC)
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
        原子性地设置任务的取消请求标记

        DB 驱动的取消机制，通过 cancel_requested flag 传递取消信号

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
            .values(cancel_requested=True, updated_at=datetime.now(UTC))
        )
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    def request_task_cancellation(self, run_id: str) -> str | None:
        """
        原子性地把可取消任务推进到 cancelling

        仅允许 pending/running -> cancelling，避免取消竞态把已终态任务回写成 cancelling

        Returns:
            最新任务状态；若成功写入则固定返回 "cancelling"，若任务不存在则返回 None
        """
        from sqlalchemy import update

        now = datetime.now(UTC)
        stmt = (
            update(AnalysisRun)
            .where(AnalysisRun.run_id == run_id)
            .where(AnalysisRun.status.in_(("pending", "running")))
            .values(
                status="cancelling",
                cancel_requested=True,
                updated_at=now,
            )
        )
        result = self.session.execute(stmt)
        self.session.commit()
        if result.rowcount > 0:  # type: ignore[attr-defined]
            return "cancelling"

        status_stmt = select(AnalysisRun.status).where(AnalysisRun.run_id == run_id)
        refreshed_status = self.session.execute(status_stmt).scalar_one_or_none()
        return str(refreshed_status) if refreshed_status is not None else None

    def get_by_status(self, status: str) -> list[dict[str, Any]]:
        """
        按状态查询任务

        用于查询指定状态的所有任务

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
        获取所有运行中的任务

        用于启动时清理孤儿任务和运行时状态检查

        Returns:
            所有 status=running 的任务记录列表
        """
        return self.get_by_status("running")

    def get_pending_tasks(self) -> list[dict[str, Any]]:
        """
        获取所有 pending 任务

        为启动恢复和 DB worker pickup 提供统一的 pending 查询入口
        """
        return self.get_by_status("pending")

    def claim_pending_run(self, run_id: str, *, worker_id: str, heartbeat_at: datetime | None = None) -> bool:
        """
        原子性领取一个尚未执行的 pending 任务

        通过单条 UPDATE 将 pending->running，避免多个实例同时把同一任务拉起执行
        """
        from sqlalchemy import update

        # 2026-08-13 P2：heartbeat_at 列无时区，默认值统一落 naive UTC 挂钟
        # （避免 aware UTC 被 PG 按会话时区转换，导致 resume 窗口/孤儿回收误判）
        now = heartbeat_at or datetime.now(UTC).replace(tzinfo=None)
        stmt = (
            update(AnalysisRun)
            .where(AnalysisRun.run_id == run_id)
            .where(AnalysisRun.status == "pending")
            .where(AnalysisRun.cancel_requested == False)  # noqa: E712
            .values(
                status="running",
                worker_id=worker_id,
                heartbeat_at=now,
                started_at=now,
                updated_at=now,
            )
        )
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    def cancel_unclaimed_pending_run(self, run_id: str, *, message: str) -> bool:
        """
        原子性终结尚未被任何 worker 领取的 pending 任务

        允许进程外取消在任务真正启动前直接落终态，避免进入不可恢复的 cancelling 死状态
        """
        from sqlalchemy import update

        now = datetime.now(UTC)
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
        task_kind: str | None | object = _UNSET,
        request_payload: dict[str, Any] | None | object = _UNSET,
        cancel_requested: bool | None | object = _UNSET,
        worker_id: str | None | object = _UNSET,
        heartbeat_at: datetime | None | object = _UNSET,
        started_at: datetime | None | object = _UNSET,
        completed_at: datetime | None | object = _UNSET,
    ) -> None:
        """
        批量更新任务的运行态字段

        统一的运行态字段更新方法，支持选择性更新

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
            started_at: 任务实际开始执行时间
            completed_at: 完成时间
        """
        stmt = select(AnalysisRun).where(AnalysisRun.run_id == run_id)
        run = self.session.execute(stmt).scalar_one_or_none()
        if not run:
            return

        now = datetime.now(UTC)
        if _is_set(status):
            run.status = status
        if _is_set(progress):
            run.progress = progress
        if _is_set(stage):
            run.stage = stage
        if _is_set(sub_stage):
            run.sub_stage = sub_stage
        if _is_set(current):
            run.current = current
        if _is_set(total):
            run.total = total
        if _is_set(message):
            run.message = message
        if _is_set(error):
            run.error = error
        if _is_set(task_kind):
            run.task_kind = task_kind
        if _is_set(request_payload):
            run.request_payload = self._serialize_request_payload(request_payload)
        if _is_set(cancel_requested):
            run.cancel_requested = cancel_requested
        if _is_set(worker_id):
            run.worker_id = worker_id
        if _is_set(heartbeat_at):
            run.heartbeat_at = heartbeat_at
        if _is_set(started_at):
            run.started_at = started_at
        if _is_set(completed_at):
            run.completed_at = completed_at
        run.updated_at = now
        self.session.commit()

    def get_run_by_run_id_prefix(self, run_id_prefix: str) -> dict[str, Any] | None:
        """
        通过run_id前缀获取运行记录

        使用run_id前缀匹配查询运行记录

        Args:
            run_id_prefix: run_id前缀（如前8位）

        Returns:
            运行记录字典，不存在则返回 None

        使用 limit(1) 避免多记录时抛出异常
        """
        # 2026-08-13 P2-9：前缀中的 %/_/\\ 按字面字符匹配，避免被 LIKE 当作通配符
        escaped_prefix = (
            run_id_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        stmt = (
            select(AnalysisRun)
            .where(AnalysisRun.run_id.like(f"{escaped_prefix}%", escape="\\"))
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
        """2026-08-05 用于按当前 ORM 外键逆序删除运行数据并由调用方统一提交"""
        exists_stmt = select(AnalysisRun.run_id).where(AnalysisRun.run_id == run_id)
        if self.session.execute(exists_stmt).scalar_one_or_none() is None:
            return False

        existing_table_names = set(inspect(self.session.get_bind()).get_table_names())
        for table in reversed(Base.metadata.sorted_tables):
            if table.name not in existing_table_names:
                continue
            run_id_column = table.c.get("run_id")
            if run_id_column is None:
                continue
            self.session.execute(delete(table).where(run_id_column == run_id))
        self.session.flush()
        return True

    def count_distinct_novels(self) -> int:
        """
        统计不同小说的数量

        返回 analysis_runs 表中 distinct novel_id 的数量
        """
        from sqlalchemy import func, select

        stmt = select(func.count(func.distinct(AnalysisRun.novel_id))).select_from(AnalysisRun)
        result = self.session.execute(stmt)
        return result.scalar() or 0

    def mark_running_as_failed(self, *, stale_before: datetime) -> int:
        """
        将明确可判定为孤儿的 running 任务标记为 failed

        仅回收带有 worker 归属且心跳超时的任务，避免新进程误收口其他活跃实例上的真实运行任务

        Returns:
            受影响的行数
        """
        from sqlalchemy import update

        now = datetime.now(UTC)
        stmt = (
            update(AnalysisRun)
            .where(AnalysisRun.status == "running")
            .where(AnalysisRun.worker_id.is_not(None))
            .where(AnalysisRun.heartbeat_at.is_not(None))
            .where(AnalysisRun.heartbeat_at < stale_before)
            # 2026-08-14 P2-12：孤儿回收同时落 error/completed_at，
            # 前端 failed 不再缺错误原因与完成时间
            .values(
                status="failed",
                error="孤儿任务回收（worker 心跳超时）",
                completed_at=now,
                updated_at=now,
            )
        )
        result = self.session.execute(stmt)
        self.session.commit()
        count = result.rowcount  # type: ignore[attr-defined]
        if count > 0:
            logger.info(f"Marked {count} orphaned running task(s) as failed on startup")
        return count

    def mark_cancelling_as_cancelled(self, *, stale_before: datetime) -> int:
        """
        将明确可判定为孤儿的 cancelling 任务收口为 cancelled

        仅回收带有 worker 归属且心跳超时的任务，避免误终结仍在其他实例中收尾的任务

        Returns:
            受影响的行数
        """
        from sqlalchemy import update

        now = datetime.now(UTC)
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

        返回每个 novel_id 的最新运行记录，用于小说列表展示

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
