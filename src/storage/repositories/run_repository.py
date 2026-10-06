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


def _naive_utcnow() -> datetime:
    """2026-08-26 无时区列统一落 naive UTC 挂钟

    与 2026-08-13 heartbeat_at 修复同口径：aware UTC 直接赋给
    timestamp without time zone 列会被 PG 按会话时区（如 Asia/Shanghai）
    转换，导致 completed_at 等时间戳虚增 8 小时。
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _utc_isoformat(value: datetime | None) -> str | None:
    """2026-08-26 无时区 UTC 挂钟序列化为 ISO 字符串并标注 Z 后缀

    DB 各列统一存 naive UTC 墙钟，序列化显式带 Z 后前端
    new Date() 可按 UTC 解析并正确显示本地时间。
    """
    return value.isoformat() + "Z" if value is not None else None


def _as_naive_utc(value: datetime | None) -> datetime | None:
    """2026-08-26 归一化调用方传入的时间戳为 naive UTC 挂钟"""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)

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

    def _to_dict_with_deserialization(self, run: AnalysisRun) -> dict[str, Any]:
        """
        将 ORM 对象转换为字典并反序列化 request_payload

        2026-08-20 优化：反序列化逻辑内联于此，减少多个端点各1层的函数调用开销
        """
        # 内联反序列化逻辑，避免额外的函数调用
        request_payload_dict = None
        if run.request_payload:
            try:
                request_payload_dict = json.loads(run.request_payload)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to deserialize request_payload: {e}")

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
            "task_kind": run.task_kind,
            "request_payload": request_payload_dict,
            "cancel_requested": run.cancel_requested,
            "worker_id": run.worker_id,
            "heartbeat_at": _utc_isoformat(run.heartbeat_at),
            "started_at": _utc_isoformat(run.started_at),
            "completed_at": _utc_isoformat(run.completed_at),
            "created_at": _utc_isoformat(run.created_at),
            "updated_at": _utc_isoformat(run.updated_at),
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
        """创建新的分析运行记录。Args: novel_id/source_path/title/author/run_id；Returns: 运行ID。"""
        if run_id is None:
            run_id = str(uuid.uuid4())
        now = _naive_utcnow()

        run = AnalysisRun(
            run_id=run_id,
            novel_id=novel_id,
            source_path=source_path,
            title=title,
            author=author,
            status="pending",
            task_kind=task_kind,
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
        return self._to_dict_with_deserialization(run)

    def update_run_status(self, run_id: str, status: str) -> None:
        """
        更新运行状态

        Args:
            run_id: 运行ID
            status: 新状态
        """
        now = _naive_utcnow()
        stmt = select(AnalysisRun).where(AnalysisRun.run_id == run_id)
        run = self.session.execute(stmt).scalar_one_or_none()
        if run:
            run.status = status
            if status in ("completed", "failed", "cancelled"):
                run.completed_at = now
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
        return [self._to_dict_with_deserialization(run) for run in runs]

    def cancel_run(self, run_id: str) -> bool:
        """原子性设置取消标记（DB 驱动 cancel_requested）。Args: run_id；Returns: 是否成功。"""
        from sqlalchemy import update

        stmt = (
            update(AnalysisRun)
            .where(AnalysisRun.run_id == run_id)
            .where(AnalysisRun.cancel_requested.is_(False))
            .values(cancel_requested=True,
                    updated_at=_naive_utcnow())
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

        now = _naive_utcnow()
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
        """按状态查询任务。Args: status；Returns: 任务记录列表。"""
        stmt = select(AnalysisRun).where(AnalysisRun.status == status).order_by(AnalysisRun.created_at.desc())
        runs = self.session.execute(stmt).scalars().all()
        return [self._to_dict_with_deserialization(run) for run in runs]

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
        from sqlalchemy import func, update

        # 2026-08-13 P2：heartbeat_at 列无时区，默认值统一落 naive UTC 挂钟
        # （避免 aware UTC 被 PG 按会话时区转换，导致 resume 窗口/孤儿回收误判）
        now = heartbeat_at or _naive_utcnow()
        stmt = (
            update(AnalysisRun)
            .where(AnalysisRun.run_id == run_id)
            .where(AnalysisRun.status == "pending")
            .where(AnalysisRun.cancel_requested.is_(False))
            .values(
                status="running",
                worker_id=worker_id,
                heartbeat_at=now,
                # 2026-10-04 重领（诊断重试触发的 re-claim）保留首次开始时间：
                # started_at 曾被覆盖成最后一次 claim 时刻，两次 run 的表面耗时
                # 因此缩水成 13m36s/7m26s（真实 16h46m/4h09m）
                started_at=func.coalesce(AnalysisRun.started_at, now),
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

        now = _naive_utcnow()
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
        """批量更新运行态字段（仅写入显式传入的字段）。"""
        stmt = select(AnalysisRun).where(AnalysisRun.run_id == run_id)
        run = self.session.execute(stmt).scalar_one_or_none()
        if not run:
            return

        now = _naive_utcnow()
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
            run.heartbeat_at = _as_naive_utc(heartbeat_at)
        if _is_set(started_at):
            run.started_at = _as_naive_utc(started_at)
        if _is_set(completed_at):
            run.completed_at = _as_naive_utc(completed_at)
        run.updated_at = now
        self.session.commit()

    def get_run_by_run_id_prefix(self, run_id_prefix: str) -> dict[str, Any] | None:
        """按 run_id 前缀查询（LIKE 转义 %/_/\，limit(1) 防多记录异常）。Args: run_id_prefix；Returns: 记录或 None。"""
        # 2026-08-13 P2-9：前缀中的 %/_/\\ 按字面字符匹配，避免被 LIKE 当作通配符
        escaped_prefix = run_id_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = (
            select(AnalysisRun)
            .where(AnalysisRun.run_id.like(f"{escaped_prefix}%", escape="\\"))
            .order_by(AnalysisRun.created_at.asc())
            .limit(1)
        )
        run = self.session.execute(stmt).scalar_one_or_none()
        if run is None:
            return None
        return self._to_dict_with_deserialization(run)

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

    def mark_running_as_failed(self) -> int:
        """
        启动时把所有 running 任务标记为 failed

        任务运行态与 work 队列都只活在进程内，也没有租约或半成品持久态：
        进程重启后 running 行不存在活着的执行方，必然是孤儿，一律收口。
        前提是单实例部署——将来两个进程共库时，新进程会终结旧进程正在跑的任务。

        Returns:
            受影响的行数
        """
        from sqlalchemy import update

        now = _naive_utcnow()
        stmt = (
            update(AnalysisRun)
            .where(AnalysisRun.status == "running")
            # 2026-08-14 P2-12：孤儿回收同时落 error/completed_at，
            # 前端 failed 不再缺错误原因与完成时间
            .values(
                status="failed",
                error="进程重启，运行中的任务已终止",
                completed_at=now,
                worker_id=None,
                heartbeat_at=None,
                updated_at=now,
            )
        )
        result = self.session.execute(stmt)
        self.session.commit()
        count = result.rowcount  # type: ignore[attr-defined]
        if count > 0:
            logger.info(f"Marked {count} running task(s) as failed on startup")
        return count

    def mark_cancelling_as_cancelled(self) -> int:
        """
        启动时把所有 cancelling 任务收口为 cancelled

        与 running 同理：重启后不存在仍在收尾的执行方，cancelling 只会是死状态

        Returns:
            受影响的行数
        """
        from sqlalchemy import update

        now = _naive_utcnow()
        stmt = (
            update(AnalysisRun)
            .where(AnalysisRun.status == "cancelling")
            .values(
                status="cancelled",
                cancel_requested=False,
                completed_at=now,
                worker_id=None,
                heartbeat_at=None,
                updated_at=now,
            )
        )
        result = self.session.execute(stmt)
        self.session.commit()
        count = result.rowcount  # type: ignore[attr-defined]
        if count > 0:
            logger.info(f"Marked {count} cancelling task(s) as cancelled on startup")
        return count
