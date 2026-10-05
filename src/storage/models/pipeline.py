"""并行标注流水线的持久化工作、命令与可见性边界"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class WorkItem(Base):
    """统一任务队列：章节标注与连续性共用一套 4 态状态机，数据库行是工作领取与迟到写回的唯一真相源"""

    __tablename__ = "work_items"

    work_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"))
    work_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    logical_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    cutoff_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="waiting")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_hash: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "run_id", "work_kind", "logical_key", "payload_hash", "cutoff_hash",
            name="uq_work_identity",
        ),
        CheckConstraint("work_kind IN ('formal_current', 'continuity')", name="ck_work_kind"),
        CheckConstraint(
            "state IN ('waiting', 'running', 'succeeded', 'failed')",
            name="ck_work_state",
        ),
        Index("idx_work_claim", "state", "available_at", "priority"),
        Index("idx_work_run_state", "run_id", "state"),
    )


class SemanticCommand(Base):
    """不可变的局部事实与连续性声明，投影可以从它们完整重建"""

    __tablename__ = "semantic_commands"

    command_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"))
    origin_annotation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE")
    )


    origin_chapter_id: Mapped[int | None] = mapped_column(Integer)
    origin_chapter_sequence: Mapped[int | None] = mapped_column(Integer)
    command_path: Mapped[str] = mapped_column(String(255), nullable=False)
    command_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    partition_key: Mapped[str] = mapped_column(String(128), nullable=False)
    effective_document_position: Mapped[dict] = mapped_column(JSONB, nullable=False)
    explicit_story_time: Mapped[dict | None] = mapped_column(JSONB)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    independence_keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    parent_command_id: Mapped[str | None] = mapped_column(String(64))
    precondition_epoch: Mapped[int | None] = mapped_column(Integer)
    precondition_hash: Mapped[str | None] = mapped_column(String(64))
    # 2026-10-05 队列删除后 author_work_id 只是铸造回执的溯源标识，不再是 work_items 外键
    author_work_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("origin_annotation_id", "command_path", name="uq_semantic_command_annotation_path"),
        CheckConstraint("jsonb_array_length(evidence_ids) > 0", name="ck_semantic_command_evidence"),
        Index("idx_semantic_command_partition", "run_id", "partition_key", "created_at"),
    )


class TextEvidenceRecord(Base):
    """原文精确区间是正式事实和连续性命令的根证据"""

    __tablename__ = "text_evidence"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    paragraph_id: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"], ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE", name="text_evidence_paragraph_fkey",
        ),
        CheckConstraint("char_start >= 0 AND char_end > char_start", name="ck_text_evidence_span"),
        UniqueConstraint(
            "run_id", "paragraph_id", "char_start", "char_end", "source_manifest_hash",
            name="uq_text_evidence_span",
        ),
    )


class CommandOutcome(Base):
    """命令的可重建处理结果，不回写不可变命令"""

    __tablename__ = "command_outcomes"

    command_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("semantic_commands.command_id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(80))
    partition_key: Mapped[str] = mapped_column(String(128), nullable=False)
    head_epoch: Mapped[int | None] = mapped_column(Integer)
    state_hash: Mapped[str | None] = mapped_column(String(64))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "state IN ('accepted', 'conflict', 'pending_dependency', 'rejected')",
            name="ck_command_outcome_state",
        ),
    )


class ContinuityCase(Base):
    """案例身份与目标不可变，同一稳定目标只保留一个案例"""

    __tablename__ = "continuity_cases"

    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"))
    case_key: Mapped[str] = mapped_column(String(64), nullable=False)
    issue_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    search_keys: Mapped[list] = mapped_column(JSONB, nullable=False)
    target_ref: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_evidence: Mapped[list] = mapped_column(JSONB, nullable=False)
    originating_annotation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE")
    )
    originating_chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "case_key", name="uq_continuity_cases_key"),
        CheckConstraint("jsonb_array_length(source_evidence) > 0", name="ck_continuity_case_evidence"),
    )


class CaseHead(Base):
    """局部 CAS 状态；活动 lease 只由本行决定"""

    __tablename__ = "case_heads"

    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("continuity_cases.case_id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    head_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_lease_hash: Mapped[str | None] = mapped_column(String(64))
    active_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'resolved', 'deferred', 'contested')", name="ck_case_head_state"
        ),
    )


class CaseClaim(Base):
    """保留全部抢占历史，过期持有者不能消费新 epoch"""

    __tablename__ = "case_claims"

    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("continuity_cases.case_id", ondelete="CASCADE"), primary_key=True
    )
    claim_epoch: Mapped[int] = mapped_column(Integer, primary_key=True)
    lease_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # 2026-10-05 队列删除后 work_id 只是工作回执的溯源标识，不再是 work_items 外键
    work_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'consumed', 'released', 'expired')", name="ck_case_claim_status"
        ),
    )


class AnalysisCutoff(Base):
    """只有 released 行可以成为 API 和聚合的业务可见边界"""

    __tablename__ = "analysis_cutoffs"

    cutoff_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"))
    round_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    formal_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    command_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    case_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    cancellation_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="sealing")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("run_id", "round_kind", "round_number", name="uq_analysis_cutoff_round"),
        CheckConstraint("state IN ('sealing', 'projecting', 'released', 'failed')", name="ck_cutoff_state"),
        Index("idx_analysis_cutoff_latest", "run_id", "state", "released_at"),
    )


class PartitionHead(Base):
    """每个语义目标局部推进，投影哈希可从命令重算核对"""

    __tablename__ = "partition_heads"

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    partition_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    head_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    projection: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class CutoffPartition(Base):
    """释放后的分区快照不随下一轮 partition head 推进而变化"""

    __tablename__ = "cutoff_partitions"

    cutoff_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("analysis_cutoffs.cutoff_hash", ondelete="CASCADE"), primary_key=True
    )
    partition_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    projection: Mapped[dict] = mapped_column(JSONB, nullable=False)
    projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class SourceManifest(Base):
    """全书原文快照哈希只存一份，章节工作引用它而非重复携带全书段落"""

    __tablename__ = "source_manifests"

    source_manifest_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"))
    chapter_hashes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    paragraph_hashes: Mapped[dict] = mapped_column(JSONB, nullable=False)


class FormalArtifact(Base):
    """正式结果操作日志与授权一并冻结，重放不依赖运行期 FactGraph"""

    __tablename__ = "formal_artifacts"

    annotation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE"), primary_key=True
    )
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    materialized: Mapped[bool] = mapped_column(default=False, nullable=False)


class EventOutbox(Base):
    """与业务状态同事务写入，Dispatcher 负责可重放发布"""

    __tablename__ = "event_outbox"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"))
    chapter_id: Mapped[int | None] = mapped_column(Integer)
    cutoff_hash: Mapped[str | None] = mapped_column(String(64))
    stream_id: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_event_outbox_stream", "run_id", "stream_id"),
        Index("idx_event_outbox_pending", "published_at", "created_at"),
    )
