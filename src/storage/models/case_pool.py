"每个案例一行的登记与承诺模型"

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base


class Case(Base):
    "案例登记及承诺结果"

    __tablename__ = "case"
    __table_args__ = (
        CheckConstraint("type IN ('character', 'relation', 'dialogue', 'event')", name="ck_case_type"),
        CheckConstraint("status IN ('pending', 'resolved')", name="ck_case_status"),
        CheckConstraint("char_length(description) BETWEEN 1 AND 100", name="ck_case_description"),
        CheckConstraint(
            "(status = 'pending' AND promised_agent_id IS NULL) OR "
            "(status = 'resolved' AND promised_agent_id IS NOT NULL)",
            name="ck_case_promise",
        ),
        {"quote": True},
    )
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    producer_agent_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("agent.id", ondelete="RESTRICT"), nullable=True
    )
    promised_agent_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("agent.id", ondelete="RESTRICT"), nullable=True
    )
