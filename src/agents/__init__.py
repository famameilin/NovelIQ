"""
LangGraph Agent 公共惰性入口
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_ANNOTATION_EXPORTS = {
    "BoundChapterAnnotation",
    "AnnotationAgent",
}
_DIAGNOSIS_EXPORTS = {
    "DiagnosisAgentRunError",
    "run_diagnosis_agent",
}

__all__ = [
    "BoundChapterAnnotation",
    "DiagnosisAgentRunError",
    "AnnotationAgent",
    "run_diagnosis_agent",
]


def __getattr__(name: str) -> Any:
    """用于按需加载 Agent 公共出口并避免存储层导入形成环"""
    if name in _ANNOTATION_EXPORTS:
        return getattr(import_module("src.agents.annotation"), name)
    if name in _DIAGNOSIS_EXPORTS:
        return getattr(import_module("src.agents.diagnosis"), name)
    raise AttributeError(f"module 'src.agents' has no attribute {name!r}")
