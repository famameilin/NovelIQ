"""
全书叙事组织 ORM 模型

不复制 run/session/work；producer 是该判断的真实作者，不由端点作者替代。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

#: 因果角色封闭取值（仅真实存在才保存）
CAUSE_ROLES = ("root", "main", "secondary")
#: 叙事线类型封闭取值
ARC_KINDS = ("main", "subplot")
#: 伏笔动作类型封闭取值
FORESHADOW_ACTION_TYPES = ("setup", "reinforce", "payoff")


class NarrativeLink(Base):
    """
    叙事链路表（四种互斥形状）

    - 语义/因果关系：两端各在完整事件/声明 FK 中恰一；relation_type 与
      真实本地操作来源；(producer,source_operation_local_key) 唯一，
      章级本地地址（annotation_local_key）亦按实际来源唯一
    - 单父包含：contained_child_id 唯一直接父（无环、不自含）
    - 事件—叙事线：member_event_id + arc_group_id 自然唯一，arc_role 为该关联实际角色
    - 事件—结果：member_event_id + outcome_group_id 自然唯一

    线关联全部平等；is_active/expired_at 不互相推算，只保存真实观察。
    """

    __tablename__ = "narrative_links"
    __table_args__ = (
        CheckConstraint(
            "cause_role IS NULL OR cause_role IN ('root', 'main', 'secondary')",
            name="ck_narrative_links_cause_role",
        ),
        CheckConstraint(
            # 语义/因果形状
            "((semantic_source_event_id IS NOT NULL)::int + (semantic_source_declaration_id IS NOT NULL)::int = 1"
            " AND (semantic_target_event_id IS NOT NULL)::int + (semantic_target_declaration_id IS NOT NULL)::int = 1"
            " AND relation_type IS NOT NULL AND source_operation_local_key IS NOT NULL"
            " AND contained_child_id IS NULL AND contained_parent_id IS NULL"
            " AND member_event_id IS NULL AND arc_group_id IS NULL AND arc_role IS NULL"
            " AND outcome_group_id IS NULL)"
            " OR (contained_child_id IS NOT NULL AND contained_parent_id IS NOT NULL"
            " AND contained_child_id <> contained_parent_id"
            " AND semantic_source_event_id IS NULL AND semantic_source_declaration_id IS NULL"
            " AND semantic_target_event_id IS NULL AND semantic_target_declaration_id IS NULL"
            " AND relation_type IS NULL AND source_operation_local_key IS NULL"
            " AND member_event_id IS NULL AND arc_group_id IS NULL AND arc_role IS NULL"
            " AND outcome_group_id IS NULL AND is_active IS NULL AND expired_at IS NULL AND cause_role IS NULL)"
            " OR (member_event_id IS NOT NULL AND arc_group_id IS NOT NULL AND arc_role IS NOT NULL"
            " AND semantic_source_event_id IS NULL AND semantic_source_declaration_id IS NULL"
            " AND semantic_target_event_id IS NULL AND semantic_target_declaration_id IS NULL"
            " AND relation_type IS NULL AND source_operation_local_key IS NULL"
            " AND contained_child_id IS NULL AND contained_parent_id IS NULL AND outcome_group_id IS NULL"
            " AND is_active IS NULL AND expired_at IS NULL AND cause_role IS NULL)"
            " OR (member_event_id IS NOT NULL AND outcome_group_id IS NOT NULL"
            " AND semantic_source_event_id IS NULL AND semantic_source_declaration_id IS NULL"
            " AND semantic_target_event_id IS NULL AND semantic_target_declaration_id IS NULL"
            " AND relation_type IS NULL AND source_operation_local_key IS NULL"
            " AND contained_child_id IS NULL AND contained_parent_id IS NULL AND arc_group_id IS NULL"
            " AND arc_role IS NULL AND is_active IS NULL AND expired_at IS NULL AND cause_role IS NULL)",
            name="ck_narrative_links_shape",
        ),
        Index(
            "uq_narrative_links_operation", "producer_execution_id", "source_operation_local_key",
            unique=True, postgresql_where=sql_text("source_operation_local_key IS NOT NULL"),
        ),
        Index(
            "uq_narrative_links_annotation_local", "producer_execution_id", "annotation_local_key",
            unique=True, postgresql_where=sql_text("annotation_local_key IS NOT NULL"),
        ),
        Index(
            "uq_narrative_links_containment", "contained_child_id",
            unique=True, postgresql_where=sql_text("contained_child_id IS NOT NULL"),
        ),
        Index(
            "uq_narrative_links_arc", "member_event_id", "arc_group_id",
            unique=True, postgresql_where=sql_text("arc_group_id IS NOT NULL"),
        ),
        Index(
            "uq_narrative_links_outcome", "member_event_id", "outcome_group_id",
            unique=True, postgresql_where=sql_text("outcome_group_id IS NOT NULL"),
        ),
        Index("idx_narrative_links_producer", "producer_execution_id"),
        Index("idx_narrative_links_source_event", "semantic_source_event_id"),
        Index("idx_narrative_links_target_event", "semantic_target_event_id"),
        {"comment": "叙事链路表：语义/因果、单父包含、事件—线、事件—结果四种互斥形状"},
    )

    link_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="链路主键（uuid）")
    producer_execution_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("executions.execution_id", ondelete="RESTRICT", name="narrative_links_producer_fkey"),
        nullable=False,
        comment="该判断的真实作者执行",
    )
    reason: Mapped[str] = mapped_column(String, nullable=False, comment="关联理由")
    semantic_source_event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("complete_events.event_id", ondelete="RESTRICT", name="narrative_links_source_event_fkey"),
        nullable=True,
        comment="语义关系源端（完整事件，与声明端点恰一）",
    )
    semantic_source_declaration_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "event_declarations.declaration_id",
            ondelete="RESTRICT",
            name="narrative_links_source_declaration_fkey",
        ),
        nullable=True,
        comment="语义关系源端（声明，与事件端点恰一）",
    )
    semantic_target_event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("complete_events.event_id", ondelete="RESTRICT", name="narrative_links_target_event_fkey"),
        nullable=True,
        comment="语义关系目标端（完整事件，与声明端点恰一）",
    )
    semantic_target_declaration_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "event_declarations.declaration_id",
            ondelete="RESTRICT",
            name="narrative_links_target_declaration_fkey",
        ),
        nullable=True,
        comment="语义关系目标端（声明，与事件端点恰一）",
    )
    relation_type: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="语义关系类型码")
    source_operation_local_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="产生该链路的真实本地操作地址"
    )
    annotation_local_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="章级本地地址（标注来源）"
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="真实创建时间")
    is_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True, comment="实际活动状态（承接旧边观察）")
    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="真实到期时间（不由 is_active 推算）"
    )
    cause_role: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="因果角色（root/main/secondary）")
    contained_child_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("complete_events.event_id", ondelete="RESTRICT", name="narrative_links_child_fkey"),
        nullable=True,
        comment="包含关系子事件（唯一直接父）",
    )
    contained_parent_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("complete_events.event_id", ondelete="RESTRICT", name="narrative_links_parent_fkey"),
        nullable=True,
        comment="包含关系父事件",
    )
    member_event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("complete_events.event_id", ondelete="RESTRICT", name="narrative_links_member_event_fkey"),
        nullable=True,
        comment="事件—线/事件—结果关联的事件",
    )
    arc_group_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("narrative_groups.group_id", ondelete="RESTRICT", name="narrative_links_arc_group_fkey"),
        nullable=True,
        comment="关联叙事线节点",
    )
    outcome_group_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("narrative_groups.group_id", ondelete="RESTRICT", name="narrative_links_outcome_group_fkey"),
        nullable=True,
        comment="关联事件结果节点",
    )
    arc_role: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="该关联在叙事线中的实际角色")

    def __repr__(self) -> str:
        return f"<NarrativeLink(link_id={self.link_id})>"


class NarrativeGroup(Base):
    """
    全书组织节点表（叙事线 / 事件结果两种互斥形状）

    - 叙事线必填 arc_kind(main/subplot)、objective、role、reason；结果必填
      outcome_description；未填不相干属性
    - parent_arc_id 自 FK 但仅允许线→线，无环且单父；标题不唯一
    """

    __tablename__ = "narrative_groups"
    __table_args__ = (
        CheckConstraint("arc_kind IS NULL OR arc_kind IN ('main', 'subplot')", name="ck_narrative_groups_arc_kind"),
        CheckConstraint(
            "(arc_kind IS NOT NULL AND arc_objective IS NOT NULL AND arc_role IS NOT NULL"
            " AND arc_reason IS NOT NULL AND outcome_description IS NULL)"
            " OR (arc_kind IS NULL AND arc_objective IS NULL AND arc_role IS NULL"
            " AND arc_reason IS NULL AND outcome_description IS NOT NULL)",
            name="ck_narrative_groups_shape",
        ),
        CheckConstraint("parent_arc_id IS NULL OR parent_arc_id <> group_id", name="ck_narrative_groups_self_parent"),
        Index("idx_narrative_groups_producer", "producer_execution_id"),
        {"comment": "组织节点表：叙事线与事件结果两类互斥形状（父线只能指向线，无环）"},
    )

    group_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="节点主键（uuid，原 arc/outcome uuid）")
    producer_execution_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("executions.execution_id", ondelete="RESTRICT", name="narrative_groups_producer_fkey"),
        nullable=False,
        comment="真实生产执行",
    )
    title: Mapped[str] = mapped_column(String, nullable=False, comment="标题（不唯一，不以标题合并节点）")
    arc_kind: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="线类型（main/subplot）")
    arc_objective: Mapped[str | None] = mapped_column(String, nullable=True, comment="叙事线目标")
    arc_role: Mapped[str | None] = mapped_column(String, nullable=True, comment="叙事线作用")
    arc_reason: Mapped[str | None] = mapped_column(String, nullable=True, comment="叙事线判断理由")
    parent_arc_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("narrative_groups.group_id", ondelete="RESTRICT", name="narrative_groups_parent_fkey"),
        nullable=True,
        comment="父线（仅线→线，单父无环）",
    )
    outcome_description: Mapped[str | None] = mapped_column(String, nullable=True, comment="结果描述（结果形状）")

    def __repr__(self) -> str:
        return f"<NarrativeGroup(group_id={self.group_id}, title={self.title})>"


class OrganizationCheck(Base):
    """
    组织核对表（四类互斥形状）

    - 单事件核对：reviewed_event_id 唯一；事件+邻接包含/关系的 snapshot_hash
    - 单声明核对：reviewed_declaration_id 唯一；声明+提案+动作的源 hash
    - 声明对比较：(source_declaration_id,target_declaration_id) 唯一；保持原最早锚点定向
    - 结构对核对：(source_event_id,target_event_id) 唯一；无序对不得反向重复（触发器校验）
    """

    __tablename__ = "organization_checks"
    __table_args__ = (
        CheckConstraint(
            "(reviewed_event_id IS NOT NULL AND snapshot_hash IS NOT NULL AND disposition IS NULL"
            " AND reviewed_declaration_id IS NULL AND source_declaration_id IS NULL AND target_declaration_id IS NULL"
            " AND source_event_id IS NULL AND target_event_id IS NULL)"
            " OR (reviewed_declaration_id IS NOT NULL AND snapshot_hash IS NOT NULL AND disposition IS NULL"
            " AND reviewed_event_id IS NULL AND source_declaration_id IS NULL AND target_declaration_id IS NULL"
            " AND source_event_id IS NULL AND target_event_id IS NULL)"
            " OR (source_declaration_id IS NOT NULL AND target_declaration_id IS NOT NULL"
            " AND disposition IS NOT NULL AND snapshot_hash IS NULL"
            " AND reviewed_event_id IS NULL AND reviewed_declaration_id IS NULL"
            " AND source_event_id IS NULL AND target_event_id IS NULL)"
            " OR (source_event_id IS NOT NULL AND target_event_id IS NOT NULL"
            " AND snapshot_hash IS NOT NULL AND disposition IS NOT NULL"
            " AND reviewed_event_id IS NULL AND reviewed_declaration_id IS NULL"
            " AND source_declaration_id IS NULL AND target_declaration_id IS NULL)",
            name="ck_organization_checks_shape",
        ),
        Index(
            "uq_organization_checks_event", "reviewed_event_id",
            unique=True, postgresql_where=sql_text("reviewed_event_id IS NOT NULL"),
        ),
        Index(
            "uq_organization_checks_declaration", "reviewed_declaration_id",
            unique=True, postgresql_where=sql_text("reviewed_declaration_id IS NOT NULL"),
        ),
        Index(
            "uq_organization_checks_declaration_pair", "source_declaration_id", "target_declaration_id",
            unique=True, postgresql_where=sql_text("source_declaration_id IS NOT NULL"),
        ),
        Index(
            "uq_organization_checks_event_pair", "source_event_id", "target_event_id",
            unique=True, postgresql_where=sql_text("source_event_id IS NOT NULL"),
        ),
        Index("idx_organization_checks_producer", "producer_execution_id"),
        {"comment": "组织核对表：单事件/单声明核对与声明对/结构对判断四类互斥形状"},
    )

    check_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="核对主键（uuid）")
    producer_execution_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("executions.execution_id", ondelete="RESTRICT", name="organization_checks_producer_fkey"),
        nullable=False,
        comment="真实生产者执行",
    )
    reason: Mapped[str] = mapped_column(String, nullable=False, comment="核对理由")
    reviewed_event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("complete_events.event_id", ondelete="CASCADE", name="organization_checks_event_fkey"),
        nullable=True,
        comment="被核对事件（单事件核对）",
    )
    reviewed_declaration_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "event_declarations.declaration_id",
            ondelete="CASCADE",
            name="organization_checks_declaration_fkey",
        ),
        nullable=True,
        comment="被核对声明（单声明核对）",
    )
    source_declaration_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "event_declarations.declaration_id",
            ondelete="RESTRICT",
            name="organization_checks_source_declaration_fkey",
        ),
        nullable=True,
        comment="声明对来源（保持原最早锚点定向）",
    )
    target_declaration_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "event_declarations.declaration_id",
            ondelete="RESTRICT",
            name="organization_checks_target_declaration_fkey",
        ),
        nullable=True,
        comment="声明对目标",
    )
    source_event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("complete_events.event_id", ondelete="RESTRICT", name="organization_checks_source_event_fkey"),
        nullable=True,
        comment="结构对来源事件",
    )
    target_event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("complete_events.event_id", ondelete="RESTRICT", name="organization_checks_target_event_fkey"),
        nullable=True,
        comment="结构对目标事件",
    )
    snapshot_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="核对快照承诺（源 hash）")
    disposition: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="判断结果")

    def __repr__(self) -> str:
        return f"<OrganizationCheck(check_id={self.check_id})>"


class ConflictRecord(Base):
    """冲突登记表：真实生产者与理由，三个主体 FK 恰一（fact 为 BIGINT，不塞伪多态列）"""

    __tablename__ = "conflict_records"
    __table_args__ = (
        CheckConstraint(
            "(subject_event_id IS NOT NULL)::int + (subject_declaration_id IS NOT NULL)::int "
            "+ (subject_fact_id IS NOT NULL)::int = 1",
            name="ck_conflict_records_exactly_one_subject",
        ),
        Index("idx_conflict_records_producer", "producer_execution_id"),
        {"comment": "冲突记录表：原文冲突登记及具体主体（resolution 恒 unresolved 按存在性投影）"},
    )

    conflict_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="冲突主键（uuid）")
    producer_execution_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("executions.execution_id", ondelete="RESTRICT", name="conflict_records_producer_fkey"),
        nullable=False,
        comment="真实登记执行",
    )
    reason: Mapped[str] = mapped_column(String, nullable=False, comment="冲突理由")
    subject_event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("complete_events.event_id", ondelete="RESTRICT", name="conflict_records_event_fkey"),
        nullable=True,
        comment="主体完整事件",
    )
    subject_declaration_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("event_declarations.declaration_id", ondelete="RESTRICT", name="conflict_records_declaration_fkey"),
        nullable=True,
        comment="主体章级声明",
    )
    subject_fact_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("graph_facts.graph_fact_id", ondelete="RESTRICT", name="conflict_records_fact_fkey"),
        nullable=True,
        comment="主体图谱事实（BIGINT 流水）",
    )

    def __repr__(self) -> str:
        return f"<ConflictRecord(conflict_id={self.conflict_id})>"


class ConflictClaim(Base):
    """冲突各方独立陈述：每条自己的真实生产者与证据（至少两条由触发器校验）"""

    __tablename__ = "conflict_claims"
    __table_args__ = (
        Index("uq_conflict_claims_ordinal", "conflict_id", "claim_ordinal", unique=True),
        {"comment": "冲突陈述表：各条相反陈述及各自来源"},
    )

    claim_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="陈述主键（uuid）")
    conflict_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conflict_records.conflict_id", ondelete="CASCADE", name="conflict_claims_conflict_fkey"),
        nullable=False,
        comment="所属冲突",
    )
    claim_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, comment="陈述序号（0 起）")
    producer_execution_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("executions.execution_id", ondelete="RESTRICT", name="conflict_claims_producer_fkey"),
        nullable=False,
        comment="该陈述的真实来源执行（不默认等于冲突登记者）",
    )
    claim_text: Mapped[str] = mapped_column(String, nullable=False, comment="陈述内容")

    def __repr__(self) -> str:
        return f"<ConflictClaim(claim_id={self.claim_id}, conflict_id={self.conflict_id})>"


class EventForeshadowingAction(Base):
    """伏笔动作事实：来源/目标声明真实 FK（root/target 完整事件按绑定投影，不复制）"""

    __tablename__ = "event_foreshadowing_actions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('setup', 'reinforce', 'payoff')", name="ck_event_foreshadowing_actions_type"
        ),
        Index(
            "uq_event_foreshadowing_actions_operation",
            "producer_execution_id",
            "source_operation_local_key",
            unique=True,
        ),
        Index("idx_event_foreshadowing_actions_source_declaration", "source_declaration_id"),
        {"comment": "伏笔动作表：setup/reinforce/payoff 动作事实（evidence_scope=paragraph 为生成合同）"},
    )

    action_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="动作主键（uuid）")
    producer_execution_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("executions.execution_id", ondelete="RESTRICT", name="event_foreshadowing_actions_producer_fkey"),
        nullable=False,
        comment="真实生产执行",
    )
    source_operation_local_key: Mapped[str] = mapped_column(String(128), nullable=False, comment="实际操作身份")
    operation_order: Mapped[int] = mapped_column(Integer, nullable=False, comment="执行内操作顺序")
    action_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="动作类型（setup/reinforce/payoff）")
    source_declaration_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "event_declarations.declaration_id",
            ondelete="RESTRICT",
            name="event_foreshadowing_actions_source_fkey",
        ),
        nullable=False,
        comment="来源声明",
    )
    target_declaration_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "event_declarations.declaration_id",
            ondelete="RESTRICT",
            name="event_foreshadowing_actions_target_fkey",
        ),
        nullable=True,
        comment="目标声明（无目标为空）",
    )

    def __repr__(self) -> str:
        return f"<EventForeshadowingAction(action_id={self.action_id}, type={self.action_type})>"


class SourceEvidence(Base):
    """
    原文证据表（九个所有者恰一；每个所有者分支 (owner,ordinal) 唯一）

    quote、hash、chapter 和全文坐标从正式原文/定位计算，不双存；
    同一原文被两个判断引用时各自一条成员，保留顺序，不合并业务依据。
    """

    __tablename__ = "source_evidence"
    __table_args__ = (
        CheckConstraint("start_char < end_char", name="ck_source_evidence_char_order"),
        CheckConstraint(
            "(graph_fact_id IS NOT NULL)::int + (declaration_id IS NOT NULL)::int "
            "+ (complete_event_id IS NOT NULL)::int + (narrative_group_id IS NOT NULL)::int "
            "+ (narrative_link_id IS NOT NULL)::int + (foreshadow_action_id IS NOT NULL)::int "
            "+ (conflict_id IS NOT NULL)::int + (claim_id IS NOT NULL)::int "
            "+ (check_id IS NOT NULL)::int = 1",
            name="ck_source_evidence_exactly_one_owner",
        ),
        Index(
            "uq_source_evidence_graph_fact", "graph_fact_id", "ordinal",
            unique=True, postgresql_where=sql_text("graph_fact_id IS NOT NULL"),
        ),
        Index(
            "uq_source_evidence_declaration", "declaration_id", "ordinal",
            unique=True, postgresql_where=sql_text("declaration_id IS NOT NULL"),
        ),
        Index(
            "uq_source_evidence_complete_event", "complete_event_id", "ordinal",
            unique=True, postgresql_where=sql_text("complete_event_id IS NOT NULL"),
        ),
        Index(
            "uq_source_evidence_narrative_group", "narrative_group_id", "ordinal",
            unique=True, postgresql_where=sql_text("narrative_group_id IS NOT NULL"),
        ),
        Index(
            "uq_source_evidence_narrative_link", "narrative_link_id", "ordinal",
            unique=True, postgresql_where=sql_text("narrative_link_id IS NOT NULL"),
        ),
        Index(
            "uq_source_evidence_foreshadow_action", "foreshadow_action_id", "ordinal",
            unique=True, postgresql_where=sql_text("foreshadow_action_id IS NOT NULL"),
        ),
        Index(
            "uq_source_evidence_conflict", "conflict_id", "ordinal",
            unique=True, postgresql_where=sql_text("conflict_id IS NOT NULL"),
        ),
        Index(
            "uq_source_evidence_claim", "claim_id", "ordinal",
            unique=True, postgresql_where=sql_text("claim_id IS NOT NULL"),
        ),
        Index(
            "uq_source_evidence_check", "check_id", "ordinal",
            unique=True, postgresql_where=sql_text("check_id IS NOT NULL"),
        ),
        {"comment": "原文证据表：由明确领域所有者直接持有的有序证据（owner+ordinal 唯一）"},
    )

    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="证据主键（uuid）")
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, comment="所有者内证据序号（0 起）")
    paragraph_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="原文段号（所有者所属 run 内）")
    start_char: Mapped[int] = mapped_column(Integer, nullable=False, comment="段内起始字符偏移")
    end_char: Mapped[int] = mapped_column(Integer, nullable=False, comment="段内结束字符偏移")
    related_complete_event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("complete_events.event_id", ondelete="RESTRICT", name="source_evidence_related_event_fkey"),
        nullable=True,
        comment="证据的相关完整事件（非第二所有者）",
    )
    graph_fact_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("graph_facts.graph_fact_id", ondelete="CASCADE", name="source_evidence_graph_fact_fkey"),
        nullable=True,
        comment="所有者：图谱事实",
    )
    declaration_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("event_declarations.declaration_id", ondelete="CASCADE", name="source_evidence_declaration_fkey"),
        nullable=True,
        comment="所有者：章级声明",
    )
    complete_event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("complete_events.event_id", ondelete="CASCADE", name="source_evidence_event_fkey"),
        nullable=True,
        comment="所有者：完整事件",
    )
    narrative_group_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("narrative_groups.group_id", ondelete="CASCADE", name="source_evidence_group_fkey"),
        nullable=True,
        comment="所有者：叙事组织节点",
    )
    narrative_link_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("narrative_links.link_id", ondelete="CASCADE", name="source_evidence_link_fkey"),
        nullable=True,
        comment="所有者：叙事链路",
    )
    foreshadow_action_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("event_foreshadowing_actions.action_id", ondelete="CASCADE", name="source_evidence_action_fkey"),
        nullable=True,
        comment="所有者：伏笔动作",
    )
    conflict_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("conflict_records.conflict_id", ondelete="CASCADE", name="source_evidence_conflict_fkey"),
        nullable=True,
        comment="所有者：冲突登记",
    )
    claim_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("conflict_claims.claim_id", ondelete="CASCADE", name="source_evidence_claim_fkey"),
        nullable=True,
        comment="所有者：冲突陈述",
    )
    check_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("organization_checks.check_id", ondelete="CASCADE", name="source_evidence_check_fkey"),
        nullable=True,
        comment="所有者：组织核对",
    )

    def __repr__(self) -> str:
        return f"<SourceEvidence(evidence_id={self.evidence_id}, ordinal={self.ordinal})>"
