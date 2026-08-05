"""标注相关表 ORM 模型定义"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ARRAY, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ChunkAnnotation(Base):
    """分块标注表，存储情感、事件类型等结构化标注结果"""

    __tablename__ = "chunk_annotation"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    emotional_valence: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pivot_moment: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cliffhanger: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_foreshadowing: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_strong_setup: Mapped[int | None] = mapped_column(Integer, nullable=True)
    foreshadowing_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    setup_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    foreshadowing_desc: Mapped[str | None] = mapped_column(Text, nullable=True)
    setup_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_unresolved_now: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_payoff_family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payoff_likelihood: Mapped[str | None] = mapped_column(String(20), nullable=True)
    linked_setup_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_chunk_annotation_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ChunkAnnotation(chunk_id={self.chunk_id}, run_id={self.run_id})>"


class ChunkCharacter(Base):
    """分块角色表，存储分块中出现的角色信息"""

    __tablename__ = "chunk_characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    surface_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_slot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_global_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    global_skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    role_function: Mapped[str | None] = mapped_column(String(50), nullable=True)
    action: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    emotion_score: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_chunk_characters_chunk_id", "chunk_id"),
        Index("idx_chunk_characters_name", "name"),
        Index("idx_chunk_characters_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ChunkCharacter(chunk_id={self.chunk_id}, name={self.name})>"


class ChunkRelation(Base):
    """分块关系表，存储角色之间的关系变化与方向性"""

    __tablename__ = "chunk_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    from_char: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_char: Mapped[str | None] = mapped_column(String(255), nullable=True)
    from_reference_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_reference_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resolved_from_global_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_to_global_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference_skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    change: Mapped[str | None] = mapped_column(String(50), nullable=True)
    directionality: Mapped[str | None] = mapped_column(String(20), nullable=True, default="directed")
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    projection_status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="pending")
    projected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    projection_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_chunk_relations_chunk_id", "chunk_id"),
        Index("idx_chunk_relations_run_id", "run_id"),
        Index("idx_chunk_relations_projection_status", "run_id", "projection_status"),
    )

    def __repr__(self) -> str:
        return f"<ChunkRelation(chunk_id={self.chunk_id}, from={self.from_char}, to={self.to_char})>"


class ChunkDialogue(Base):
    """分块对话表，存储说话者候选、语气、内容和身份线索"""

    __tablename__ = "chunk_dialogues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    speaker_references: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    identity_clue: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_chunk_dialogues_chunk_id", "chunk_id"),
        Index("idx_chunk_dialogues_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ChunkDialogue(chunk_id={self.chunk_id}, speaker={self.speaker})>"


class ChunkForeshadowing(Base):
    """分块伏笔表，存储分块中的伏笔分析结果"""

    __tablename__ = "chunk_foreshadowing"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    is_strong_setup: Mapped[int | None] = mapped_column(Integer, nullable=True)
    foreshadowing_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    setup_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    anchor_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    anchor_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    setup_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_unresolved_now: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_payoff_family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payoff_likelihood: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_new_setup: Mapped[int | None] = mapped_column(Integer, nullable=True)
    linked_setup_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    setup_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_chunk_foreshadowing_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ChunkForeshadowing(chunk_id={self.chunk_id}, run_id={self.run_id})>"


class CharacterAppearance(Base):
    """角色出场表，存储角色出场信息和身份线索"""

    __tablename__ = "character_appearances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    identity_clue: Mapped[str | None] = mapped_column(Text, nullable=True)
    clue_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_character_appearances_chunk_id", "chunk_id"),
        Index("idx_character_appearances_raw_name", "raw_name"),
        Index("idx_character_appearances_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<CharacterAppearance(chunk_id={self.chunk_id}, raw_name={self.raw_name})>"
