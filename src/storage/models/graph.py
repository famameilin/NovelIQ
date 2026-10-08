"""章节图谱当前状态 ORM 模型"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, naive_utcnow


@dataclass(frozen=True, slots=True)
class ChapterBoundary:
    """2026-08-19 用于表示由章节身份派生的图谱边界"""

    run_id: str
    chapter_id: int
    chapter_order: int
    first_chapter_id: int
    last_chapter_id: int
    annotation_id: str


class GraphEntity(Base):
    """2026-08-19 用于保存单次分析运行内稳定的实体身份

    2026-09-19 id 纪律：所有 id 都是 uuid——entity_id 主键从自增 int 改为
    String(36) uuid（uuid5 按 run+规范名确定性铸造，agent 运行面与落库同值，
    见 fact_graph._entity_uuid）。
    """

    __tablename__ = "graph_entities"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('character', 'location', 'item', 'organization')",
            name="ck_graph_entities_type",
        ),
        Index("idx_graph_entities_run_canonical", "run_id", "canonical_name"),
        Index("idx_graph_entities_run_type", "run_id", "entity_type"),
        Index("idx_graph_entities_run_last_seen", "run_id", "last_seen_chapter"),
        {"comment": "图实体表：run 内稳定实体身份（uuid5 按 run+规范名确定性铸造）"},
    )

    entity_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="实体主键（uuid）")
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, comment="所属分析运行"
    )
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="实体规范名")
    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="实体类型（character/location/item/organization）"
    )
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, comment="标签列表")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, comment="实体属性字典")
    first_seen_chapter: Mapped[int] = mapped_column(Integer, nullable=False, comment="首次出现章")
    last_seen_chapter: Mapped[int] = mapped_column(Integer, nullable=False, comment="最后出现章")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, onupdate=naive_utcnow, comment="更新时间"
    )


class GraphFact(Base):
    """2026-08-19 用于保存章节事实及其来源证据"""

    __tablename__ = "graph_facts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="graph_facts_chapter_run_fkey",
        ),
        ForeignKeyConstraint(
            ["effective_chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="graph_facts_effective_chapter_run_fkey",
        ),
        CheckConstraint("jsonb_array_length(evidence) > 0", name="ck_graph_facts_evidence_non_empty"),
        UniqueConstraint("run_id", "chapter_id", "fact_id", name="uq_graph_facts_run_chapter_fact"),
        UniqueConstraint("run_id", "chapter_id", "payload_path", name="uq_graph_facts_chapter_payload_path"),
        Index("idx_graph_facts_run_chapter", "run_id", "chapter_id"),
        Index("idx_graph_facts_run_subject_predicate", "run_id", "subject_entity_id", "predicate"),
        Index("idx_graph_facts_run_event", "run_id", "event_id"),
        {"comment": "图事实表：章节事实（主谓宾+断言强度+生效章）及其原文证据"},
    )

    graph_fact_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, comment="所属分析运行"
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="事实登记章")
    fact_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="章内事实键")
    fact_type: Mapped[str] = mapped_column(String(100), nullable=False, comment="事实类型")
    subject_entity_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("graph_entities.entity_id", ondelete="RESTRICT"),
        nullable=True,
        comment="主语实体（可空）",
    )
    predicate: Mapped[str] = mapped_column(String(255), nullable=False, comment="谓词")
    object: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="宾语（可空）")
    value: Mapped[Any | None] = mapped_column(JSONB, nullable=True, comment="值（可空）")
    participants: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, comment="参与者列表")
    scope: Mapped[str] = mapped_column(String(255), nullable=False, comment="作用域")
    story_time: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="故事内时间（可空）")
    assertion: Mapped[str] = mapped_column(String(20), nullable=False, comment="断言类型")
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, comment="置信度")
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, comment="事实内容")
    effective_chapter_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="生效章")
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False, comment="来源种类")
    annotation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_outputs.output_id", ondelete="CASCADE"),
        nullable=False,
        comment="来源标注 id",
    )
    payload_path: Mapped[str] = mapped_column(String(255), nullable=False, comment="章内 payload 路径（章内唯一）")
    author_work_id: Mapped[str | None] = mapped_column(String(64), comment="产生该行的 agent 执行 work 标识")
    event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("event_nodes.event_id", ondelete="RESTRICT"),
        nullable=True,
        comment="关联事件（可空）",
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, comment="原文证据列表（非空）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )


class EntityState(Base):
    """2026-08-19 用于保存实体在章节边界的状态和变化"""

    __tablename__ = "entity_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="entity_states_chapter_run_fkey",
        ),
        CheckConstraint("jsonb_array_length(changes) > 0", name="ck_entity_states_changes_non_empty"),
        Index("idx_entity_states_run_entity", "run_id", "entity_id", "chapter_id"),
        {"comment": "实体状态表：实体在章节边界的状态快照与变化记录（每实体每章一行）"},
    )

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True, comment="所属分析运行"
    )
    chapter_id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="章节编号")
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), primary_key=True, comment="实体 id"
    )
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, comment="章末状态")
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, comment="本章变化列表（非空）")
    author_work_id: Mapped[str | None] = mapped_column(String(64), comment="产生该行的 agent 执行 work 标识")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )


class GraphRelation(Base):
    """2026-08-19 用于保存稳定关系身份及其实体端点"""

    __tablename__ = "graph_relations"
    __table_args__ = (
        CheckConstraint("directionality IN ('directed', 'bidirectional')", name="ck_graph_relations_directionality"),
        CheckConstraint("relation_semantics IN ('ordinary', 'same_character')", name="ck_graph_relations_semantics"),
        CheckConstraint("from_entity_id <> to_entity_id", name="ck_graph_relations_distinct_endpoints"),
        Index("idx_graph_relations_run_from", "run_id", "from_entity_id"),
        Index("idx_graph_relations_run_to", "run_id", "to_entity_id"),
        {"comment": "图关系表：稳定关系身份及其实体端点（方向性与语义受约束）"},
    )

    relation_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="关系主键（uuid）")
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, comment="所属分析运行"
    )
    from_entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), nullable=False, comment="起点实体"
    )
    to_entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), nullable=False, comment="终点实体"
    )
    directionality: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="方向性（directed/bidirectional）"
    )
    relation_semantics: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="关系语义（ordinary/same_character）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )


class RelationState(Base):
    """2026-08-19 用于保存关系在章节边界的状态和变化"""

    __tablename__ = "relation_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="relation_states_chapter_run_fkey",
        ),
        CheckConstraint("jsonb_array_length(changes) > 0", name="ck_relation_states_changes_non_empty"),
        Index("idx_relation_states_run_relation", "run_id", "relation_id", "chapter_id"),
        Index("idx_relation_states_run_active", "run_id", "is_active"),
        {"comment": "关系状态表：关系在章节边界的状态与变化记录（每关系每章一行）"},
    )

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True, comment="所属分析运行"
    )
    chapter_id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="章节编号")
    relation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("graph_relations.relation_id", ondelete="CASCADE"), primary_key=True, comment="关系 id"
    )
    relation_type: Mapped[str] = mapped_column(String(100), nullable=False, comment="关系类型")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, comment="关系属性")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="是否活跃")
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, comment="本章变化列表（非空）")
    author_work_id: Mapped[str | None] = mapped_column(String(64), comment="产生该行的 agent 执行 work 标识")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )
