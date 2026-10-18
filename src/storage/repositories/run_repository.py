"""
分析运行记录的数据库操作实现

来源观察写 source_title/source_author；重分析请求以六个 force_* 与
requested_num_topics 具名标量列保存（无请求该组全空，false 为实际提交）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, TypeGuard, TypeVar

from loguru import logger
from sqlalchemy import delete, inspect, select

from src.storage.models import AnalysisRun, Base

from .base import BaseRepository


def _naive_utcnow() -> datetime:
    """无时区列统一落 naive UTC 挂钟

    aware UTC 直接赋给 timestamp without time zone 列会被 PG 按会话时区转换，
    导致时间戳虚增时差。
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _utc_isoformat(value: datetime | None) -> str | None:
    """无时区 UTC 挂钟序列化为 ISO 字符串并标注 Z 后缀

    DB 各列统一存 naive UTC 墙钟；显式带 Z 后前端 new Date() 可按 UTC 解析。
    """
    return value.isoformat() + "Z" if value is not None else None


def _as_naive_utc(value: datetime | None) -> datetime | None:
    """归一化调用方传入的时间戳为 naive UTC 挂钟"""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


_UNSET = object()
T = TypeVar("T")

#: run 级表的清理顺序（子 → 父）：RESTRICT 外键决定依赖方必须先删；
#: book_cases 先于 case_entries、work_items 先于 executions（两处 RESTRICT 回指）。
_RUN_PURGE_ORDER: tuple[str, ...] = (
    "source_evidence",
    "conflict_claims",
    "fact_entity_tags",
    "conflict_records",
    "book_cases",
    "case_entries",
    "graph_facts",
    "organization_checks",
    "narrative_links",
    "event_revisions",
    "event_foreshadowing_actions",
    "dialogue_records",
    "declaration_participants",
    "event_declarations",
    "analysis_assessments",
    "agent_tool_calls",
    "narrative_groups",
    "model_calls",
    "linguistic_arcs",
    "diagnosis_reports",
    "complete_events",
    "chapter_annotations",
    "work_items",
    "executions",
    "paragraph_topics",
    "paragraph_metrics",
    "paragraph_features",
    "linguistic_spans",
    "paragraphs",
    "graph_relations",
    "graph_entities",
    "event_outbox",
    "chapters",
    "analysis_runs",
)


