"""
模型与工具调用审计及消息发件箱 ORM 模型

审计保持独立短事务；turn_ms = model_ms + tool_wall_ms 为读取计算；
供应商实报与程序 fallback 明确区分；bytes 文档仅原样审计/展示，不用于业务查询/修改。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base, naive_utcnow


class ModelCall(Base):
    "模型调用表（每条真实请求一行）"

    __tablename__ = "model_calls"
    __table_args__ = (
        CheckConstraint(
            "(execution_id IS NOT NULL AND turn_index IS NOT NULL AND standalone_run_id IS NULL"
            " AND standalone_chapter_id IS NULL AND standalone_task_type IS NULL"
            " AND standalone_call_type IS NULL)"
            " OR (execution_id IS NULL AND turn_index IS NULL AND standalone_run_id IS NOT NULL"
            " AND standalone_task_type IS NOT NULL AND standalone_call_type IS NOT NULL)",
            name="ck_model_calls_shape",
        ),
        Index(
            "uq_model_calls_execution_turn",
            "execution_id",
            "turn_index",
            unique=True,
            postgresql_where=sql_text("execution_id IS NOT NULL"),
        ),
        Index("idx_model_calls_status", "status"),
        Index("idx_model_calls_standalone_run", "standalone_run_id"),
        {"comment": "模型调用表：真实请求的模型/状态/用量/费用/计时/通信文档（Agent 或 standalone 恰一）"},
    )

    call_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="调用流水", default=new_id, autoincrement=False
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False, comment="模型名")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", comment="调用状态")
    error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="调用错误信息")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="结束时间")
    message_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, comment="审计消息幂等键（非空时唯一，缺失表示无键）"
    )

    # Agent 上下文（execution+turn 恰一于 standalone 组）
    execution_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("executions.execution_id", ondelete="CASCADE", name="model_calls_execution_fkey"),
        nullable=True,
        comment="所属真实 invocation",
    )
    turn_index: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="回合序号（execution 内 1 起）")

    # 非 Agent 独立上下文（不伪造成 work）
    standalone_run_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE", name="model_calls_standalone_run_fkey"),
        nullable=True,
        comment="独立调用所属分析运行",
    )
    standalone_chapter_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="独立调用章节编号（可空，run 内局部）"
    )
    standalone_task_type: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="独立任务类型")
    standalone_call_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="独立调用类型")

    # 用量分项与计账来源（reasoning/cache 是否含于其他分项沿供应商口径，不擅自相加）
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="输入 token 数")
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="输出 token 数")
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="缓存读取 token 数")
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="推理 token 数")
    accounting_source: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="计账来源（reported 等）")

    # 供应商实报总量（程序 fallback 不落列）与实际费用（不按当前单价重算）
    reported_total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="供应商实报总量")
    cost: Mapped[float | None] = mapped_column(Float, nullable=True, comment="本次实际费用")

    # 五类计时独立观测（turn_ms 为读取投影）
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="首 token 耗时（毫秒）")
    first_visible_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="首可见输出耗时（毫秒）")
    reasoning_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="推理耗时（毫秒）")
    model_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="模型耗时（毫秒）")
    tool_wall_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="工具墙钟耗时（毫秒）")

    # 真实通信/提示正文/审计观察/计时备注文档（原样审计，仅展示/重放）
    request_messages_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, comment="实际发送消息文档")
    raw_response_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, comment="供应商原始回执文档")
    context_observed_bytes: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, comment="当时审计上下文文档"
    )
    timing_notes_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, comment="有序计时诊断备注文档")

    def __repr__(self) -> str:
        return f"<ModelCall(call_id={self.call_id}, model={self.model}, status={self.status})>"


class AgentToolCall(Base):
    "工具调用表：每次真实外层工具调用的身份、顺序与观察字节"

    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        Index("uq_agent_tool_calls_call_index", "call_id", "call_index", unique=True),
        {"comment": "工具调用审计表：每个工具调用一行（原始参数与实际执行参数分列保存）"},
    )

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="工具调用流水", default=new_id, autoincrement=False
    )
    call_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("model_calls.call_id", ondelete="CASCADE", name="agent_tool_calls_call_fkey"),
        nullable=False,
        comment="所属模型调用",
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="工具名")
    call_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="调用内序号")
    status: Mapped[str] = mapped_column(String(20), nullable=False, comment="调用状态")
    error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="调用错误信息")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="开始时间")
    tool_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="实际测量耗时（毫秒）")
    message_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, comment="审计消息幂等键（非空时唯一）"
    )
    raw_args_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, comment="模型原始参数文档")
    executed_args_bytes: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, comment="程序实际执行参数文档"
    )
    response_observed_bytes: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, comment="原始工具返回文档"
    )
    receipt_observed_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, comment="原始程序回执文档")

    def __repr__(self) -> str:
        return f"<AgentToolCall(id={self.id}, tool={self.tool_name}, status={self.status})>"


class EventOutbox(Base):
    "SSE 发件箱表：实际展示消息、路由、稳定游标与投递时间"

    __tablename__ = "event_outbox"
    __table_args__ = (
        UniqueConstraint("run_id", "message_key", name="uq_outbox_run_message"),
        Index("idx_event_outbox_created", "created_at"),
        Index("idx_event_outbox_run_type", "run_id", "event_type"),
        {"comment": "SSE 事件发件箱表：消息身份、全局游标、路由与实际投递（emitted_bytes 原样重放）"},
    )

    message_key: Mapped[str] = mapped_column(String(255), nullable=False, comment="实际投递消息幂等键")
    event_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="消息身份", default=new_id, autoincrement=False
    )
    stream_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        nullable=False,
        unique=True,
        comment="全局单调游标（产生时分配）",
    )
    run_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE", name="event_outbox_run_fkey"),
        nullable=False,
        comment="真实路由运行",
    )
    chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="真实路由章节编号（可空）")
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, comment="事件类型")
    emitted_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, comment="实际发出消息字节")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow, comment="产生时间")
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="实际投递时间（未投递为空，不补创建时间）"
    )

    def __repr__(self) -> str:
        return f"<EventOutbox(event_id={self.event_id}, stream_id={self.stream_id})>"
