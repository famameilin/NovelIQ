"""
工作、执行与正式产物 ORM 模型

推导项不落列：novel/run 从 session 取，逐段情绪的 run/chapter 从 record 取，
名单顺序与去重由条件唯一约束保证。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base, naive_utcnow

#: 执行角色封闭取值（章内四个标注角色 + 诊断两个角色）
AGENT_TYPES = ("annotation", "entity", "event", "metric", "case", "report")
#: 章内标注角色取值域
ANNOTATION_ROLES = ("annotation", "entity", "event", "metric")
#: 诊断角色封闭取值（案例办理与报告收尾）
DIAGNOSIS_ROLES = ("case", "report")
#: 执行状态封闭取值
AGENT_STATUSES = ("running", "success", "error")
#: 诊断重点结构封闭取值
FOCUS_STRUCTURES = ("single", "dual", "ensemble")
#: 人物名单角色封闭取值（三份名单独立有序，不双存主角布尔）
CAST_ROLES = ("focus", "main", "core")


class Agent(Base):
    "真实 Agent 身份与运行结局"

    __tablename__ = "agent"
    __table_args__ = (
        CheckConstraint("type IN ('annotation', 'entity', 'event', 'metric', 'case', 'report')", name="ck_agent_type"),
        CheckConstraint("status IN ('running', 'success', 'error')", name="ck_agent_status"),
    )
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")


class ChapterAnnotation(Base):
    "正式章节标注记录表"

    __tablename__ = "agent_annotations"
    __table_args__ = (
        CheckConstraint("emotional_valence IN (-2, -1, 0, 1, 2)", name="ck_chapter_annotations_valence"),
        CheckConstraint("role IN ('annotation', 'entity', 'event', 'metric')", name="ck_chapter_annotations_role"),
        ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE", name="chapter_annotations_run_fkey"),
        ForeignKeyConstraint(
            ["run_id", "chapter_id"],
            ["chapters.run_id", "chapters.chapter_id"],
            ondelete="CASCADE",
            name="chapter_annotations_chapter_fkey",
        ),
        {"comment": "章节标注表：正式产物头与归属（run/章/角色），每个 Agent 至多一份正式产物"},
    )

    record_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="产物主键", default=new_id, autoincrement=False
    )
    agent_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("agent.id", ondelete="RESTRICT", name="chapter_annotations_execution_fkey"),
        nullable=False,
        unique=True,
        comment="产生产物的真实执行",
    )
    run_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, comment="产出所属运行")
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="产出所属章节编号")
    role: Mapped[str] = mapped_column(String(20), nullable=False, comment="产出角色（annotation/entity/event/metric）")
    consolidation_digest: Mapped[str | None] = mapped_column(Text, nullable=True, comment="已核对的正式标注来源摘要")
    # 具名指标独立提交：实体/事件角色执行没有章级指标时各列为空
    summary: Mapped[str | None] = mapped_column(String, nullable=True, comment="章节摘要")
    emotional_valence: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="情绪效价（-2..2）")
    narrative_function: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="叙事功能")
    pivot_moment: Mapped[bool | None] = mapped_column(nullable=True, comment="是否含关键转折")
    cliffhanger: Mapped[bool | None] = mapped_column(nullable=True, comment="是否悬念收尾")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow, comment="创建时间")
    saved_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="五组件成功事务落库时间"
    )

    def __repr__(self) -> str:
        return f"<ChapterAnnotation(record_id={self.record_id})>"


class DiagnosisReport(Base):
    "正式全书诊断表"

    __tablename__ = "diagnosis_reports"
    __table_args__ = (
        CheckConstraint(
            "value_logic_type IS NULL OR value_logic_type IN ('善义有价值', '强者为王', '混合型')",
            name="ck_diagnosis_reports_value_logic_type",
        ),
        CheckConstraint(
            "focus_structure IS NULL OR focus_structure IN ('single', 'dual', 'ensemble')",
            name="ck_diagnosis_reports_focus_structure",
        ),
        CheckConstraint(
            "power_stance_score IS NULL OR (power_stance_score BETWEEN 0 AND 5)",
            name="ck_diagnosis_reports_power_score",
        ),
        CheckConstraint(
            "common_people_dignity IS NULL OR (common_people_dignity BETWEEN 0 AND 5)",
            name="ck_diagnosis_reports_dignity_score",
        ),
        CheckConstraint(
            "cultural_depth_score IS NULL OR (cultural_depth_score BETWEEN 0 AND 5)",
            name="ck_diagnosis_reports_cultural_score",
        ),
        {"comment": "诊断报告表：正式诊断正文、评分与冻结核对承诺（一运行正式发布唯一由触发器校验）"},
    )

    report_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="报告主键", default=new_id, autoincrement=False
    )
    agent_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("agent.id", ondelete="RESTRICT", name="diagnosis_reports_session_fkey"),
        nullable=False,
        unique=True,
        comment="产出报告的真实 Agent",
    )
    diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True, comment="整体诊断正文")
    value_logic_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="价值观类型")
    value_logic_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="价值观判断理由")
    power_stance_score: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="强者立场评分（0..5）")
    power_stance_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="强者立场理由")
    common_people_dignity: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="普通人尊严评分（0..5）")
    dignity_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="尊严判断理由")
    cultural_depth_score: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="文化深度评分（0..5）")
    cultural_depth_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="文化深度理由")
    narrative_arc_type: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="叙事弧类型短标签")
    focus_structure: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="重点结构")
    theme_color: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="主题色（十六进制）")
    identity_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True, comment="身份核对冻结承诺")
    structure_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True, comment="结构核对冻结承诺")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow, comment="创建时间")

    def __repr__(self) -> str:
        return f"<DiagnosisReport(report_id={self.report_id})>"


class AnalysisAssessment(Base):
    "分析条目表（六类有限条目，恰一形状）"

    __tablename__ = "agent_assessments"
    __table_args__ = (
        CheckConstraint(
            "(record_id IS NOT NULL AND paragraph_id IS NOT NULL AND emotion IS NOT NULL"
            " AND report_id IS NULL AND ordinal IS NULL AND genre_label IS NULL AND style_label IS NULL"
            " AND topic_id IS NULL AND topic_label IS NULL AND scored_entity_id IS NULL"
            " AND character_score IS NULL AND cast_role IS NULL AND cast_entity_id IS NULL)"
            " OR (report_id IS NOT NULL AND ordinal IS NOT NULL AND genre_label IS NOT NULL"
            " AND record_id IS NULL AND paragraph_id IS NULL AND emotion IS NULL AND style_label IS NULL"
            " AND topic_id IS NULL AND topic_label IS NULL AND scored_entity_id IS NULL"
            " AND character_score IS NULL AND cast_role IS NULL AND cast_entity_id IS NULL)"
            " OR (report_id IS NOT NULL AND ordinal IS NOT NULL AND style_label IS NOT NULL"
            " AND record_id IS NULL AND paragraph_id IS NULL AND emotion IS NULL AND genre_label IS NULL"
            " AND topic_id IS NULL AND topic_label IS NULL AND scored_entity_id IS NULL"
            " AND character_score IS NULL AND cast_role IS NULL AND cast_entity_id IS NULL)"
            " OR (report_id IS NOT NULL AND topic_id IS NOT NULL AND topic_label IS NOT NULL"
            " AND record_id IS NULL AND paragraph_id IS NULL AND emotion IS NULL AND ordinal IS NULL"
            " AND genre_label IS NULL AND style_label IS NULL AND scored_entity_id IS NULL"
            " AND character_score IS NULL AND cast_role IS NULL AND cast_entity_id IS NULL)"
            " OR (report_id IS NOT NULL AND scored_entity_id IS NOT NULL AND character_score IS NOT NULL"
            " AND record_id IS NULL AND paragraph_id IS NULL AND emotion IS NULL AND ordinal IS NULL"
            " AND genre_label IS NULL AND style_label IS NULL AND topic_id IS NULL AND topic_label IS NULL"
            " AND cast_role IS NULL AND cast_entity_id IS NULL)"
            " OR (report_id IS NOT NULL AND cast_role IS NOT NULL AND ordinal IS NOT NULL"
            " AND cast_entity_id IS NOT NULL AND record_id IS NULL AND paragraph_id IS NULL AND emotion IS NULL"
            " AND genre_label IS NULL AND style_label IS NULL AND topic_id IS NULL AND topic_label IS NULL"
            " AND scored_entity_id IS NULL AND character_score IS NULL)",
            name="ck_analysis_assessments_shape",
        ),
        CheckConstraint(
            "cast_role IS NULL OR cast_role IN ('focus', 'main', 'core')",
            name="ck_analysis_assessments_cast_role",
        ),
        Index(
            "uq_analysis_assessments_emotion",
            "record_id",
            "paragraph_id",
            unique=True,
            postgresql_where=sql_text("record_id IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_genre_ordinal",
            "report_id",
            "ordinal",
            unique=True,
            postgresql_where=sql_text("genre_label IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_genre_label",
            "report_id",
            "genre_label",
            unique=True,
            postgresql_where=sql_text("genre_label IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_style_ordinal",
            "report_id",
            "ordinal",
            unique=True,
            postgresql_where=sql_text("style_label IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_style_label",
            "report_id",
            "style_label",
            unique=True,
            postgresql_where=sql_text("style_label IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_topic",
            "report_id",
            "topic_id",
            unique=True,
            postgresql_where=sql_text("topic_label IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_score",
            "report_id",
            "scored_entity_id",
            unique=True,
            postgresql_where=sql_text("character_score IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_cast_ordinal",
            "report_id",
            "cast_role",
            "ordinal",
            unique=True,
            postgresql_where=sql_text("cast_entity_id IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_cast_entity",
            "report_id",
            "cast_role",
            "cast_entity_id",
            unique=True,
            postgresql_where=sql_text("cast_entity_id IS NOT NULL"),
        ),
        {"comment": "分析条目表：逐段情绪/题材标签/风格标签/主题命名/人物评分/人物名单六种互斥形状"},
    )

    assessment_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="条目主键（uuid）", default=new_id, autoincrement=False
    )
    record_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("agent_annotations.record_id", ondelete="CASCADE", name="analysis_assessments_record_fkey"),
        nullable=True,
        comment="所属章节标注记录（逐段情绪）",
    )
    report_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("diagnosis_reports.report_id", ondelete="CASCADE", name="analysis_assessments_report_fkey"),
        nullable=True,
        comment="所属诊断报告",
    )
    paragraph_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="段落编号（逐段情绪）")
    emotion: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="段落情绪分值（-2..2）")
    ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="条目序号（0 起）")
    genre_label: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="题材标签")
    style_label: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="风格标签")
    topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="主题 id")
    topic_label: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="主题标签")
    scored_entity_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("graph_entities.entity_id", ondelete="RESTRICT", name="analysis_assessments_score_entity_fkey"),
        nullable=True,
        comment="评分角色实体",
    )
    character_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="人物弧线评分")
    cast_role: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="名单角色（focus/main/core）")
    cast_entity_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("graph_entities.entity_id", ondelete="RESTRICT", name="analysis_assessments_cast_entity_fkey"),
        nullable=True,
        comment="名单角色实体",
    )

    def __repr__(self) -> str:
        return f"<AnalysisAssessment(assessment_id={self.assessment_id})>"
