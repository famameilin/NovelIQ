"""
创建时间: 2025-03-11
创建者: TraeAI
任务: 本地模型客户端模块

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 项目文件结构整理与拆解 - 添加新客户端类导出

修改时间: 2026-03-23
修改者: TraeAI
任务: unify-model-client-architecture
修改内容: AnnotationClient 和 DisambiguationClient 已移动到 src/models/
"""

from .base import TokenUsageCallback
from .embedding import EmbeddingClient
from .parser import extract_think_content, make_empty_annotation
from .schema import (
    ChunkAnnotation,
    CharacterSnapshot,
    DialogueSnapshot,
    RelationChangeSnapshot,
)
from .unified_client import UnifiedModelClient

__all__ = [
    "ChunkAnnotation",
    "CharacterSnapshot",
    "DialogueSnapshot",
    "EmbeddingClient",
    "extract_think_content",
    "make_empty_annotation",
    "RelationChangeSnapshot",
    "TokenUsageCallback",
    "UnifiedModelClient",
]
