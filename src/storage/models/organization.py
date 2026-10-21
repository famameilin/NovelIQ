"""
全书叙事组织 ORM 模型

不复制 run/session/work；producer 是该判断的真实作者，不由端点作者替代。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base

#: 因果角色封闭取值（仅真实存在才保存）
CAUSE_ROLES = ("root", "main", "secondary")
#: 叙事线类型封闭取值
ARC_KINDS = ("main", "subplot")
#: 伏笔动作类型封闭取值
FORESHADOW_ACTION_TYPES = ("setup", "reinforce", "payoff")


class NarrativeLink(Base):
    "叙事链路表（四种互斥形状）"

    __tablename__ = "event_links"
    __table_args__ = (
        CheckConstraint(
            "cause_role IS NULL OR cause_role IN ('root', 'main', 'secondary')",
            name="ck_narrative_links_cause_role",
        ),
        CheckConstraint(
            # 语义/因果形状
            "(semantic_source_event_id IS NOT NULL"
            " AND semantic_target_event_id IS NOT NULL"
            " AND relation_type IS NOT NULL AND source_operation_local_key IS NOT NULL"
            " AND contained_child_id IS NULL AND contained_parent_id IS NULL"
            " AND member_event_id IS NULL AND arc_group_id IS NULL AND arc_role IS NULL"
            " AND outcome_group_id IS NULL)"
            " OR (contained_child_id IS NOT NULL AND contained_parent_id IS NOT NULL"
            " AND contained_child_id <> contained_parent_id"
            " AND semantic_source_event_id IS NULL"
            " AND semantic_target_event_id IS NULL"
            " AND relation_type IS NULL AND source_operation_local_key IS NULL"
            " AND member_event_id IS NULL AND arc_group_id IS NULL AND arc_role IS NULL"
            " AND outcome_group_id IS NULL AND is_active IS NULL AND expired_at IS NULL AND cause_role IS NULL)"
            " OR (member_event_id IS NOT NULL AND arc_group_id IS NOT NULL AND arc_role IS NOT NULL"
            " AND semantic_source_event_id IS NULL"
            " AND semantic_target_event_id IS NULL"
            " AND relation_type IS NULL AND source_operation_local_key IS NULL"
            " AND contained_child_id IS NULL AND contained_parent_id IS NULL AND outcome_group_id IS NULL"
            " AND is_active IS NULL AND expired_at IS NULL AND cause_role IS NULL)"
            " OR (member_event_id IS NOT NULL AND outcome_group_id IS NOT NULL"
            " AND semantic_source_event_id IS NULL"
            " AND semantic_target_event_id IS NULL"
            " AND relation_type IS NULL AND source_operation_local_key IS NULL"
            " AND contained_child_id IS NULL AND contained_parent_id IS NULL AND arc_group_id IS NULL"
            " AND arc_role IS NULL AND is_active IS NULL AND expired_at IS NULL AND cause_role IS NULL)",
            name="ck_narrative_links_shape",
        ),
        Index(
            "uq_narrative_links_operation",
            "producer_agent_id",
            "source_operation_local_key",
            unique=True,
            postgresql_where=sql_text("source_operation_local_key IS NOT NULL"),
        ),
        Index(
            "uq_narrative_links_annotation_local",
            "producer_agent_id",
            "annotation_local_key",
            unique=True,
            postgresql_where=sql_text("annotation_local_key IS NOT NULL"),
        ),
        Index(
            "uq_narrative_links_containment",
            "contained_child_id",
            unique=True,
            postgresql_where=sql_text("contained_child_id IS NOT NULL"),
        ),
        Index(
            "uq_narrative_links_arc",
            "member_event_id",
            "arc_group_id",
            unique=True,
            postgresql_where=sql_text("arc_group_id IS NOT NULL"),
        ),
        Index(
            "uq_narrative_links_outcome",
            "member_event_id",
            "outcome_group_id",
            unique=True,
            postgresql_where=sql_text("outcome_group_id IS NOT NULL"),
        ),
        Index("idx_narrative_links_producer", "producer_agent_id"),
        Index("idx_narrative_links_source_event", "semantic_source_event_id"),
        Index("idx_narrative_links_target_event", "semantic_target_event_id"),
        {"comment": "叙事链路表：语义/因果、单父包含、事件—线、事件—结果四种互斥形状"},
    )

    link_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="链路主键（uuid）", default=new_id, autoincrement=False
    )
    producer_agent_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("agent.id", ondelete="RESTRICT", name="narrative_links_producer_fkey"),
        nullable=False,
        comment="该判断的真实作者执行",
    )
    reason: Mapped[str] = mapped_column(String, nullable=False, comment="关联理由")
    semantic_source_event_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_records.event_id", ondelete="RESTRICT", name="narrative_links_source_event_fkey"),
        nullable=True,
        comment="语义关系源端（完整事件，与事件端点恰一）",
    )
    semantic_target_event_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_records.event_id", ondelete="RESTRICT", name="narrative_links_target_event_fkey"),
        nullable=True,
        comment="语义关系目标端（完整事件，与事件端点恰一）",
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
        Uuid(as_uuid=False),
        ForeignKey("event_records.event_id", ondelete="RESTRICT", name="narrative_links_child_fkey"),
        nullable=True,
        comment="包含关系子事件（唯一直接父）",
    )
    contained_parent_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_records.event_id", ondelete="RESTRICT", name="narrative_links_parent_fkey"),
        nullable=True,
        comment="包含关系父事件",
    )
    member_event_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_records.event_id", ondelete="RESTRICT", name="narrative_links_member_event_fkey"),
        nullable=True,
        comment="事件—线/事件—结果关联的事件",
    )
    arc_group_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_groups.group_id", ondelete="RESTRICT", name="narrative_links_arc_group_fkey"),
        nullable=True,
        comment="关联叙事线节点",
    )
    outcome_group_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_groups.group_id", ondelete="RESTRICT", name="narrative_links_outcome_group_fkey"),
        nullable=True,
        comment="关联事件结果节点",
    )
    arc_role: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="该关联在叙事线中的实际角色")

    def __repr__(self) -> str:
        return f"<NarrativeLink(link_id={self.link_id})>"


class NarrativeGroup(Base):
    "全书组织节点表（叙事线 / 事件结果两种互斥形状）"

    __tablename__ = "event_groups"
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
        Index("idx_narrative_groups_producer", "producer_agent_id"),
        {"comment": "组织节点表：叙事线与事件结果两类互斥形状（父线只能指向线，无环）"},
    )

    group_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        primary_key=True,
        comment="节点主键（uuid，原 arc/outcome uuid）",
        default=new_id,
        autoincrement=False,
    )
    producer_agent_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("agent.id", ondelete="RESTRICT", name="narrative_groups_producer_fkey"),
        nullable=False,
        comment="真实生产执行",
    )
    title: Mapped[str] = mapped_column(String, nullable=False, comment="标题（不唯一，不以标题合并节点）")
    arc_kind: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="线类型（main/subplot）")
    arc_objective: Mapped[str | None] = mapped_column(String, nullable=True, comment="叙事线目标")
    arc_role: Mapped[str | None] = mapped_column(String, nullable=True, comment="叙事线作用")
    arc_reason: Mapped[str | None] = mapped_column(String, nullable=True, comment="叙事线判断理由")
    parent_arc_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_groups.group_id", ondelete="RESTRICT", name="narrative_groups_parent_fkey"),
        nullable=True,
        comment="父线（仅线→线，单父无环）",
    )
    outcome_description: Mapped[str | None] = mapped_column(String, nullable=True, comment="结果描述（结果形状）")

    def __repr__(self) -> str:
        return f"<NarrativeGroup(group_id={self.group_id}, title={self.title})>"


class OrganizationCheck(Base):
    "单事件核对与事件结构对判断"

    __tablename__ = "event_checks"
    __table_args__ = (
        CheckConstraint(
            "(reviewed_event_id IS NOT NULL AND snapshot_hash IS NOT NULL AND disposition IS NULL"
            " AND source_event_id IS NULL AND target_event_id IS NULL)"
            " OR (source_event_id IS NOT NULL AND target_event_id IS NOT NULL"
            " AND source_event_id <> target_event_id AND snapshot_hash IS NOT NULL"
            " AND disposition IN ('contains','part_of','related','independent') AND reviewed_event_id IS NULL)",
            name="ck_organization_checks_shape",
        ),
        Index(
            "uq_organization_checks_event",
            "reviewed_event_id",
            unique=True,
            postgresql_where=sql_text("reviewed_event_id IS NOT NULL"),
        ),
        Index(
            "uq_organization_checks_event_pair",
            "source_event_id",
            "target_event_id",
            unique=True,
            postgresql_where=sql_text("source_event_id IS NOT NULL"),
        ),
        Index("idx_organization_checks_producer", "producer_agent_id"),
        {"comment": "组织核对表：单事件核对和事件结构对判断"},
    )

    check_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="核对主键（uuid）", default=new_id, autoincrement=False
    )
    producer_agent_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("agent.id", ondelete="RESTRICT", name="organization_checks_producer_fkey"),
        nullable=False,
        comment="真实生产者执行",
    )
    reason: Mapped[str] = mapped_column(String, nullable=False, comment="核对理由")
    reviewed_event_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_records.event_id", ondelete="CASCADE", name="organization_checks_event_fkey"),
        nullable=True,
        comment="被核对事件（单事件核对）",
    )
    source_event_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_records.event_id", ondelete="RESTRICT", name="organization_checks_source_event_fkey"),
        nullable=True,
        comment="结构对来源事件",
    )
    target_event_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_records.event_id", ondelete="RESTRICT", name="organization_checks_target_event_fkey"),
        nullable=True,
        comment="结构对目标事件",
    )
    snapshot_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="核对快照承诺（源 hash）")
    disposition: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="判断结果")

    def __repr__(self) -> str:
        return f"<OrganizationCheck(check_id={self.check_id})>"


class EventForeshadowingAction(Base):
    "伏笔动作事实：来源事件与目标事件直接引用"

    __tablename__ = "event_foreshadowing_actions"
    __table_args__ = (
        CheckConstraint("action_type IN ('setup', 'reinforce', 'payoff')", name="ck_event_foreshadowing_actions_type"),
        Index(
            "uq_event_foreshadowing_actions_operation",
            "producer_agent_id",
            "source_operation_local_key",
            unique=True,
        ),
        Index("idx_event_foreshadowing_actions_source_annotation_event", "source_event_id"),
        {"comment": "伏笔动作表：setup/reinforce/payoff 动作事实（evidence_scope=paragraph 为生成合同）"},
    )

    action_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="动作主键（uuid）", default=new_id, autoincrement=False
    )
    producer_agent_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("agent.id", ondelete="RESTRICT", name="event_foreshadowing_actions_producer_fkey"),
        nullable=False,
        comment="真实生产执行",
    )
    source_operation_local_key: Mapped[str] = mapped_column(String(128), nullable=False, comment="实际操作身份")
    operation_order: Mapped[int] = mapped_column(Integer, nullable=False, comment="执行内操作顺序")
    action_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="动作类型（setup/reinforce/payoff）")
    source_event_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_records.event_id", ondelete="RESTRICT", name="event_foreshadowing_actions_source_fkey"),
        nullable=False,
        comment="来源事件",
    )
    target_event_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_records.event_id", ondelete="RESTRICT", name="event_foreshadowing_actions_target_fkey"),
        nullable=True,
        comment="目标事件（无目标为空）",
    )

    def __repr__(self) -> str:
        return f"<EventForeshadowingAction(action_id={self.action_id}, type={self.action_type})>"


class SourceEvidence(Base):
    "原文证据表：六类所有者恰一，各所有者内证据序号唯一"

    __tablename__ = "paragraph_evidence"
    __table_args__ = (
        CheckConstraint("start_char < end_char", name="ck_source_evidence_char_order"),
        CheckConstraint(
            "(graph_fact_id IS NOT NULL)::int "
            "+ (complete_event_id IS NOT NULL)::int + (narrative_group_id IS NOT NULL)::int "
            "+ (narrative_link_id IS NOT NULL)::int + (foreshadow_action_id IS NOT NULL)::int "
            "+ (check_id IS NOT NULL)::int = 1",
            name="ck_source_evidence_exactly_one_owner",
        ),
        Index(
            "uq_source_evidence_graph_fact",
            "graph_fact_id",
            "ordinal",
            unique=True,
            postgresql_where=sql_text("graph_fact_id IS NOT NULL"),
        ),
        Index(
            "uq_source_evidence_complete_event",
            "complete_event_id",
            "ordinal",
            unique=True,
            postgresql_where=sql_text("complete_event_id IS NOT NULL"),
        ),
        Index(
            "uq_source_evidence_narrative_group",
            "narrative_group_id",
            "ordinal",
            unique=True,
            postgresql_where=sql_text("narrative_group_id IS NOT NULL"),
        ),
        Index(
            "uq_source_evidence_narrative_link",
            "narrative_link_id",
            "ordinal",
            unique=True,
            postgresql_where=sql_text("narrative_link_id IS NOT NULL"),
        ),
        Index(
            "uq_source_evidence_foreshadow_action",
            "foreshadow_action_id",
            "ordinal",
            unique=True,
            postgresql_where=sql_text("foreshadow_action_id IS NOT NULL"),
        ),
        Index(
            "uq_source_evidence_check",
            "check_id",
            "ordinal",
            unique=True,
            postgresql_where=sql_text("check_id IS NOT NULL"),
        ),
        {"comment": "原文证据表：由明确领域所有者直接持有的有序证据（owner+ordinal 唯一）"},
    )

    evidence_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="证据主键（uuid）", default=new_id, autoincrement=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, comment="所有者内证据序号（0 起）")
    paragraph_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="原文段号（所有者所属 run 内）")
    start_char: Mapped[int] = mapped_column(Integer, nullable=False, comment="段内起始字符偏移")
    end_char: Mapped[int] = mapped_column(Integer, nullable=False, comment="段内结束字符偏移")
    related_complete_event_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_records.event_id", ondelete="RESTRICT", name="source_evidence_related_event_fkey"),
        nullable=True,
        comment="证据的相关完整事件（非第二所有者）",
    )
    graph_fact_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("graph_facts.graph_fact_id", ondelete="CASCADE", name="source_evidence_graph_fact_fkey"),
        nullable=True,
        comment="所有者：图谱事实",
    )
    complete_event_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_records.event_id", ondelete="CASCADE", name="source_evidence_event_fkey"),
        nullable=True,
        comment="所有者：完整事件",
    )
    narrative_group_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_groups.group_id", ondelete="CASCADE", name="source_evidence_group_fkey"),
        nullable=True,
        comment="所有者：叙事组织节点",
    )
    narrative_link_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_links.link_id", ondelete="CASCADE", name="source_evidence_link_fkey"),
        nullable=True,
        comment="所有者：叙事链路",
    )
    foreshadow_action_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_foreshadowing_actions.action_id", ondelete="CASCADE", name="source_evidence_action_fkey"),
        nullable=True,
        comment="所有者：伏笔动作",
    )
    check_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_checks.check_id", ondelete="CASCADE", name="source_evidence_check_fkey"),
        nullable=True,
        comment="所有者：组织核对",
    )

    def __repr__(self) -> str:
        return f"<SourceEvidence(evidence_id={self.evidence_id}, ordinal={self.ordinal})>"
