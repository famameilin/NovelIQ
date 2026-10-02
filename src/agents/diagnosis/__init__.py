"""
诊断 Agent 子包

仅保留 src.agents.__getattr__ 动态出口需要的 re-export
（run_diagnosis_agent 供 src.workflows.diagnose 使用）；其余使用方
一律从子模块导入：src.agents.diagnosis.runner / contract / evidence / tools。
"""

from .runner import DiagnosisAgentRunError, run_diagnosis_agent

__all__ = [
    "DiagnosisAgentRunError",
    "run_diagnosis_agent",
]
