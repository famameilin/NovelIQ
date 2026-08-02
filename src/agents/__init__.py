"""
Agent 能力包（LangGraph）

- annotation: 标注 Agent（阶段 1-4 合并 + 身份消歧集成进循环 + 超长章节子代理分派）
- diagnosis: 诊断 Agent（工具化自主取证）
"""

from .annotation import (
    AnnotationAgentRunError,
    AnnotationChunkResult,
    IdentityMemory,
    load_identity_memory,
    run_annotation_agent,
    save_identity_memory,
)
from .diagnosis import (
    DiagnosisAgentRunError,
    run_diagnosis_agent,
)

__all__ = [
    "AnnotationAgentRunError",
    "AnnotationChunkResult",
    "DiagnosisAgentRunError",
    "IdentityMemory",
    "load_identity_memory",
    "run_annotation_agent",
    "run_diagnosis_agent",
    "save_identity_memory",
]
