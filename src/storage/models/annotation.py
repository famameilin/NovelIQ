"""
创建时间: 2026-03-15
创建者: TraeAI
任务: postgresql-migration
说明: 标注相关表 ORM 模型定义

本模块定义标注相关的数据表：
- ChunkAnnotation: 分块标注表
- ChunkCharacter: 分块角色表
- ChunkRelation: 分块关系表
- ChunkDialogue: 分块对话表
- ChunkForeshadowing: 分块伏笔表
- CharacterAppearance: 角色出场表

修改时间: 2026-03-16
修改者: TraeAI
修改内容: 将 ChunkAnnotation 和 ChunkForeshadowing 的主键改为复合主键 (chunk_id, run_id)，使用复合外键引用 chunks 表
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ChunkAnnotation(Base):
    """
    分块标注表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储分块的标注信息（情感、事件类型等）

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 将主键改为复合主键 (chunk_id, run_id)，使用复合外键引用 chunks 表
    """

    __tablename__ = "chunk_annotation"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    emotional_valence: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pivot_moment: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cliffhanger: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_foreshadowing: Mapped[int | None] = mapped_column(Integer, nullable=True)
    foreshadowing_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    foreshadowing_desc: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    """
    分块角色表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储分块中出现的角色信息
    """

    __tablename__ = "chunk_characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    role_function: Mapped[str | None] = mapped_column(String(50), nullable=True)
    action: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    emotion_score: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True, index=True
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
    """
    分块关系表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储分块中角色之间的关系变化
    """

    __tablename__ = "chunk_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    from_char: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_char: Mapped[str | None] = mapped_column(String(255), nullable=True)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    change: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True, index=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_chunk_relations_chunk_id", "chunk_id"),
        Index("idx_chunk_relations_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ChunkRelation(chunk_id={self.chunk_id}, from={self.from_char}, to={self.to_char})>"


class ChunkDialogue(Base):
    """
    分块对话表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储分块中的对话信息

    修改时间: 2026-03-25
    修改者: TraeAI
    修改内容: 添加 tone 字段，存储对话语气类型（强硬/温和/讽刺/恳求/命令/恐惧/惊慌）

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: fix-unknown-speaker-context
    修改内容: 添加 content 和 evidence 字段，便于追溯未知说话者的上下文

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: use-phase3-identity-clue-in-disambiguation
    修改内容: 添加 identity_clue 字段，存储 Phase 3 提取的身份线索
    """

    __tablename__ = "chunk_dialogues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    speaker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    identity_clue: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True, index=True
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
    """
    分块伏笔表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储分块中的伏笔分析结果

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 将主键改为复合主键 (chunk_id, run_id)，使用复合外键引用 chunks 表
    """

    __tablename__ = "chunk_foreshadowing"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    foreshadowing_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    anchor_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    anchor_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    """
    角色出场表

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 存储角色出场信息和身份线索
    """

    __tablename__ = "character_appearances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    raw_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    identity_clue: Mapped[str | None] = mapped_column(Text, nullable=True)
    clue_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=True, index=True
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
