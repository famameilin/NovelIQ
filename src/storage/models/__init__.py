"""
创建时间: 2026-03-15
创建者: TraeAI
任务: postgresql-migration
说明: ORM 模型聚合导出

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 使用 pgvector，移除旧的 embedding 字段导出

修改时间: 2026-03-16
修改者: TraeAI
任务: fix-disambiguation-three-phase
修改内容: 新增 DisambigCheckpoint 模型导出

本模块统一导出所有 ORM 模型和 Base 类。
"""

from src.storage.models.base import Base
from src.storage.models.core import AnalysisRun, DisambigCheckpoint
from src.storage.models.chunk import Chunk, ChunkStyle, ChunkCulture, ChunkTopic, ChunkEmbedding
from src.storage.models.annotation import (
    ChunkAnnotation,
    ChunkCharacter,
    ChunkRelation,
    ChunkDialogue,
    ChunkForeshadowing,
    CharacterAppearance,
)
from src.storage.models.entity import (
    Entity,
    EntityAlias,
    EntityRelation,
    EntitySnapshot,
    EntityRegistry,
)
from src.storage.models.analysis import (
    CloudAnalysis,
    EmotionCurve,
    RhythmCurve,
    GlobalStats,
    GlobalContext,
    ChunkSummary,
)
from src.storage.models.rag import TokenUsage, GraphStorage

EMBEDDING_DIM = 1536

__all__ = [
    "Base",
    "AnalysisRun",
    "DisambigCheckpoint",
    "Chunk",
    "ChunkStyle",
    "ChunkCulture",
    "ChunkTopic",
    "ChunkEmbedding",
    "ChunkAnnotation",
    "ChunkCharacter",
    "ChunkRelation",
    "ChunkDialogue",
    "ChunkForeshadowing",
    "CharacterAppearance",
    "Entity",
    "EntityAlias",
    "EntityRelation",
    "EntitySnapshot",
    "EntityRegistry",
    "CloudAnalysis",
    "EmotionCurve",
    "RhythmCurve",
    "GlobalStats",
    "GlobalContext",
    "ChunkSummary",
    "TokenUsage",
    "GraphStorage",
    "EMBEDDING_DIM",
]
