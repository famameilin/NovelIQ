"""成功角色 work 的结果身份与书级案例，不保存运行期预算、租约或规则快照"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, naive_utcnow


class AnnotationWork(Base):
    """队列只在五个业务组件的同一成功事务内写入此表"""

    __tablename__ = "annotation_work"
    __table_args__ = (
        UniqueConstraint("run_id", "chapter_id", "role", name="uq_annotation_work_role"),
        CheckConstraint("role IN ('solo', 'structure', 'event', 'evidence')", name="ck_annotation_work_role"),
        CheckConstraint("state = 'saved'", name="ck_annotation_work_saved"),
        {"comment": "标注工作登记表：角色 work 成功落库的结果身份，与业务写入同事务提交"},
    )

    work_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="工作主键（uuid）")
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), comment="所属分析运行"
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="章节编号")
    role: Mapped[str] = mapped_column(String(20), nullable=False, comment="章内角色（solo/structure/event/evidence）")
    invocation_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="产生结果的 agent 调用 id")
    state: Mapped[str] = mapped_column(String(20), nullable=False, comment="登记状态（恒为 saved）")
    saved_at: Mapped[datetime] = mapped_column(
        DateTime, default=naive_utcnow, comment="落库时间"
    )


class BookCase(Base):
    """案例的业务内容只有 ID 和 description，登记状态与各章交付贡献同行保存"""

    __tablename__ = "book_cases"
    __table_args__ = (
        CheckConstraint("state IN ('pending', 'resolved', 'deferred', 'contested')", name="ck_book_case_state"),
        {"comment": "书级案例表：跨章案例的业务内容、登记状态与各章交付贡献"},
    )

    case_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="案例主键（uuid）")
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), comment="所属分析运行"
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, comment="案例描述")
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending",
        comment="案例状态（pending/resolved/deferred/contested）",
    )
    contributions: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}", comment="各章对案例的交付贡献"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=naive_utcnow, comment="创建时间"
    )
