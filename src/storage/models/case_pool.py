"书级案例及六种互斥案例条目的持久化模型"

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base, naive_utcnow

#: 案例类型封闭取值（问题类型，不唯一决定结构目标类型）
CASE_TYPES = ("character", "relation", "dialogue", "event")
#: 独立评审状态封闭取值（pending/resolved 由真实采纳交付投影）
CASE_REVIEW_STATES = ("deferred", "contested")


class BookCase(Base):
    "书级案例表：登记身份、明确目标与独立评审状态"

    __tablename__ = "book_cases"
    __table_args__ = (
        CheckConstraint("case_type IN ('character', 'relation', 'dialogue', 'event')", name="ck_book_cases_type"),
        CheckConstraint("char_length(description) <= 100", name="ck_book_cases_description_length"),
        CheckConstraint(
            "review_state IS NULL OR review_state IN ('deferred', 'contested')",
            name="ck_book_cases_review_state",
        ),
        CheckConstraint(
            "(automatic_declaration_id IS NOT NULL)::int + (entity_target_id IS NOT NULL)::int"
            " + (relation_target_id IS NOT NULL)::int + (dialogue_target_id IS NOT NULL)::int"
            " + (declaration_target_id IS NOT NULL)::int + (complete_event_target_id IS NOT NULL)::int"
            " + (pending_event_entry_id IS NOT NULL)::int"
            " + (dialogue_candidate_chapter_id IS NOT NULL)::int <= 1",
            name="ck_book_cases_at_most_one_target",
        ),
        CheckConstraint(
            "(dialogue_candidate_chapter_id IS NULL) = (dialogue_candidate_start IS NULL)"
            " AND (dialogue_candidate_chapter_id IS NULL) = (dialogue_candidate_end IS NULL)",
            name="ck_book_cases_dialogue_candidate_triple",
        ),
        CheckConstraint(
            "(registration_run_id IS NULL) = ("
            "(automatic_declaration_id IS NOT NULL)::int + (entity_target_id IS NOT NULL)::int"
            " + (relation_target_id IS NOT NULL)::int + (dialogue_target_id IS NOT NULL)::int"
            " + (declaration_target_id IS NOT NULL)::int + (complete_event_target_id IS NOT NULL)::int"
            " + (pending_event_entry_id IS NOT NULL)::int > 0)",
            name="ck_book_cases_registration_run_rule",
        ),
        Index("idx_book_cases_run_type", "registration_run_id", "case_type"),
        {"comment": "书级案例表：跨章案例登记与明确目标（不设 run+type+description 唯一键）"},
    )

    case_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="案例主键（uuid）", default=new_id, autoincrement=False
    )
    registration_run_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE", name="book_cases_run_fkey"),
        nullable=True,
        comment="登记运行（正式目标/候选观察可决定 run 时必须为空）",
    )
    case_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="案例类型（character/relation/dialogue/event）"
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, comment="案例描述（不超过100字）")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow, comment="创建时间")
    automatic_declaration_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_declarations.declaration_id", ondelete="RESTRICT", name="book_cases_auto_declaration_fkey"),
        nullable=True,
        comment="按声明自动登记的唯一自然目标",
    )
    entity_target_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("graph_entities.entity_id", ondelete="RESTRICT", name="book_cases_entity_target_fkey"),
        nullable=True,
        comment="实体目标",
    )
    relation_target_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("graph_relations.relation_id", ondelete="RESTRICT", name="book_cases_relation_target_fkey"),
        nullable=True,
        comment="关系目标（dangling_relation 的 node_id 指向关系而非实体）",
    )
    dialogue_target_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("dialogue_records.dialogue_id", ondelete="RESTRICT", name="book_cases_dialogue_target_fkey"),
        nullable=True,
        comment="对话目标",
    )
    declaration_target_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("event_declarations.declaration_id", ondelete="RESTRICT", name="book_cases_declaration_target_fkey"),
        nullable=True,
        comment="声明目标（普通描述登记）",
    )
    complete_event_target_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("complete_events.event_id", ondelete="RESTRICT", name="book_cases_event_target_fkey"),
        nullable=True,
        comment="完整事件目标",
    )
    pending_event_entry_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("case_entries.entry_id", ondelete="RESTRICT", name="book_cases_pending_entry_fkey", use_alter=True),
        nullable=True,
        comment="诊断失败候选的观察条目（目标可能从未发布成 complete_events）",
    )
    dialogue_candidate_chapter_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="对话候选章节编号（无正式对话记录时）"
    )
    dialogue_candidate_start: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="对话候选起始字符偏移")
    dialogue_candidate_end: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="对话候选结束字符偏移")
    registration_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="登记原因（与描述分离）")
    registration_paragraph_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="登记原文段号")
    review_state: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="独立评审状态（deferred/contested；pending/resolved 由采纳投影）"
    )

    def __repr__(self) -> str:
        return f"<BookCase(case_id={self.case_id}, case_type={self.case_type})>"


