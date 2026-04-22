"""
创建时间: 2026-03-19
创建者: TraeAI
任务: 保存模型交互记录
说明: 存储每次模型调用的 prompt、response、think 内容

本模块定义模型交互记录表：
- ModelInteraction: 模型交互记录表，关联 chunk，保存每次调用的详细信息
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ModelInteraction(Base):
    """
    模型交互记录表

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 保存模型交互记录
    说明: 存储每次模型调用的 prompt、response、think 内容，关联到具体 chunk

    记录策略:
    - 每个 chunk 最多记录 4 次交互（本地模型最多3次重试 + 1次云端回退）
    - 每次交互记录 prompt、response、think 的完整内容
    - 支持 diagnose 阶段的交互记录
    """

    __tablename__ = "model_interactions"

    # 主键
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 关联信息
    chunk_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # 交互类型：annotate / diagnose / disambiguate 等
    interaction_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # 阶段信息：phase1 / phase2 / cloud_fallback 等
    phase: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 尝试次数：1-4
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # 模型信息
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)  # local / cloud

    # 交互内容
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    thinking: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 响应元数据
    response_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thinking_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_thinking: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)  # 0=False, 1=True
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thinking_state: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")

    # 状态信息
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")  # success / error
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 调用耗时（毫秒）

    __table_args__ = (
        # 复合外键关联 chunks 表
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        # 外键关联 analysis_runs 表
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        # 索引优化查询
        Index("idx_model_interactions_run_id", "run_id"),
        Index("idx_model_interactions_chunk_id_run_id", "chunk_id", "run_id"),
        Index("idx_model_interactions_type", "interaction_type"),
        Index("idx_model_interactions_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ModelInteraction("
            f"id={self.id}, chunk_id={self.chunk_id}, "
            f"run_id={self.run_id}, "
            f"type={self.interaction_type}, phase={self.phase})>"
        )
