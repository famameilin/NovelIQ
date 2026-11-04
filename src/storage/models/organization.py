"""事件关系、全书结果与原文证据的 ORM 模型"""

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
#: 伏笔动作类型封闭取值
FORESHADOW_ACTION_TYPES = ("setup", "reinforce", "payoff")


class NarrativeLink(Base):
    "语义关系、事件树成员及整树父子引用"

    __tablename__ = "event_links"
    __table_args__ = (
        CheckConstraint(
            "(semantic_source_event_id IS NOT NULL AND semantic_target_event_id IS NOT NULL"
            " AND relation_type IS NOT NULL AND source_operation_local_key IS NOT NULL"
            " AND tree_id IS NULL AND member_event_id IS NULL AND position IS NULL"
            " AND parent_tree_id IS NULL AND child_tree_id IS NULL)"
            " OR (tree_id IS NOT NULL AND member_event_id IS NOT NULL"
            " AND position IS NOT NULL AND position >= 0"
            " AND parent_tree_id IS NULL AND child_tree_id IS NULL"
            " AND semantic_source_event_id IS NULL AND semantic_target_event_id IS NULL"
            " AND relation_type IS NULL AND source_operation_local_key IS NULL"
            " AND is_active IS NULL AND expired_at IS NULL AND cause_role IS NULL)"
            " OR (parent_tree_id IS NOT NULL AND child_tree_id IS NOT NULL AND parent_tree_id <> child_tree_id"
            " AND tree_id IS NULL AND member_event_id IS NULL AND position IS NULL"
            " AND semantic_source_event_id IS NULL AND semantic_target_event_id IS NULL"
            " AND relation_type IS NULL AND source_operation_local_key IS NULL"
            " AND is_active IS NULL AND expired_at IS NULL AND cause_role IS NULL)",
            name="ck_narrative_links_shape",
        ),
        CheckConstraint(
            "cause_role IS NULL OR cause_role IN ('root', 'main', 'secondary')", name="ck_narrative_links_cause_role"
        ),
        Index(
            "uq_event_member",
            "member_event_id",
            unique=True,
            postgresql_where=sql_text("member_event_id IS NOT NULL"),
        ),
        Index(
            "uq_tree_position",
            "tree_id",
            "position",
            unique=True,
            postgresql_where=sql_text("tree_id IS NOT NULL"),
        ),
        Index(
            "uq_tree_reference",
            "parent_tree_id",
            "child_tree_id",
            unique=True,
            postgresql_where=sql_text("parent_tree_id IS NOT NULL"),
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
        Index("idx_narrative_links_producer", "producer_agent_id"),
        Index("idx_narrative_links_source_event", "semantic_source_event_id"),
        Index("idx_narrative_links_target_event", "semantic_target_event_id"),
    )
    link_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id, autoincrement=False)
    producer_agent_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("agent.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String, nullable=False)
    semantic_source_event_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("event_records.event_id", ondelete="RESTRICT"), nullable=True
    )
    semantic_target_event_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("event_records.event_id", ondelete="RESTRICT"), nullable=True
    )
    relation_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_operation_local_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    annotation_local_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cause_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="树内连续成员顺序")
    tree_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_groups.group_id", ondelete="RESTRICT"),
        nullable=True,
        comment="事件树身份",
    )
    member_event_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_records.event_id", ondelete="RESTRICT"),
        nullable=True,
        comment="树成员事件身份",
    )
    parent_tree_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_groups.group_id", ondelete="RESTRICT"),
        nullable=True,
        comment="父事件树身份",
    )
    child_tree_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_groups.group_id", ondelete="RESTRICT"),
        nullable=True,
        comment="子事件树身份",
    )


class NarrativeGroup(Base):
    "事件树与全书结果节点表"

    __tablename__ = "event_groups"
    __table_args__ = (
        CheckConstraint("kind IN ('tree', 'outcome')", name="ck_narrative_groups_kind"),
        CheckConstraint("kind = 'tree' OR is_event_line = false", name="ck_narrative_groups_event_line"),
        CheckConstraint(
            "line_name IS NULL OR (is_event_line AND char_length(line_name) BETWEEN 2 AND 6 "
            "AND right(line_name, 1) = '线')",
            name="ck_narrative_groups_line_name",
        ),
        Index("idx_narrative_groups_producer", "producer_agent_id"),
        Index(
            "uq_narrative_groups_tree_key",
            "producer_agent_id",
            "tree_key",
            unique=True,
            postgresql_where=sql_text("tree_key IS NOT NULL"),
        ),
        {"comment": "事件树与全书结果节点表：树身份独立于事件，空树合法"},
    )

    group_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        primary_key=True,
        comment="树或结果主键（uuid）",
        default=new_id,
        autoincrement=False,
    )
    producer_agent_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("agent.id", ondelete="RESTRICT", name="narrative_groups_producer_fkey"),
        nullable=False,
        comment="真实生产执行",
    )
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="outcome", comment="节点类型：tree/outcome"
    )
    title: Mapped[str] = mapped_column(String, nullable=False, comment="标题（不唯一，不以标题合并节点）")
    description: Mapped[str] = mapped_column(String, nullable=False, comment="树的说明或结果描述")
    is_event_line: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否选为事件线")
    line_name: Mapped[str | None] = mapped_column(
        String(6), nullable=True, comment="选为事件线时的书内线名，结尾为「线」"
    )
    tree_key: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="生产者内树幂等键")

    def __repr__(self) -> str:
        return f"<NarrativeGroup(group_id={self.group_id}, kind={self.kind}, title={self.title})>"


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