def _run_purge_predicates(run_id: str) -> dict[str, Any]:
    """每张 run 级表「属于该 run」的谓词：有 run_id 列直接用，其余按外键链解析"""
    from sqlalchemy import or_

    m = Base.metadata.tables

    def col(table: str, name: str) -> Any:
        return m[table].c[name]

    def ids(table: str, column: str, predicate: Any) -> Any:
        return select(m[table].c[column]).where(predicate)

    entities = ids("graph_entities", "entity_id", col("graph_entities", "run_id") == run_id)
    sessions = ids("executions", "execution_id", col("executions", "session_run_id") == run_id)
    work_items = ids(
        "work_items",
        "work_id",
        or_(
            col("work_items", "program_run_id") == run_id,
            col("work_items", "diagnosis_session_id").in_(sessions),
        ),
    )
    executions = ids(
        "executions",
        "execution_id",
        or_(
            col("executions", "session_run_id") == run_id,
            col("executions", "run_id") == run_id,
        ),
    )
    model_calls = ids(
        "model_calls",
        "call_id",
        or_(col("model_calls", "standalone_run_id") == run_id, col("model_calls", "execution_id").in_(executions)),
    )
    annotations = ids("chapter_annotations", "record_id", col("chapter_annotations", "execution_id").in_(executions))
    events = ids("complete_events", "event_id", col("complete_events", "producer_execution_id").in_(executions))
    declarations = ids("event_declarations", "declaration_id", col("event_declarations", "record_id").in_(annotations))
    reports = ids("diagnosis_reports", "report_id", col("diagnosis_reports", "session_id").in_(executions))
    links = ids("narrative_links", "link_id", col("narrative_links", "producer_execution_id").in_(executions))
    groups = ids("narrative_groups", "group_id", col("narrative_groups", "producer_execution_id").in_(executions))
    conflicts = ids("conflict_records", "conflict_id", col("conflict_records", "producer_execution_id").in_(executions))
    claims = ids("conflict_claims", "claim_id", col("conflict_claims", "producer_execution_id").in_(executions))
    checks = ids("organization_checks", "check_id", col("organization_checks", "producer_execution_id").in_(executions))
    actions = ids(
        "event_foreshadowing_actions",
        "action_id",
        col("event_foreshadowing_actions", "producer_execution_id").in_(executions),
    )
    participants = ids(
        "declaration_participants",
        "participant_id",
        col("declaration_participants", "declaration_id").in_(declarations),
    )
    relations = ids(
        "graph_relations",
        "relation_id",
        or_(
            col("graph_relations", "from_entity_id").in_(entities),
            col("graph_relations", "to_entity_id").in_(entities),
        ),
    )
    dialogues = ids(
        "dialogue_records",
        "dialogue_id",
        or_(
            col("dialogue_records", "creation_execution_id").in_(executions),
            col("dialogue_records", "current_attribution_execution_id").in_(executions),
        ),
    )
    entries = ids(
        "case_entries",
        "entry_id",
        or_(
            col("case_entries", "producer_execution_id").in_(executions),
            col("case_entries", "candidate_producer_execution_id").in_(executions),
            col("case_entries", "program_work_id").in_(work_items),
        ),
    )
    facts = ids(
        "graph_facts",
        "graph_fact_id",
        or_(
            col("graph_facts", "direct_producer_execution_id").in_(executions),
            col("graph_facts", "program_work_id").in_(work_items),
            col("graph_facts", "entity_id").in_(entities),
            col("graph_facts", "relation_id").in_(relations),
            col("graph_facts", "participant_id").in_(participants),
        ),
    )

    return {
        "source_evidence": or_(
            col("source_evidence", "declaration_id").in_(declarations),
            col("source_evidence", "complete_event_id").in_(events),
            col("source_evidence", "related_complete_event_id").in_(events),
            col("source_evidence", "graph_fact_id").in_(facts),
            col("source_evidence", "narrative_link_id").in_(links),
            col("source_evidence", "foreshadow_action_id").in_(actions),
            col("source_evidence", "narrative_group_id").in_(groups),
            col("source_evidence", "conflict_id").in_(conflicts),
            col("source_evidence", "claim_id").in_(claims),
            col("source_evidence", "check_id").in_(checks),
        ),
        "conflict_claims": col("conflict_claims", "producer_execution_id").in_(executions),
        "fact_entity_tags": col("fact_entity_tags", "graph_fact_id").in_(facts),
        "conflict_records": col("conflict_records", "producer_execution_id").in_(executions),
        "book_cases": or_(
            col("book_cases", "registration_run_id") == run_id,
            col("book_cases", "pending_event_entry_id").in_(entries),
            col("book_cases", "case_id").in_(
                select(m["case_entries"].c.case_id).where(
                    col("case_entries", "entry_id").in_(entries),
                    col("case_entries", "case_id").is_not(None),
                )
            ),
        ),
        "case_entries": col("case_entries", "entry_id").in_(entries),
        "graph_facts": col("graph_facts", "graph_fact_id").in_(facts),
        "organization_checks": col("organization_checks", "producer_execution_id").in_(executions),
        "narrative_links": col("narrative_links", "producer_execution_id").in_(executions),
        "event_revisions": or_(
            col("event_revisions", "declaration_id").in_(declarations),
            col("event_revisions", "event_id").in_(events),
        ),
        "event_foreshadowing_actions": col("event_foreshadowing_actions", "producer_execution_id").in_(executions),
        "dialogue_records": col("dialogue_records", "dialogue_id").in_(dialogues),
        "declaration_participants": col("declaration_participants", "declaration_id").in_(declarations),
        "event_declarations": col("event_declarations", "declaration_id").in_(declarations),
        "analysis_assessments": or_(
            col("analysis_assessments", "report_id").in_(reports),
            col("analysis_assessments", "record_id").in_(annotations),
            col("analysis_assessments", "scored_entity_id").in_(entities),
            col("analysis_assessments", "cast_entity_id").in_(entities),
        ),
        "agent_tool_calls": col("agent_tool_calls", "call_id").in_(model_calls),
        "narrative_groups": col("narrative_groups", "group_id").in_(groups),
        "model_calls": col("model_calls", "call_id").in_(model_calls),
        "linguistic_arcs": or_(
            col("linguistic_arcs", "head_span_id").in_(
                ids("linguistic_spans", "span_id", col("linguistic_spans", "run_id") == run_id)
            ),
            col("linguistic_arcs", "dependent_span_id").in_(
                ids("linguistic_spans", "span_id", col("linguistic_spans", "run_id") == run_id)
            ),
        ),
        "diagnosis_reports": col("diagnosis_reports", "report_id").in_(reports),
        "complete_events": col("complete_events", "event_id").in_(events),
        "chapter_annotations": col("chapter_annotations", "record_id").in_(annotations),
        "work_items": col("work_items", "work_id").in_(work_items),
        "executions": col("executions", "execution_id").in_(executions),
        "paragraph_topics": col("paragraph_topics", "run_id") == run_id,
        "paragraph_metrics": col("paragraph_metrics", "run_id") == run_id,
        "paragraph_features": col("paragraph_features", "run_id") == run_id,
        "linguistic_spans": col("linguistic_spans", "run_id") == run_id,
        "paragraphs": col("paragraphs", "run_id") == run_id,
        "graph_relations": col("graph_relations", "relation_id").in_(relations),
        "graph_entities": col("graph_entities", "entity_id").in_(entities),
        "event_outbox": col("event_outbox", "run_id") == run_id,
        "chapters": col("chapters", "run_id") == run_id,
        "analysis_runs": col("analysis_runs", "run_id") == run_id,
    }

