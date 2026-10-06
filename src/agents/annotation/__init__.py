"""
章节标注 Agent 公共入口
"""

from .errors import (
    AnnotationAgentError,
    AnnotationAuthorizationError,
    AnnotationInputError,
    AnnotationProtocolError,
    AnnotationRetryableError,
)
from .schema import BoundChapterAnnotation
from .tools import (
    AnnotationQueryService,
    AnnotationToolLedger,
    build_annotation_tools,
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
