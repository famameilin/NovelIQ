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
from .graph import build_annotation_graph
from .runner import run_annotation_agent, validate_bound_annotation
from .schema import (
    AgentRunResult,
    BoundChapterAnnotation,
    CompletionResult,
)
from .tools import AnnotationQueryService, AnnotationToolLedger, build_annotation_tools

__all__ = [
    "AgentRunResult",
    "AnnotationAgentError",
    "AnnotationAuthorizationError",
    "AnnotationInputError",
    "AnnotationProtocolError",
    "AnnotationQueryService",
    "AnnotationRetryableError",
    "AnnotationToolLedger",
    "BoundChapterAnnotation",
    "CompletionResult",
    "build_annotation_graph",
    "build_annotation_tools",
    "run_annotation_agent",
    "validate_bound_annotation",
]
