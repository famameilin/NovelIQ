"""
章节标注案例池与连续性事实 ORM 模型
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    """2026-08-05 用于生成连续性业务表统一的 UTC 时间"""
    return datetime.now(UTC)


class ChapterAnnotationRecord(Base):
    """2026-08-05 用于保存每个 run 章节唯一的完整正式标注"""

    __tablename__ = "chapter_annotations"

    annotation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    initial_finish_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    after_chapter_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    revision_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "chapter_id", name="uq_chapter_annotations_run_chapter"),
        Index("idx_chapter_annotations_run_chapter", "run_id", "chapter_id"),
    )


class CasePoolCase(Base):
    """2026-08-05 用于保存需要后续章节继续处理的活动或历史案例"""

    __tablename__ = "case_pool_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    keys: Mapped[list] = mapped_column(JSONB, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_annotation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE"),
        nullable=False,
    )
    last_surfaced_annotation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chapter_annotations.annotation_id", ondelete="SET NULL"),
        nullable=True,
    )
    last_surfaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    __table_args__ = (
        UniqueConstraint("run_id", "dedupe_key", name="uq_case_pool_cases_run_dedupe"),
        Index("idx_case_pool_cases_run_state", "run_id", "state"),
        Index("idx_case_pool_cases_rotation", "run_id", "state", "last_surfaced_at", "id"),
    )


class ContinuityFact(Base):
    """2026-08-05 用于保存 Agent 明确 push 的独立连续性事实"""

    __tablename__ = "continuity_facts"

    fact_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_annotation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE"),
        nullable=False,
    )
    fact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[dict] = mapped_column(JSONB, nullable=False)
    predicate: Mapped[str] = mapped_column(String(255), nullable=False)
    object: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    participants: Mapped[list] = mapped_column(JSONB, nullable=False)
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    story_time: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    assertion: Mapped[str] = mapped_column(String(20), nullable=False)
    change_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    linked_fact_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "dedupe_key", name="uq_continuity_facts_run_dedupe"),
        Index("idx_continuity_facts_run_predicate", "run_id", "predicate"),
        Index("idx_continuity_facts_run_linked", "run_id", "linked_fact_id"),
    )


class CaseResolutionMapping(Base):
    """2026-08-05 用于关联章节输出来源案例与实际业务目标"""

    __tablename__ = "case_resolution_mappings"

    mapping_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    annotation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_case_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("case_pool_cases.id", ondelete="SET NULL"),
        nullable=True,
    )
    result_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_case_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("case_pool_cases.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_fact_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("continuity_facts.fact_id", ondelete="SET NULL"),
        nullable=True,
    )
    target_setup_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("foreshadowing_threads.setup_id", ondelete="SET NULL"),
        nullable=True,
    )
    target_hit_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("foreshadowing_thread_hits.hit_id", ondelete="SET NULL"),
        nullable=True,
    )
    rejected_reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("idx_case_resolution_mappings_annotation", "run_id", "annotation_id"),
        Index("idx_case_resolution_mappings_source", "run_id", "source_case_id"),
    )
