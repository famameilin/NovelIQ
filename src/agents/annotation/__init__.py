"""
章节标注 Agent 公共入口
"""

from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.output_models import BoundChapterAnnotation
from src.agents.annotation.tool_factories import build_annotation_tools
from src.agents.annotation.tools import AnnotationQueryService

from .errors import (
    AnnotationAgentError,
    AnnotationAuthorizationError,
    AnnotationInputError,
    AnnotationProtocolError,
    AnnotationRetryableError,
)
from .validation import validate_bound_annotation

__all__ = [
    "AnnotationAgentError",
    "AnnotationAuthorizationError",
    "AnnotationInputError",
    "AnnotationProtocolError",
    "AnnotationQueryService",
    "AnnotationRetryableError",
    "AnnotationToolLedger",
    "BoundChapterAnnotation",
    "build_annotation_tools",
    "AnnotationAgent",
    "validate_bound_annotation",
]


def __getattr__(name: str):
    """共享域与存储层相互引用时，延迟加载 Agent 执行入口"""
    if name == "AnnotationAgent":
        from .agent import AnnotationAgent

        return AnnotationAgent
    raise AttributeError(name)
