"""
事实图谱 ORM 模型

operation kind 由具体列形状表达，不存由引用决定的重复 operation_code；
graph 与 plotline 两个列表都从 0 开始，不能用 producer+order 作全表键。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base, naive_utcnow

#: 实体类型封闭取值
ENTITY_TYPES = ("character", "location", "item", "organization")
#: 字段操作三态封闭取值（omit 表示未提交，不落列值）
FIELD_ACTIONS = ("omit", "set", "clear")


class GraphEntity(Base):
    "图实体表：run 内稳定实体身份（UUIDv7 独立主键，按 run+规范名+大类保持业务唯一）"

    __tablename__ = "graph_entities"
    __table_args__ = (
        UniqueConstraint("run_id", "canonical_name", "entity_type", name="uq_graph_entities_run_name_type"),
        Index("idx_graph_entities_run_canonical", "run_id", "canonical_name"),
        Index("idx_graph_entities_run_type", "run_id", "entity_type"),
        {"comment": "图实体表：run 内稳定实体身份（名称比较须与 NFC/strip/casefold 身份规则一致）"},
    )

    entity_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="实体主键（uuid）", default=new_id, autoincrement=False
    )
    run_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        comment="所属分析运行",
    )
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="实体规范名")
    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="实体类型（character/location/item/organization）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, onupdate=naive_utcnow, comment="更新时间"
    )


class GraphRelation(Base):
    "图关系表：稳定关系身份及真实端点；run 从端点取得（两端必须同 run）"

    __tablename__ = "graph_relations"
    __table_args__ = (
        UniqueConstraint("from_entity_id", "to_entity_id", "relation_type", name="uq_graph_relations_endpoints_type"),
        CheckConstraint("from_entity_id <> to_entity_id", name="ck_graph_relations_distinct_endpoints"),
        Index("idx_graph_relations_from", "from_entity_id"),
        Index("idx_graph_relations_to", "to_entity_id"),
        {"comment": "图关系表：稳定关系身份及实体端点（类型决定方向与语义，不逐行保存）"},
    )

    relation_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="关系主键（uuid）", default=new_id, autoincrement=False
    )
    from_entity_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("graph_entities.entity_id", ondelete="CASCADE"),
        nullable=False,
        comment="起点实体",
    )
    to_entity_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("graph_entities.entity_id", ondelete="CASCADE"),
        nullable=False,
        comment="终点实体",
    )
    relation_type: Mapped[str] = mapped_column(String(100), nullable=False, comment="关系类型（版本化关系合同）")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow, comment="创建时间")


class GraphFact(Base):
    "图事实表（五种互斥形状）"

    __tablename__ = "graph_facts"
    __table_args__ = (
        CheckConstraint(
            "description_action IS NULL OR description_action IN ('omit', 'set', 'clear')",
            name="ck_graph_facts_description_action",
        ),
        CheckConstraint(
            "representative_action IS NULL OR representative_action IN ('omit', 'set', 'clear')",
            name="ck_graph_facts_representative_action",
        ),
        CheckConstraint(
            # 未提交（action 与值同空）或「set 当且仅当有值」
            "(description_action IS NULL AND description_value IS NULL)"
            " OR ((description_action = 'set') IS NOT DISTINCT FROM (description_value IS NOT NULL))",
            name="ck_graph_facts_description_value_pair",
        ),
        CheckConstraint(
            "(representative_action IS NULL AND representative_value IS NULL)"
            " OR ((representative_action = 'set') IS NOT DISTINCT FROM (representative_value IS NOT NULL))",
            name="ck_graph_facts_representative_value_pair",
        ),
        CheckConstraint(
            # 关系变化的取值就是写面合同的七类（不把 break 归一为 retract：
            # 旧读面对断裂与撤回各有展示标签，值原样入事实行）
            "relation_change_kind IS NULL OR relation_change_kind IN"
            " ('assert', 'reinforce', 'weaken', 'retract', 'refine', 'supersede', 'break')",
            name="ck_graph_facts_relation_change_kind",
        ),
        CheckConstraint(
            "identity_kind IS NULL OR identity_kind IN ('same', 'different')",
            name="ck_graph_facts_identity_kind",
        ),
        CheckConstraint(
            # 实体引用/更新形状
            "(direct_producer_execution_id IS NOT NULL AND entity_id IS NOT NULL AND operation_order IS NOT NULL"
            " AND relation_id IS NULL AND participant_id IS NULL AND program_work_id IS NULL"
            " AND business_call_id IS NULL AND declaration_id IS NULL"
            " AND plotline_subject_id IS NULL AND plotline_subject_title IS NULL"
            " AND plotline_description IS NULL AND plotline_before IS NULL AND plotline_after IS NULL"
            " AND relation_change_kind IS NULL AND identity_kind IS NULL AND reason IS NULL)"
            # 实体关系操作形状
            " OR (direct_producer_execution_id IS NOT NULL AND relation_id IS NOT NULL"
            " AND operation_order IS NOT NULL AND relation_change_kind IS NOT NULL"
            " AND entity_id IS NULL AND participant_id IS NULL AND program_work_id IS NULL"
            " AND business_call_id IS NULL AND declaration_id IS NULL"
            " AND plotline_subject_id IS NULL AND plotline_subject_title IS NULL"
            " AND plotline_description IS NULL AND plotline_before IS NULL AND plotline_after IS NULL"
            " AND description_action IS NULL AND description_value IS NULL"
            " AND representative_action IS NULL AND representative_value IS NULL AND tags_submitted IS NULL)"
            # 人物动态观测形状
            " OR (participant_id IS NOT NULL AND direct_producer_execution_id IS NULL"
            " AND operation_order IS NULL AND relation_id IS NULL AND entity_id IS NULL"
            " AND program_work_id IS NULL AND business_call_id IS NULL AND declaration_id IS NULL"
            " AND plotline_subject_id IS NULL AND plotline_subject_title IS NULL"
            " AND plotline_description IS NULL AND plotline_before IS NULL AND plotline_after IS NULL"
            " AND description_action IS NULL AND description_value IS NULL"
            " AND representative_action IS NULL AND representative_value IS NULL AND tags_submitted IS NULL"
            " AND relation_change_kind IS NULL AND identity_kind IS NULL AND reason IS NULL)"
            # 独立情节推进形状
            " OR (direct_producer_execution_id IS NOT NULL AND business_call_id IS NOT NULL"
            " AND operation_order IS NOT NULL AND plotline_subject_id IS NOT NULL"
            " AND plotline_subject_title IS NOT NULL AND plotline_description IS NOT NULL"
            " AND plotline_after IS NOT NULL"
            " AND entity_id IS NULL AND relation_id IS NULL AND participant_id IS NULL"
            " AND program_work_id IS NULL"
            " AND description_action IS NULL AND description_value IS NULL"
            " AND representative_action IS NULL AND representative_value IS NULL AND tags_submitted IS NULL"
            " AND relation_change_kind IS NULL AND identity_kind IS NULL AND reason IS NULL)"
            # 章末程序核对回执形状
            " OR (program_work_id IS NOT NULL AND direct_producer_execution_id IS NULL"
            " AND operation_order IS NULL AND entity_id IS NULL AND relation_id IS NULL"
            " AND participant_id IS NULL AND business_call_id IS NULL AND declaration_id IS NULL"
            " AND plotline_subject_id IS NULL AND plotline_subject_title IS NULL"
            " AND plotline_description IS NULL AND plotline_before IS NULL AND plotline_after IS NULL"
            " AND description_action IS NULL AND description_value IS NULL"
            " AND representative_action IS NULL AND representative_value IS NULL AND tags_submitted IS NULL"
            " AND relation_change_kind IS NULL AND identity_kind IS NULL AND reason IS NULL)",
            name="ck_graph_facts_shape",
        ),
        Index(
            "uq_graph_facts_producer_order",
            "direct_producer_execution_id",
            "operation_order",
            unique=True,
            postgresql_where=sql_text("direct_producer_execution_id IS NOT NULL AND business_call_id IS NULL"),
        ),
        Index(
            "uq_graph_facts_business_call",
            "business_call_id",
            unique=True,
            postgresql_where=sql_text("business_call_id IS NOT NULL"),
        ),
        Index(
            "uq_graph_facts_participant",
            "participant_id",
            unique=True,
            postgresql_where=sql_text("participant_id IS NOT NULL"),
        ),
        Index(
            "uq_graph_facts_program_work",
            "program_work_id",
            unique=True,
            postgresql_where=sql_text("program_work_id IS NOT NULL"),
        ),
        Index("idx_graph_facts_producer_execution", "direct_producer_execution_id"),
        {"comment": "图事实表：实体/关系/参与者/情节推进/程序核对五种互斥形状（运行从生产来源取得）"},
    )

    graph_fact_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="事实流水", default=new_id, autoincrement=False
    )
    # 真实生产执行（实体/关系/情节推进形状必填；人物观测从参与者来源取，不填）
    direct_producer_execution_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("executions.execution_id", ondelete="RESTRICT", name="graph_facts_producer_fkey"),
        nullable=True,
        comment="直接生产执行（实体/关系/情节推进）",
    )
    # 章末程序核对回执来源
    program_work_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("work_items.work_id", ondelete="RESTRICT", name="graph_facts_program_work_fkey"),
        nullable=True,
        comment="章末核对程序 work（回执形状）",
    )
    operation_order: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="执行内操作顺序（0 起）")
    business_call_id: Mapped[str | None] = mapped_column(Text, nullable=True, comment="情节推进的实际程序 call_id")
    effective_chapter_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="真实独立选章时的有效章节编号"
    )
    entity_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("graph_entities.entity_id", ondelete="RESTRICT", name="graph_facts_entity_fkey"),
        nullable=True,
        comment="实体目标",
    )
    relation_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("graph_relations.relation_id", ondelete="RESTRICT", name="graph_facts_relation_fkey"),
        nullable=True,
        comment="关系目标",
    )
    participant_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("declaration_participants.participant_id", ondelete="RESTRICT", name="graph_facts_participant_fkey"),
        nullable=True,
        comment="人物动态观测的源参与者（唯一）",
    )
    declaration_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_declarations.declaration_id", ondelete="RESTRICT", name="graph_facts_declaration_fkey"),
        nullable=True,
        comment="情节推进的可选来源声明",
    )
    description_action: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="description 操作（omit/set/clear）"
    )
    description_value: Mapped[str | None] = mapped_column(Text, nullable=True, comment="description 设置值")
    representative_action: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="代表标记操作（omit/set/clear）"
    )
    representative_value: Mapped[bool | None] = mapped_column(Boolean, nullable=True, comment="代表标记设置值")
    tags_submitted: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="标签集合显式提交：true 且零成员=清空；NULL=没提交；False=身份确认引用"
    )
    relation_change_kind: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="关系操作（assert/reinforce/weaken/retract/refine/supersede/break）"
    )
    identity_kind: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="同一身份判断（same/different）"
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="操作理由")
    plotline_subject_id: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="推进序列业务标识")
    plotline_subject_title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="本次提交的主体标题")
    plotline_description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="本次推进描述")
    plotline_before: Mapped[str | None] = mapped_column(Text, nullable=True, comment="推进前状态")
    plotline_after: Mapped[str | None] = mapped_column(Text, nullable=True, comment="推进后状态")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow, comment="创建时间")

    def __repr__(self) -> str:
        return f"<GraphFact(graph_fact_id={self.graph_fact_id})>"


class FactEntityTag(Base):
    "标签成员：去重且保留顺序（父事实 tags_submitted=true 且零行表示清空）"

    __tablename__ = "fact_entity_tags"
    __table_args__ = (
        UniqueConstraint("graph_fact_id", "tag_ordinal", name="uq_fact_entity_tags_business_key"),
        UniqueConstraint("graph_fact_id", "tag", name="uq_fact_entity_tags_tag"),
        {"comment": "事实标签表：标签集合的具名成员（有序、去重，不复制 entity/producer）"},
    )

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=new_id, autoincrement=False, comment="UUIDv7 独立主键"
    )
    graph_fact_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("graph_facts.graph_fact_id", ondelete="CASCADE", name="fact_entity_tags_fact_fkey"),
        comment="事实流水",
        nullable=False,
    )
    tag_ordinal: Mapped[int] = mapped_column(Integer, comment="标签序号（0 起）", nullable=False)
    tag: Mapped[str] = mapped_column(String(100), nullable=False, comment="标签文本")

    def __repr__(self) -> str:
        return f"<FactEntityTag(graph_fact_id={self.graph_fact_id}, tag={self.tag})>"