class CaseEntry(Base):
    "案例条目表（六种互斥形状，父子层级固定）"

    __tablename__ = "case_entries"
    __table_args__ = (
        CheckConstraint(
            "(case_id IS NOT NULL AND producer_execution_id IS NOT NULL AND adopted IS NOT NULL"
            " AND program_work_id IS NULL AND parent_entry_id IS NULL AND business_call_id IS NULL"
            " AND accepted_order IS NULL AND tool_name IS NULL AND receipt_bytes IS NULL"
            " AND narrative_link_id IS NULL AND warning_record_id IS NULL AND warning_report_id IS NULL"
            " AND warning_ordinal IS NULL AND attempted_case_reference IS NULL AND warning_message IS NULL"
            " AND candidate_producer_execution_id IS NULL AND pending_event_reference IS NULL"
            " AND pending_event_title IS NULL AND pending_event_chapter_id IS NULL)"
            " OR (case_id IS NOT NULL AND program_work_id IS NOT NULL AND adopted IS NULL"
            " AND producer_execution_id IS NULL AND parent_entry_id IS NULL AND business_call_id IS NULL"
            " AND accepted_order IS NULL AND tool_name IS NULL AND receipt_bytes IS NULL"
            " AND narrative_link_id IS NULL AND warning_record_id IS NULL AND warning_report_id IS NULL"
            " AND warning_ordinal IS NULL AND attempted_case_reference IS NULL AND warning_message IS NULL"
            " AND candidate_producer_execution_id IS NULL AND pending_event_reference IS NULL"
            " AND pending_event_title IS NULL AND pending_event_chapter_id IS NULL)"
            " OR (parent_entry_id IS NOT NULL AND business_call_id IS NOT NULL AND accepted_order IS NOT NULL"
            " AND tool_name IS NOT NULL AND receipt_bytes IS NOT NULL"
            " AND case_id IS NULL AND producer_execution_id IS NULL AND program_work_id IS NULL"
            " AND adopted IS NULL AND narrative_link_id IS NULL"
            " AND warning_record_id IS NULL AND warning_report_id IS NULL AND warning_ordinal IS NULL"
            " AND attempted_case_reference IS NULL AND warning_message IS NULL"
            " AND candidate_producer_execution_id IS NULL AND pending_event_reference IS NULL"
            " AND pending_event_title IS NULL AND pending_event_chapter_id IS NULL)"
            " OR (parent_entry_id IS NOT NULL AND narrative_link_id IS NOT NULL"
            " AND case_id IS NULL AND producer_execution_id IS NULL AND program_work_id IS NULL"
            " AND adopted IS NULL AND business_call_id IS NULL AND accepted_order IS NULL"
            " AND tool_name IS NULL AND receipt_bytes IS NULL"
            " AND warning_record_id IS NULL AND warning_report_id IS NULL AND warning_ordinal IS NULL"
            " AND attempted_case_reference IS NULL AND warning_message IS NULL"
            " AND candidate_producer_execution_id IS NULL AND pending_event_reference IS NULL"
            " AND pending_event_title IS NULL AND pending_event_chapter_id IS NULL)"
            " OR ((warning_record_id IS NOT NULL)::int + (warning_report_id IS NOT NULL)::int = 1"
            " AND warning_ordinal IS NOT NULL AND attempted_case_reference IS NOT NULL"
            " AND warning_message IS NOT NULL"
            " AND ((warning_report_id IS NOT NULL AND producer_execution_id IS NOT NULL)"
            " OR (warning_record_id IS NOT NULL AND producer_execution_id IS NULL))"
            " AND case_id IS NULL AND program_work_id IS NULL"
            " AND adopted IS NULL AND parent_entry_id IS NULL AND business_call_id IS NULL"
            " AND accepted_order IS NULL AND tool_name IS NULL AND receipt_bytes IS NULL"
            " AND narrative_link_id IS NULL"
            " AND candidate_producer_execution_id IS NULL AND pending_event_reference IS NULL"
            " AND pending_event_title IS NULL AND pending_event_chapter_id IS NULL)"
            " OR (candidate_producer_execution_id IS NOT NULL AND pending_event_reference IS NOT NULL"
            " AND pending_event_title IS NOT NULL AND pending_event_chapter_id IS NOT NULL"
            " AND case_id IS NULL AND producer_execution_id IS NULL AND program_work_id IS NULL"
            " AND adopted IS NULL AND parent_entry_id IS NULL AND business_call_id IS NULL"
            " AND accepted_order IS NULL AND tool_name IS NULL AND receipt_bytes IS NULL"
            " AND narrative_link_id IS NULL AND warning_record_id IS NULL AND warning_report_id IS NULL"
            " AND warning_ordinal IS NULL AND attempted_case_reference IS NULL AND warning_message IS NULL)",
            name="ck_case_entries_shape",
        ),
        Index(
            "uq_case_entries_support_execution",
            "case_id",
            "producer_execution_id",
            unique=True,
            postgresql_where=sql_text("producer_execution_id IS NOT NULL"),
        ),
        Index(
            "uq_case_entries_support_program",
            "case_id",
            "program_work_id",
            unique=True,
            postgresql_where=sql_text("program_work_id IS NOT NULL"),
        ),
        Index(
            "uq_case_entries_business_call",
            "business_call_id",
            unique=True,
            postgresql_where=sql_text("business_call_id IS NOT NULL"),
        ),
        Index(
            "uq_case_entries_parent_order",
            "parent_entry_id",
            "accepted_order",
            unique=True,
            postgresql_where=sql_text("accepted_order IS NOT NULL"),
        ),
        Index(
            "uq_case_entries_link",
            "parent_entry_id",
            "narrative_link_id",
            unique=True,
            postgresql_where=sql_text("narrative_link_id IS NOT NULL"),
        ),
        Index(
            "uq_case_entries_warning_record",
            "warning_record_id",
            "warning_ordinal",
            unique=True,
            postgresql_where=sql_text("warning_record_id IS NOT NULL"),
        ),
        Index(
            "uq_case_entries_warning_report",
            "warning_report_id",
            "producer_execution_id",
            "warning_ordinal",
            unique=True,
            postgresql_where=sql_text("warning_report_id IS NOT NULL"),
        ),
        Index(
            "uq_case_entries_pending_observation",
            "candidate_producer_execution_id",
            "pending_event_reference",
            unique=True,
            postgresql_where=sql_text("pending_event_reference IS NOT NULL"),
        ),
        {"comment": "案例条目表：支持→交付→连接及保存告警/未发布事件观察六种互斥形状"},
    )

    entry_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="条目主键（uuid）", default=new_id, autoincrement=False
    )
    case_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("book_cases.case_id", ondelete="CASCADE", name="case_entries_case_fkey"),
        nullable=True,
        comment="所属案例（支持形状）",
    )
    producer_execution_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("executions.execution_id", ondelete="RESTRICT", name="case_entries_producer_fkey"),
        nullable=True,
        comment="Agent 支持或诊断保存告警的真实执行",
    )
    program_work_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("work_items.work_id", ondelete="RESTRICT", name="case_entries_program_work_fkey"),
        nullable=True,
        comment="程序登记支持的工作",
    )
    parent_entry_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("case_entries.entry_id", ondelete="CASCADE", name="case_entries_parent_fkey"),
        nullable=True,
        comment="直接父条目（交付→支持；连接→交付）",
    )
    adopted: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="正式成功事务的真实采纳决定（不能由工具返回推断）"
    )
    business_call_id: Mapped[str | None] = mapped_column(Text, nullable=True, comment="交付的业务程序 call_id")
    accepted_order: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="run 内接受顺序")
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="交付工具名")
    receipt_bytes: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, comment="不可变回执字节（展示/审计）"
    )
    narrative_link_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("narrative_links.link_id", ondelete="RESTRICT", name="case_entries_link_fkey"),
        nullable=True,
        comment="实际写入的规范连接（回滚查叙事链路，不读旧边）",
    )
    warning_record_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("chapter_annotations.record_id", ondelete="CASCADE", name="case_entries_warning_record_fkey"),
        nullable=True,
        comment="标注保存告警来源记录",
    )
    warning_report_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("diagnosis_reports.report_id", ondelete="CASCADE", name="case_entries_warning_report_fkey"),
        nullable=True,
        comment="诊断保存告警来源报告",
    )
    warning_ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="告警序号（0 起）")
    attempted_case_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="失败回执中的案例标识观察（不要求案例存在）"
    )
    warning_message: Mapped[str | None] = mapped_column(String, nullable=True, comment="失败说明")
    candidate_producer_execution_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("executions.execution_id", ondelete="RESTRICT", name="case_entries_candidate_producer_fkey"),
        nullable=True,
        comment="诊断失败观察的真实来源执行",
    )
    pending_event_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="未发布事件的候选标识观察（不是假 FK）"
    )
    pending_event_title: Mapped[str | None] = mapped_column(String, nullable=True, comment="候选观察时的名称")
    pending_event_chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="候选观察来源章")

    def __repr__(self) -> str:
        return f"<CaseEntry(entry_id={self.entry_id})>"
