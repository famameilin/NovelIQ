"""
章节标注 Agent 公共入口
"""

from .errors import (
    AnnotationAgentError,
    AnnotationAuthorizationError,
    AnnotationConfigurationError,
    AnnotationInputError,
    AnnotationProtocolError,
    AnnotationRetryableError,
)
from .graph import build_annotation_graph
from .runner import AnnotationAgentRunError, run_annotation_agent, validate_chapter_annotation
from .schema import (
    AgentRunResult,
    ChapterAnnotation,
    ChapterAnnotationPatch,
    CompletionResult,
    Evidence,
)
from .tools import AnnotationQueryService, AnnotationToolLedger, build_annotation_tools

__all__ = [
    "AgentRunResult",
    "AnnotationAgentError",
    "AnnotationAgentRunError",
    "AnnotationAuthorizationError",
    "AnnotationConfigurationError",
    "AnnotationInputError",
    "AnnotationProtocolError",
    "AnnotationQueryService",
    "AnnotationRetryableError",
    "AnnotationToolLedger",
    "ChapterAnnotation",
    "ChapterAnnotationPatch",
    "CompletionResult",
    "Evidence",
    "build_annotation_graph",
    "build_annotation_tools",
    "run_annotation_agent",
    "validate_chapter_annotation",
]