#: 重分析请求载荷中的 force_* 阶段字段，与 analysis_runs 列名一一对应
_REQUEST_FORCE_FIELDS: tuple[str, ...] = (
    "force_preprocess",
    "force_annotate",
    "force_aggregate",
    "force_topic_model",
    "force_diagnose",
    "force_linguistic",
)


def _request_payload_columns(request_payload: dict[str, Any] | None) -> dict[str, Any]:
    """把重分析请求载荷拆成 analysis_runs 具名列（无请求该组全空）

    false 是真实提交值（保留），None/缺键才表示未请求该口径。
    """
    columns: dict[str, Any] = dict.fromkeys(_REQUEST_FORCE_FIELDS)
    columns["requested_num_topics"] = None
    if request_payload is None:
        return columns
    for field in _REQUEST_FORCE_FIELDS:
        raw_value = request_payload.get(field)
        if raw_value is not None:
            columns[field] = bool(raw_value)
    raw_num_topics = request_payload.get("num_topics")
    if raw_num_topics is not None:
        columns["requested_num_topics"] = int(raw_num_topics)
    return columns


def _request_payload_from_columns(run: AnalysisRun) -> dict[str, Any] | None:
    """把 analysis_runs 请求列重建为规范请求字典（无请求返回 None）

    重建键名与 ReanalyzeRequest 字段一致，供 resume/恢复按原语义校验；
    NULL 表示该口径未提交，不伪造 false。
    """
    payload: dict[str, Any] = {}
    for field in _REQUEST_FORCE_FIELDS:
        value = getattr(run, field)
        if value is not None:
            payload[field] = bool(value)
    if run.requested_num_topics is not None:
        payload["num_topics"] = int(run.requested_num_topics)
    return payload or None


def _is_set[T](value: T | object) -> TypeGuard[T]:
    """
    判断参数是否不是 `_UNSET` 哨兵值

    统一收窄 `T | object` 到真实字段类型，避免 mypy 把 `_UNSET` 联合类型传进 ORM 字段赋值
    """
    return value is not _UNSET


class RunRepository(BaseRepository[dict[str, Any]]):
    """运行记录数据访问层

    管理分析运行的创建、查询和状态更新（使用 AnalysisRun ORM 模型）
    """

    def _to_dict_with_deserialization(self, run: AnalysisRun) -> dict[str, Any]:
        """
        将 ORM 对象转换为字典并重建 request_payload

        按 force_*/requested_num_topics 列重建与 ReanalyzeRequest 同键的
        字典（无请求为 None）。
        """
        request_payload_dict = _request_payload_from_columns(run)

        return {
            "run_id": run.run_id,
            "novel_id": run.novel_id,
            "source_path": run.source_path,
            "title": run.source_title,
            "author": run.source_author,
            "source_title": run.source_title,
            "source_author": run.source_author,
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
        """创建新的分析运行记录。Args: novel_id/source_path/title/author/run_id；Returns: 运行ID。

        title/author 形参写入 analysis_runs.source_title/source_author（运行开始时来源观察）。
        """
        if run_id is None:
            run_id = str(uuid.uuid4())
        now = _naive_utcnow()

        run = AnalysisRun(
            run_id=run_id,
            novel_id=novel_id,
            source_path=source_path,
            source_title=title,
            source_author=author,
            status="pending",
            task_kind=task_kind,
            created_at=now,
            updated_at=now,
            **_request_payload_columns(request_payload),
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

        # heartbeat_at 列无时区，统一落 naive UTC 挂钟，避免 PG 按会话时区转换导致误判
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
                # 重领（诊断重试触发的 re-claim）保留首次开始时间：
                # started_at 不能被覆盖成最后一次 claim 的时刻
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
            # 请求整组重写为具名列；未提交口径置空
            for field, value in _request_payload_columns(request_payload).items():
                setattr(run, field, value)
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
        # 前缀中的 %/_/\\ 按字面字符匹配，避免被 LIKE 当作通配符
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
        """按运行范围删除全部 run 级数据，由调用方统一提交

        35 表里只有 9 张带 run_id 列，其余 run 级表按真实外键链解析归属；
        删除按 _RUN_PURGE_ORDER 的显式子→父顺序走，
        保证 RESTRICT 外键（含 book_cases↔case_entries、executions↔work_items
        两处互相引用）先删依赖方。novels 是全局书目，不属于任何 run，不删。
        """
        exists_stmt = select(AnalysisRun.run_id).where(AnalysisRun.run_id == run_id)
        if self.session.execute(exists_stmt).scalar_one_or_none() is None:
            return False

        existing_table_names = set(inspect(self.session.get_bind()).get_table_names())
        predicates = _run_purge_predicates(run_id)
        for table_name in _RUN_PURGE_ORDER:
            if table_name not in existing_table_names:
                continue
            table = Base.metadata.tables[table_name]
            self.session.execute(delete(table).where(predicates[table_name]))
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
            # 孤儿回收同时落 error/completed_at，使 failed 带错误原因与完成时间
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
