"""
LangGraph Agent 公共惰性入口
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_ANNOTATION_EXPORTS = {
    "AgentRunResult",
    "AnnotationAgentRunError",
    "ChapterAnnotation",
    "CompletionResult",
    "run_annotation_agent",
}
_DIAGNOSIS_EXPORTS = {
    "DiagnosisAgentRunError",
    "run_diagnosis_agent",
}

__all__ = [
    "AgentRunResult",
    "AnnotationAgentRunError",
    "ChapterAnnotation",
    "CompletionResult",
    "DiagnosisAgentRunError",
    "run_annotation_agent",
    "run_diagnosis_agent",
]


def __getattr__(name: str) -> Any:
    """2026-08-05 用于按需加载 Agent 公共出口并避免存储层导入形成环"""
    if name in _ANNOTATION_EXPORTS:
        return getattr(import_module("src.agents.annotation"), name)
    if name in _DIAGNOSIS_EXPORTS:
        return getattr(import_module("src.agents.diagnosis"), name)
    raise AttributeError(f"module 'src.agents' has no attribute {name!r}")
