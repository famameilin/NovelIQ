"""导出仓库实现与协议接口"""

from .annotation import (
    AnnotationRepository,
    CasePoolRepository,
    CaseResolutionMappingRepository,
    ChapterAnnotationRepository,
    DatabaseAnnotationQueryService,
    DialogueRecordRepository,
    ForeshadowingRepository,
)
from .base import BaseRepository, T
from .chapter_repository import ChapterRepository
from .chunk_repository import ChunkRepository, ChunkStyleData
from .diagnosis_repository import DiagnosisRepository
from .graph import EntitySnapshotRow, GraphChangeRow, GraphRepository, GraphSnapshotRow, RelationSnapshotRow
from .protocols import (
    AnnotationRepositoryProtocol,
    ChunkRepositoryProtocol,
    DiagnosisRepositoryProtocol,
    RunRepositoryProtocol,
    StatsRepositoryProtocol,
)
from .run_repository import RunRepository
from .stats import StatsRepository

__all__ = [
    "BaseRepository",
    "T",
    "ChapterRepository",
    "RunRepository",
    "AnnotationRepository",
    "ChapterAnnotationRepository",
    "CasePoolRepository",
    "DialogueRecordRepository",
    "ForeshadowingRepository",
    "CaseResolutionMappingRepository",
    "DatabaseAnnotationQueryService",
    "ChunkRepository",
    "ChunkStyleData",
    "RunRepositoryProtocol",
    "ChunkRepositoryProtocol",
    "AnnotationRepositoryProtocol",
    "StatsRepositoryProtocol",
    "DiagnosisRepositoryProtocol",
    "GraphRepository",
    "EntitySnapshotRow",
    "RelationSnapshotRow",
    "GraphSnapshotRow",
    "GraphChangeRow",
    "DiagnosisRepository",
    "StatsRepository",
]
