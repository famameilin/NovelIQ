"""
章节标注 Agent 公共入口
"""

from src.agents.annotation.errors import AnnotationAuthorizationError, AnnotationInputError, AnnotationProtocolError
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.output_models import BoundChapterAnnotation
from src.agents.annotation.tool_factories import build_annotation_tools
from src.agents.annotation.tools import AnnotationQueryService
from src.agents.errors import AgentError, AgentRetryableError

__all__ = [
    "AgentError",
    "AnnotationAuthorizationError",
    "AnnotationInputError",
    "AnnotationProtocolError",
    "AnnotationQueryService",
    "AgentRetryableError",
    "AnnotationToolLedger",
    "BoundChapterAnnotation",
    "build_annotation_tools",
    "AnnotationAgent",
]


def __getattr__(name: str):
    """共享域与存储层相互引用时，延迟加载 Agent 执行入口"""
    if name == "AnnotationAgent":
        from .agent import AnnotationAgent

        return AnnotationAgent
    raise AttributeError(name)
