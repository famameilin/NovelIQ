"""
创建时间: 2026-03-14
创建者: TraeAI
任务: Repository 基类和 Protocol 接口定义
说明: 导出所有 Repository 类和 Protocol 接口

修改时间: 2026-03-14
修改者: TraeAI
任务: 实现 RunRepository 类
修改内容: 新增 RunRepository 导出

修改时间: 2026-03-14
修改者: TraeAI
任务: Repository 层重构 - 实现 EntityRepository
修改内容: 添加 EntityRepository 导出

修改时间: 2026-03-14
修改者: TraeAI
任务: 实现 DiagnosisRepository 类
修改内容: 新增 DiagnosisRepository 导出

修改时间: 2026-03-14
修改者: TraeAI
任务: 实现 AnnotationRepository 类
修改内容: 新增 AnnotationRepository 导出

修改时间: 2026-03-14
修改者: TraeAI
任务: 实现 StatsRepository 类
修改内容: 新增 StatsRepository 导出

修改时间: 2026-03-14
修改者: TraeAI
任务: refactor-routes-use-repository
修改内容: 新增 ChunkRepository 导出

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - 拆分protocols.py
修改内容: 更新导入路径
"""

from .annotation import AnnotationRepository
from .base import BaseRepository, T
from .chunk_repository import ChunkRepository, ChunkStyleData
from .diagnosis_repository import DiagnosisRepository
from .entity import EntityRepository
from .graph import GraphRepository
from .protocols import (
    AnnotationRepositoryProtocol,
    ChunkRepositoryProtocol,
    DiagnosisRepositoryProtocol,
    EntityRepositoryProtocol,
    RunRepositoryProtocol,
    StatsRepositoryProtocol,
)
from .run_repository import RunRepository
from .stats import StatsRepository

__all__ = [
    "BaseRepository",
    "T",
    "RunRepository",
    "AnnotationRepository",
    "ChunkRepository",
    "ChunkStyleData",
    "RunRepositoryProtocol",
    "ChunkRepositoryProtocol",
    "AnnotationRepositoryProtocol",
    "StatsRepositoryProtocol",
    "EntityRepositoryProtocol",
    "DiagnosisRepositoryProtocol",
    "EntityRepository",
    "GraphRepository",
    "DiagnosisRepository",
    "StatsRepository",
]
