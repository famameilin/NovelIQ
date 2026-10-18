"""
工作、执行与正式产物 ORM 模型

推导项不落列：novel/run 从 session 取，逐段情绪的 run/chapter 从 record 取，
名单顺序与去重由条件唯一约束保证。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, naive_utcnow

#: 执行角色封闭取值（章内四个标注角色 + 诊断两个角色）
EXECUTION_ROLES = ("annotation", "entity", "event", "metric", "case", "report")
#: 章内标注角色封闭取值（executions.chapter_id 必填；chapter_annotations.role 取值域）
ANNOTATION_ROLES = ("annotation", "entity", "event", "metric")
#: 诊断角色封闭取值（案例办理与报告收尾）
DIAGNOSIS_ROLES = ("case", "report")
#: 执行状态封闭取值
EXECUTION_STATUSES = ("running", "success", "error", "interrupted")
#: 诊断重点结构封闭取值
FOCUS_STRUCTURES = ("single", "dual", "ensemble")
#: 人物名单角色封闭取值（三份名单独立有序，不双存主角布尔）
CAST_ROLES = ("focus", "main", "core")


class WorkItem(Base):
    """
    工作业务身份表（程序回执两种互斥形状）

    - 章末核对程序：program_run/chapter、program_code、program_invocation_key 为实际程序身份
    - 诊断失败保留程序：diagnosis_session、program_code 必填

    本表只承载两类程序的真实回执身份。
    """

    __tablename__ = "work_items"
    __table_args__ = (
        CheckConstraint(
            "(annotation_run_id IS NULL AND annotation_chapter_id IS NULL AND role IS NULL"
            " AND diagnosis_session_id IS NULL AND program_run_id IS NOT NULL AND program_chapter_id IS NOT NULL"
            " AND program_code IS NOT NULL AND program_invocation_key IS NOT NULL)"
            " OR (annotation_run_id IS NULL AND annotation_chapter_id IS NULL AND role IS NULL"
            " AND diagnosis_session_id IS NOT NULL AND program_run_id IS NULL AND program_chapter_id IS NULL"
            " AND program_code IS NOT NULL AND program_invocation_key IS NULL)",
            name="ck_work_items_shape",
        ),
        ForeignKeyConstraint(
            ["annotation_run_id", "annotation_chapter_id"],
            ["chapters.run_id", "chapters.chapter_id"],
            ondelete="CASCADE",
            name="work_items_annotation_chapter_fkey",
        ),
        ForeignKeyConstraint(
            ["program_run_id", "program_chapter_id"],
            ["chapters.run_id", "chapters.chapter_id"],
            ondelete="CASCADE",
            name="work_items_program_chapter_fkey",
        ),
        ForeignKeyConstraint(
            ["annotation_run_id"], ["analysis_runs.run_id"], ondelete="CASCADE", name="work_items_annotation_run_fkey"
        ),
        ForeignKeyConstraint(
            ["program_run_id"], ["analysis_runs.run_id"], ondelete="CASCADE", name="work_items_program_run_fkey"
        ),
        Index(
            "uq_work_items_program_invocation_key", "program_invocation_key",
            unique=True, postgresql_where=sql_text("program_invocation_key IS NOT NULL"),
        ),
        Index(
            "uq_work_items_diagnosis_failure", "diagnosis_session_id",
            unique=True,
            postgresql_where=sql_text("diagnosis_session_id IS NOT NULL AND program_code IS NOT NULL"),
        ),
        {"comment": "工作表：两类程序回执的业务身份（章末核对/诊断失败保留，两种互斥形状）"},
    )

    work_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="工作主键（uuid）")
    role: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="退场列：agent work 已删，程序回执形状恒为空"
    )
    annotation_run_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, comment="退场列：agent work 已删，程序回执形状恒为空"
    )
    annotation_chapter_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="退场列：agent work 已删，程序回执形状恒为空"
    )
    diagnosis_session_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey(
            "executions.execution_id",
            ondelete="RESTRICT",
            name="work_items_diagnosis_session_fkey",
            use_alter=True,
        ),
        nullable=True,
        comment="所属诊断整轮会话（executions 的 session 形状）",
    )
    program_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, comment="程序所属运行")
    program_chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="程序所属章节编号")
    program_code: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="程序代码（章末核对/诊断失败保留）"
    )
    program_invocation_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="程序来源摘要身份（chapter:{chapter}:{digest}）"
    )

    def __repr__(self) -> str:
        return f"<WorkItem(work_id={self.work_id}, role={self.role})>"


class Execution(Base):
    """
    执行表（真实 session 与真实 invocation 两类互斥形状）

    - 整轮 session：session_run_id、session_created_at 必填，尝试观测全空
    - 真实 invocation：run_id/role/attempt_number/started_at/status 必填；
      标注角色（annotation/entity/event/metric）必带 chapter_id；
      案例角色（case）章为空、案例锚可空（会话级执行不绑定单案例）；
      报告角色（report）两者为空。
      尝试唯一性按两支条件唯一：(run, 章, 角色, 尝试) 与 (run, 案例, 角色, 尝试)。

    run 直接落在执行行上；session 不冒充尝试，模型调用只能引用 invocation。
    """

    __tablename__ = "executions"
    __table_args__ = (
        CheckConstraint(
            "status IS NULL OR status IN ('running', 'success', 'error', 'interrupted')",
            name="ck_executions_status",
        ),
        CheckConstraint(
            "role IS NULL OR role IN ('annotation', 'entity', 'event', 'metric', 'case', 'report')",
            name="ck_executions_role",
        ),
        CheckConstraint(
            "(session_run_id IS NOT NULL AND session_created_at IS NOT NULL"
            " AND run_id IS NULL AND role IS NULL AND chapter_id IS NULL AND case_anchor IS NULL"
            " AND work_id IS NULL AND attempt_number IS NULL AND started_at IS NULL"
            " AND finished_at IS NULL AND status IS NULL AND error IS NULL)"
            " OR (session_run_id IS NULL AND session_created_at IS NULL AND run_id IS NOT NULL"
            " AND role IS NOT NULL AND work_id IS NULL AND attempt_number IS NOT NULL"
            " AND started_at IS NOT NULL AND status IS NOT NULL"
            " AND ((role IN ('annotation', 'entity', 'event', 'metric')"
            " AND chapter_id IS NOT NULL AND case_anchor IS NULL)"
            " OR (role = 'case' AND chapter_id IS NULL)"
            " OR (role = 'report' AND chapter_id IS NULL AND case_anchor IS NULL)))",
            name="ck_executions_shape",
        ),
        ForeignKeyConstraint(
            ["session_run_id"], ["analysis_runs.run_id"], ondelete="CASCADE", name="executions_session_run_fkey"
        ),
        ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE", name="executions_run_fkey"),
        Index(
            "uq_executions_annotation_attempt", "run_id", "chapter_id", "role", "attempt_number",
            unique=True, postgresql_where=sql_text("chapter_id IS NOT NULL"),
        ),
        Index(
            "uq_executions_case_attempt", "run_id", "case_anchor", "role", "attempt_number",
            unique=True, postgresql_where=sql_text("case_anchor IS NOT NULL"),
        ),
        {"comment": "执行表：真实整轮 session（诊断轮次）与真实 invocation 两类互斥形状（run 直接落行）"},
    )

    execution_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="执行主键（session/invocation id）")
    session_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, comment="整轮会话所属运行")
    session_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="整轮会话创建时间")
    run_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, comment="真实执行所属运行（invocation 形状必填）"
    )
    role: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="执行角色（annotation/entity/event/metric/case/report）"
    )
    chapter_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="章内标注执行的章节编号（标注角色必填）"
    )
    case_anchor: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="案例办理锚（事件案例 id；案例角色必填）"
    )
    work_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("work_items.work_id", ondelete="CASCADE", name="executions_work_fkey"),
        nullable=True,
        comment="退场列：新执行不再登记 work（领域约束规则 1 仍读取本列）",
    )
    attempt_number: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="第几次尝试（1 起）")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="结束时间")
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="执行终态")
    error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="执行失败信息")

    def __repr__(self) -> str:
        return f"<Execution(execution_id={self.execution_id}, status={self.status})>"


class ChapterAnnotation(Base):
    """
    正式章节标注记录表

    execution_id 唯一（每 execution 至多一份产物）；归属列 run/章/角色直接落行，
    读投影不依赖审计表与 work；「每章每角色至多一个正式成功记录」等价校验
    由工具层写入承担（角色值域 annotation/entity/event/metric）。
    summary、-2..2 情绪、叙事功能、pivot、cliffhanger 都是独立提交；
    saved_at 是五组件成功事务的真实回执，失败不造记录。
    """

    __tablename__ = "chapter_annotations"
    __table_args__ = (
        CheckConstraint(
            "emotional_valence IN (-2, -1, 0, 1, 2)", name="ck_chapter_annotations_valence"
        ),
        CheckConstraint(
            "role IN ('annotation', 'entity', 'event', 'metric')", name="ck_chapter_annotations_role"
        ),
        ForeignKeyConstraint(
            ["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE", name="chapter_annotations_run_fkey"
        ),
        ForeignKeyConstraint(
            ["run_id", "chapter_id"],
            ["chapters.run_id", "chapters.chapter_id"],
            ondelete="CASCADE",
            name="chapter_annotations_chapter_fkey",
        ),
        {"comment": "章节标注表：正式产物头与归属（run/章/角色），成功保存事实（每 execution 至多一份）"},
    )

    record_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="产物主键（原 output uuid）")
    execution_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("executions.execution_id", ondelete="RESTRICT", name="chapter_annotations_execution_fkey"),
        nullable=False,
        unique=True,
        comment="产生产物的真实执行",
    )
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="产出所属运行")
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="产出所属章节编号")
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="产出角色（annotation/entity/event/metric）"
    )
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False, comment="标注合同版本")
    chapter_consolidation_version: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="章末核对规则版本"
    )
    # 具名指标独立提交：实体/事件角色执行没有章级指标时各列为空
    summary: Mapped[str | None] = mapped_column(String, nullable=True, comment="章节摘要")
    emotional_valence: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="情绪效价（-2..2）")
    narrative_function: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="叙事功能")
    pivot_moment: Mapped[bool | None] = mapped_column(nullable=True, comment="是否含关键转折")
    cliffhanger: Mapped[bool | None] = mapped_column(nullable=True, comment="是否悬念收尾")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )
    saved_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="五组件成功事务落库时间"
    )

    def __repr__(self) -> str:
        return f"<ChapterAnnotation(record_id={self.record_id})>"


class DiagnosisReport(Base):
    """
    正式全书诊断表

    一个运行的正式发布唯一性由领域约束触发器校验（不靠列形状表达）；
    快照为真实冻结承诺，标签/名单/评分分别进入 analysis_assessments。
    """

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

    report_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="报告主键（原 output uuid）")
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("executions.execution_id", ondelete="RESTRICT", name="diagnosis_reports_session_fkey"),
        nullable=False,
        unique=True,
        comment="所属诊断整轮会话（executions 的 session 形状）",
    )
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False, comment="诊断合同版本")
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )

    def __repr__(self) -> str:
        return f"<DiagnosisReport(report_id={self.report_id})>"


class AnalysisAssessment(Base):
    """
    分析条目表（六类有限条目，恰一形状）

    - 逐段情绪：record_id、paragraph_id、emotion
    - 题材标签：report_id、ordinal、genre_label
    - 风格标签：report_id、ordinal、style_label
    - 主题命名：report_id、topic_id、topic_label
    - 人物评分：report_id、scored_entity_id、character_score
    - 人物名单：report_id、cast_role、ordinal、cast_entity_id

    每个分支的条件唯一性决定该分支整行；不存能从形状决定的泛型 kind/value。
    """

    __tablename__ = "analysis_assessments"
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
            "uq_analysis_assessments_emotion", "record_id", "paragraph_id",
            unique=True, postgresql_where=sql_text("record_id IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_genre_ordinal", "report_id", "ordinal",
            unique=True, postgresql_where=sql_text("genre_label IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_genre_label", "report_id", "genre_label",
            unique=True, postgresql_where=sql_text("genre_label IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_style_ordinal", "report_id", "ordinal",
            unique=True, postgresql_where=sql_text("style_label IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_style_label", "report_id", "style_label",
            unique=True, postgresql_where=sql_text("style_label IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_topic", "report_id", "topic_id",
            unique=True, postgresql_where=sql_text("topic_label IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_score", "report_id", "scored_entity_id",
            unique=True, postgresql_where=sql_text("character_score IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_cast_ordinal", "report_id", "cast_role", "ordinal",
            unique=True, postgresql_where=sql_text("cast_entity_id IS NOT NULL"),
        ),
        Index(
            "uq_analysis_assessments_cast_entity", "report_id", "cast_role", "cast_entity_id",
            unique=True, postgresql_where=sql_text("cast_entity_id IS NOT NULL"),
        ),
        {"comment": "分析条目表：逐段情绪/题材标签/风格标签/主题命名/人物评分/人物名单六种互斥形状"},
    )

    assessment_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="条目主键（uuid）")
    record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chapter_annotations.record_id", ondelete="CASCADE", name="analysis_assessments_record_fkey"),
        nullable=True,
        comment="所属章节标注记录（逐段情绪）",
    )
    report_id: Mapped[str | None] = mapped_column(
        String(36),
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
        String(36),
        ForeignKey("graph_entities.entity_id", ondelete="RESTRICT", name="analysis_assessments_score_entity_fkey"),
        nullable=True,
        comment="评分角色实体",
    )
    character_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="人物弧线评分")
    cast_role: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="名单角色（focus/main/core）")
    cast_entity_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("graph_entities.entity_id", ondelete="RESTRICT", name="analysis_assessments_cast_entity_fkey"),
        nullable=True,
        comment="名单角色实体",
    )

    def __repr__(self) -> str:
        return f"<AnalysisAssessment(assessment_id={self.assessment_id})>"
